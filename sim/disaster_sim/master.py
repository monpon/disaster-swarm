"""Central master computer: all perception and decision making happens here.

Inputs are only what the drones' ESP32 modules send over the mesh: JPEG camera frames and
IMU batches (`packets.py`). The master estimates every drone's pose (visual-inertial
odometry) and per-pixel depth (monocular depth network) itself, fuses the frames into its
map, plans, and pilots each drone with stick commands. It knows only the building's rough
outline (operator input). The VIO and depth network are simulated stand-ins
(`estimation.py`); they are the only code allowed to read the packets' `sim_truth`.

Mission phases:
  survey   -> drones circle the building and sweep the roof, looking for openings
  interior -> drones fan out through the openings and explore/scan the inside; idle drones
              re-scan low-confidence surfaces (a second look from another place)
  verify   -> a final sweep re-scans whatever is still unconfirmed (one pass, or rough
              after the point-cloud smoother) until it is confirmed or time runs out
  complete -> everything reachable is mapped; the swarm is recalled
"""
from __future__ import annotations

import dataclasses
import os
import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import torch
from scipy import ndimage
from scipy.optimize import linear_sum_assignment

from .align import Alignment, align_batch
from .comms import M_HOLD, M_MIN, LinkModel, plan_chain
from .gpu import DEV
from .entry import opening_cue, ray_angles, servo_sticks
from .detector import PERSON, PersonDetector
from .presage import triage
from .opening import DRONE_SIZE, fit_opening, plane_scale
from .estimation import SimulatedDepthNet, SimulatedVIO
from .packets import FramePacket, ImuPacket, StickCommand
from .pilot import Pilot
from .config import SimConfig
from .planner3d import NavGrid, RustNavGrid, to_waypoints
from .smoothing import Smoother
from .surface import Surface
from .radio import NOISE_DBM, SLAB_DB, TX_DBM, WALL_DB, capacity_for, path_loss_db
from .rustcore import RustMap, RustSurface
from .voxelmap import FREE_T, OCC_T, VoxelMap

IDLE, TAKEOFF, SURVEY, WAIT, ENTER, EXPLORE, INVESTIGATE, RELAY, RTB, LANDING, CHARGING, CRASHED = (
    "idle", "takeoff", "survey", "wait", "enter", "explore", "investigate", "relay", "rtb", "landing",
    "charging", "crashed")
WORKING = (SURVEY, ENTER, EXPLORE, INVESTIGATE, RELAY, WAIT)

CRUISE_POWER_W = 15.0
LOST_AFTER = 3.0
LOOK_TIME = 1.5
TILE = 4
RELAY_TARGET_BPS = 2.0e6
SURVEY_STANDOFF = 8.0
ASSOC_RADIUS = 3.0  # survivors are at least 6 m apart; sightings of one person (different drones, depth error) land within this
CONFIRM_DETECTIONS = 3
CONFIRM_RANGE = 6.0
INVESTIGATE_TIMEOUT = 40.0
VITALS_TIMEOUT = 45.0  # a drone holds this long in front of a survivor for a vitals reading before giving up
MAX_PLANS_PER_TICK = 4
OUTDOOR_MARGIN = 3
STAGE_DIST = 4.0  # m in front of an opening where the servo starts
STUCK_CMD, STUCK_S = 0.4, 6.0  # commanded m/s that counts as trying to move; window length (s)
ENTRY_COOLDOWN_S = 30.0
ENTRY_MAX_FAILS = 3
PENALTY_S = 30.0
SERVO_TIMEOUT_S = 45.0
VERIFY_PENALTY = 25.0  # verify tiles cost this much extra while exploration is still going
VERIFY_NPASS = 2  # surfaces seen from fewer separate passes than this need a re-scan
VERIFY_RESID = 0.10  # ... as do surfaces the smoother finds rougher than this (m)
SMOOTH_BATCH = 5000
SCOUT_TILE = 6  # m: frontier cells are grouped into tiles this big
SCOUT_LOOK_S = 2.0  # pause at a frontier so the map catches up with what the camera sees
PERIM_TEAM = 4  # drones flying the exterior loops while the rest enter
LATENCY_S = 0.9  # frame -> decision -> command -> response, end to end
DECEL = 3.0  # m/s^2 the drone can stop at
CLEAR_MARGIN = 1.0  # m kept in reserve when judging how fast is safe
V_GOV_MAX = 4.0
CRAB_MAX = 0.45  # rad (26 deg): how far from the direction of travel a survey drone may turn to face a wall
MAX_SLOTS = 6  # relay posts at once (a third or so of the fleet)
RELIEF_SOC = 0.40  # a relay below this charge is relieved by a fresh drone
SLOT_IDLE_S = 25.0  # a slot nothing uses for this long is given up
DEMAND_TTL_S = 6.0
LEASH_TAU = 3.0  # s ahead the motion filter looks
RELAY_SETTLE_S = 10.0  # a relay on station this long without restoring contact -> chain another

_SIX = ndimage.generate_binary_structure(3, 1)


def _dilate(mask: np.ndarray, iters: int) -> np.ndarray:
    import gpucore
    return gpucore.dilate(np.ascontiguousarray(mask, dtype=np.uint8), iters).astype(bool)
_DIRS = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]])


@dataclass
class DroneRecord:
    id: int
    pad: tuple[float, float]
    mode: str = IDLE
    pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    soc: float = 1.0
    grounded: bool = True
    crashed: bool = False
    last_seen: float = -1.0
    mode_since: float = 0.0
    path: list = field(default_factory=list)
    yaws: list | None = None
    speed: float | None = None
    task: tuple | None = None  # ("frontier" | "surface", tile key)
    task_vantage: np.ndarray | None = None
    arrived_t: float | None = None
    candidate: int | None = None
    gap: dict | None = None  # the suspicious gap this drone is sent to look at
    cue_t: float = -1.0
    entry: int | None = None
    serves: int | None = None  # relay: the drone it keeps connected
    yaw: float = 0.0
    frozen: bool = False  # ESP reports neutral-stick failsafe (lost the command link)
    link_cap: float = 0.0
    hops: int = 0
    trail: list = field(default_factory=list)
    survey_done: bool = False
    stage: str | None = None  # ENTER sub-state: approach | align | servo | backoff | legacy
    stage_since: float = 0.0
    cue: dict | None = None  # latest opening seen in this drone's own depth frame
    servo_start: np.ndarray | None = None
    servo_dir: np.ndarray | None = None
    servo_d0: float = 4.0
    cool: dict = field(default_factory=dict)  # entry id -> time before which not to retry it
    leg: dict | None = None  # the survey/scout leg this drone is flying
    parent: int = -2  # next hop toward the base (-1 = the base)
    parent_snr: float = -100.0
    neighbors: list = field(default_factory=list)
    holding: bool = False  # the drone's own link reflex has it holding at the edge of coverage
    backlog: int = 0
    slot: dict | None = None  # the relay slot this drone occupies
    was_lost: bool = False
    hold_since: float | None = None
    fresh_t: float = -1e9  # capture time of the latest frame
    fresh_clear: float = 12.0  # nearest obstacle straight ahead in that frame (m)
    brake_until: float = -1.0
    leash_k: float = 1.0
    leash_dbg: tuple = (0.0, 0.0, 0.0)
    slow_why: str = ""  # what is holding this drone's speed down (shown in the state, for debugging)
    leash_t: float = -1.0
    leash_dir: np.ndarray | None = None
    reeling: bool = False
    scout_tile: tuple | None = None  # frontier tile this drone is heading for
    scout_ready_t: float = 0.0
    leg_map: list | None = None  # path index -> leg waypoint index
    leg_path: list | None = None
    leg_partial: bool = False  # the leg path stops at the edge of cleared space
    leg_replan_t: float = -1.0
    win: list | None = None  # stuck-detection window: start time, start position, commanded distance


@dataclass
class Entry:
    id: int
    center: np.ndarray
    normal: np.ndarray
    w: float
    h: float
    side: str
    blocked: bool = False
    fails: int = 0
    retired: bool = False  # given up after repeated failed attempts
    busy: int | None = None  # the drone currently approaching/passing it
    ok: int = 0
    t_first: float = 0.0
    t_seen: float = 0.0
    fitted: bool = False  # measured by a drone looking at it (a coarse map detection is not enough to fly through)
    rect: tuple | None = None  # (axis, face, (h0, h1), (z0, z1)): the measured opening in metres
    quality: float = 0.0  # share of the rectangle that really looked through
    fail_log: list = field(default_factory=list)
    fail_rect: tuple | None = None

    @property
    def confirmed(self) -> bool:
        """Measured, and seen again and again for a few seconds: not a one-frame artefact."""
        return self.fitted and self.t_seen - self.t_first >= 2.0

    def to_dict(self) -> dict:
        return {"id": self.id, "center": [round(float(v), 2) for v in self.center],
                "normal": [float(v) for v in self.normal], "w": float(self.w), "h": float(self.h),
                "side": self.side, "blocked": self.blocked or self.retired, "fitted": self.fitted}


@dataclass
class Candidate:
    id: int
    pos: np.ndarray
    n_det: int = 1
    best_range: float = 1e9
    confirmed: bool = False
    dismissed: bool = False
    assigned: int | None = None
    assigned_t: float = 0.0
    attempts: int = 0
    vitals: dict | None = None  # the (simulated) Presage reading: hr, rr, confidence
    urgency: int = -1  # 0-100 from the vitals; -1 = not assessed yet
    tier: str = ""  # IMMEDIATE / URGENT / DELAYED
    vitals_tries: int = 0
    vitals_t0: float | None = None
    view_fails: int = 0  # times no spot to look at them from was found
    retry_t: float = 0.0
    t_assessed: float = 0.0

    def to_dict(self) -> dict:
        return {"id": self.id, "pos": [round(float(v), 2) for v in self.pos], "n": self.n_det,
                "confirmed": self.confirmed, "dismissed": self.dismissed, "drone": self.assigned,
                "vitals": self.vitals, "urgency": self.urgency, "tier": self.tier, "t_assessed": round(self.t_assessed, 1)}


class MasterController:
    def __init__(self, cfg: SimConfig, shape, outline, pads: np.ndarray, base, rng: np.random.Generator, core=None,
                 plan_entries: list | None = None, plan_vox: np.ndarray | None = None):
        self.cfg = cfg
        self.core = core  # the Rust/CUDA core, when in use
        # Plan-assisted: the building plan (its walls, floors and doors) is given, so routes are planned on it and the map
        # only has to be looked at, not discovered. Registering to the plan also keeps the pose estimate from drifting far.
        self.plan_air = None if plan_vox is None else (np.asarray(plan_vox) == 0)
        self.max_slots = MAX_SLOTS if plan_vox is None else 5  # relay posts at once (the known building keeps the backbone short)
        self.plan_solid = None if plan_vox is None else ~self.plan_air
        self.map = RustMap(core, shape, cfg) if core is not None else VoxelMap(shape, cfg)
        self.shape = tuple(shape)
        self.env_known = False
        self.keep = None
        self.x0 = self.y0 = self.x1 = self.y1 = 0
        self.top = 1
        self.base = np.array(base, dtype=float)
        self.drones = [DroneRecord(i, (float(pads[i, 0]), float(pads[i, 1]))) for i in range(len(pads))]
        self.phase = "scout" if outline is None else "operate"
        self.phase_since = 0.0
        self.scout_attempts = 0
        self.entries: list[Entry] = []
        self._mesh_t = -1.0
        self.detector = PersonDetector() if (core is not None and getattr(cfg, "detector", False)) else None
        self.person_search = True  # the console's detection settings (the "detection" command): look for people at all,
        self.person_conf = 0.45    # and the detector confidence a person box needs
        self._det_t: dict[int, float] = {}
        self._dbg_n = 0
        self.suspects: list[dict] = []  # gaps in a wall that probably are not gaps: a drone goes to look
        self.filled: list[tuple] = []  # wall rectangles confirmed solid and filled: (axis, layer, a0, a1, b0, b1)
        self.candidates: list[Candidate] = []
        self.events: list[dict] = []
        self.tick = 0
        self.seq = 0
        self.nav: NavGrid | None = None
        self.ignore = np.zeros(self.shape, dtype=bool)
        self.penalty: dict[tuple, float] = {}  # nav cells to avoid after a drone got stuck: expiry time
        self.near_occ = np.zeros(self.shape, dtype=bool)
        self.verified = np.zeros(self.shape, dtype=bool)  # surfaces that got their re-scan
        self.verify_since: float | None = None
        self.verify_empty_since: float | None = None
        self.smoother = Smoother() if core is None else None
        self.fuse_q: queue.Queue = queue.Queue(maxsize=6)
        self.fuse_out: queue.Queue = queue.Queue()
        self.fuse_busy = False
        self.fuse_ms = 0.0
        self.t_now = 0.0
        self._fuse_stop = threading.Event()
        if core is None:
            threading.Thread(target=self._fuse_loop, name="fuse", daemon=True).start()
        self.surface = RustSurface(core) if core is not None else Surface(shape)  # TSDF + marching cubes
        self.prng = np.random.default_rng(7)
        self.align_dp: list[float] = []
        self.unreachable: dict[tuple, float] = {}
        self.targets: list[dict] = []
        self.done_since: float | None = None
        sx, sy, sz = self.shape
        # Usable half of the vertical field of view: the camera is fixed to the nose, so a
        # target must sit within this elevation of the vantage point to be seen.
        self.half_vfov = np.deg2rad(cfg.cam_vfov_deg / 2 - 6.0)
        self.interior = np.zeros(self.shape, dtype=bool)
        self.outdoor = np.ones(self.shape, dtype=bool)
        self.legs: list[dict] = []  # exterior legs: any drone may fly any leg that is open
        self.gap_tries: dict[tuple, int] = {}
        self.ext_cov = 0.0  # share of the building's outer surface that has been seen
        self.entry_change_t = 0.0
        self._gaps: list = []
        self.first_inside_t: float | None = None
        self.brakes = 0
        self.home_len: dict[int, tuple] = {}
        self._cone = None
        self.scout_fail: dict[tuple, float] = {}
        self.link = LinkModel(self.map)
        self.link.field.optimistic = plan_vox is not None  # plan-assisted: a lattice vertex inside a wall must not veto a whole area
        self.slots: list[dict] = []
        self.demand: dict = {}  # key -> (point, time): places that need coverage
        self.lost_events = 0
        self.slot_n = 0
        self.demand_planned: dict = {}
        self._nodes: list[np.ndarray] = [np.array(base, dtype=float)]
        self._nodes_plan: list[np.ndarray] = [np.array(base, dtype=float)]  # ... plus posts that have a relay on the way
        self.scout_idle_since: float | None = None
        self.plan_assist = plan_entries is not None
        if outline is None:
            # Nothing is known about the site except its extent: open air everywhere until the
            # scouts find the building.
            self._set_envelope(None)
            self._seed_launch_area(pads)
        else:
            self._set_envelope(outline)
            self._begin_legs(self._plan_survey())
        if plan_entries:
            self._seed_plan_entries(plan_entries)
        n = len(pads)
        self.vio = SimulatedVIO(n, cfg, base, rng)
        self.vio.exact = plan_vox is not None  # registered to the plan: no pose drift
        self.depth_sigmas = (cfg.depth_scale_sigma, cfg.depth_region_sigma) if plan_vox is None else (0.0, 0.0)
        self.depthnet = SimulatedDepthNet(cfg, rng)
        self.pilot = Pilot(n, cfg.max_speed)
        self._az = self._el = None
        self.last_depth: list = [None] * n  # latest depth-network output per drone (for the viewer)
        self.frame_need = 1.1 * cfg.camera_hz * cfg.jpeg_bytes * 8  # bits/s a camera stream needs

    # ---------------------------------------------------------------- envelope
    def _set_envelope(self, outline, replan: bool = True) -> None:
        """(Re)derive everything that depends on where the building is. With `outline=None`
        the building is unknown: all open air, no interior."""
        sx, sy, sz = self.shape
        outdoor = np.ones(self.shape, dtype=bool)
        interior = np.zeros(self.shape, dtype=bool)
        if outline is not None:
            self.x0, self.y0, self.x1, self.y1, self.top = (int(v) for v in outline)
            self.env_known = True
            interior[self.x0 + 1:self.x1 - 1, self.y0 + 1:self.y1 - 1, 1:self.top] = True
            # Outdoor flight keeps OUTDOOR_MARGIN from the building: the pilot flies on VIO
            # estimates that can be a metre or more off.
            m_ = OUTDOOR_MARGIN
            outdoor[max(self.x0 - m_, 0):self.x1 + m_, max(self.y0 - m_, 0):self.y1 + m_, :self.top + m_] = False
        outdoor[:, :, 0] = False
        outdoor[:, :, sz - 2:] = False
        self.interior, self.outdoor = interior, outdoor
        if outline is not None and self.core is not None and self.cfg.known_outline:
            # the outer walls and the roof are fixed references the aligner can pin every frame to
            x0, x1, y0, y1, zt = float(self.x0), float(self.x1), float(self.y0), float(self.y1), float(self.top + 1)
            rows = [[0, x0, y0, y1, 0.0, zt, 2.0, 0], [0, x1, y0, y1, 0.0, zt, 2.0, 0],
                    [1, y0, 0.0, zt, x0, x1, 2.0, 0], [1, y1, 0.0, zt, x0, x1, 2.0, 0],
                    [2, zt, x0, x1, y0, y1, 1.0, 0]]
            self.core.set_landmarks(np.asarray(rows, dtype=np.float32))
        self.map.sparse2d = outdoor[:, :, 1].copy()

    def _seed_launch_area(self, pads: np.ndarray) -> None:
        """The launch area is known to be clear (the operator is standing in it), so the first
        scouts have somewhere to fly."""
        free = self.map.grid(self.map.lo)
        for x, y in pads:
            x, y = int(x), int(y)
            free[max(x - 7, 0):x + 8, max(y - 7, 0):y + 8, 1:10] = -20

    def _scout_frontiers(self):
        m = self.map
        zs = int(self.cfg.scout_alt)
        sx, sy, _ = self.shape
        free = m.grid(m.free)[:, :, zs]
        occ = m.grid(m.occupied)[:, :, max(zs - 1, 0):zs + 2].any(axis=2)
        inb = np.zeros((sx, sy), dtype=bool)
        inb[5:sx - 5, 5:sy - 5] = True
        unknown = ~(free | occ) & inb
        near = ndimage.binary_dilation(occ, iterations=2)
        keep2 = self.keep.any(axis=2) if self.keep is not None else np.zeros((sx, sy), dtype=bool)
        fr = free & ndimage.binary_dilation(unknown) & ~near & ~keep2 & inb
        return fr, unknown

    def _assign_scout(self, t: float) -> None:
        """Frontier exploration of the outside, closest to the base first: each free scout
        flies (through space already seen to be clear) to the nearest unexplored edge, looks,
        and the edge moves out. The swarm stays compact, so the mesh stays connected, and no
        drone ever flies into space the map has not cleared."""
        for r in self.drones:
            if r.scout_tile is not None and r.mode != SURVEY:
                r.scout_tile = None  # went home, crashed...: the tile is up for grabs again
        fr, unknown = self._scout_frontiers()
        zs = float(self.cfg.scout_alt)
        enroute = {r.scout_tile for r in self.drones if r.scout_tile is not None}
        tiles = {}
        for x, y in np.argwhere(fr):
            tiles.setdefault((int(x) // SCOUT_TILE, int(y) // SCOUT_TILE), []).append((int(x), int(y)))
        cands = []
        for key, cells in tiles.items():
            if len(cells) < 2 or key in enroute or self.scout_fail.get(key, -1) > t:
                continue
            c = min(cells, key=lambda c: (c[0] - self.base[0]) ** 2 + (c[1] - self.base[1]) ** 2)
            cands.append((float(np.hypot(c[0] - self.base[0], c[1] - self.base[1])), key, c))
        cands.sort()
        uncovered = False
        admitted = []
        for c in cands:  # only places the backbone already covers; for the rest, ask for a relay first
            pt = np.array([c[2][0] + 0.5, c[2][1] + 0.5, zs])
            if self._covered(pt):
                admitted.append(c)
            else:
                uncovered = True
                self._need(("scout", c[1]), pt, t)
        cands = admitted
        if self.phase == "operate" and self.env_known:  # building known: only look around it
            def near_building(c):
                x, y = c[2]
                return (self.x0 - 25 < x < self.x1 + 25) and (self.y0 - 25 < y < self.y1 + 25)
            cands = [c for c in cands if near_building(c)]
        free_drones = [r for r in self.drones if r.mode == WAIT and not self.lost(r, t) and not r.grounded
                       and r.scout_tile is None and t >= r.scout_ready_t and r.pos[2] > 2.0]
        busy = bool(enroute) or any(r.mode in (TAKEOFF, IDLE) and not r.survey_done for r in self.drones)
        if not cands:
            waiting = enroute or uncovered  # not idle while relays are being placed
            self.scout_idle_since = self.scout_idle_since if (self.scout_idle_since is not None and not waiting) \
                else (t if not waiting else None)
            return
        self.scout_idle_since = None
        if not free_drones:
            return
        cands = cands[:max(len(free_drones) * 3, 6)]
        cost = np.array([[0.7 * c[0] + 0.5 * float(np.hypot(c[2][0] - r.pos[0], c[2][1] - r.pos[1])) for c in cands]
                         for r in free_drones])
        rows, cols = linear_sum_assignment(cost)
        for i, j in sorted(zip(rows, cols), key=lambda ij: cost[ij]):
            r, (_, key, (cx, cy)) = free_drones[i], cands[j]
            look = unknown[max(cx - 6, 0):cx + 7, max(cy - 6, 0):cy + 7]
            ux, uy = np.nonzero(look)
            if len(ux):
                yaw = float(np.arctan2(uy.mean() + max(cy - 6, 0) - cy, ux.mean() + max(cx - 6, 0) - cx))
            else:
                yaw = float(np.arctan2(cy - self.base[1], cx - self.base[0]))
            goal = (cx + 0.5, cy + 0.5, zs)
            path = self._path_cells(r.pos, goal, strict=True, max_exp=60000)
            if path is None:
                self.scout_fail[key] = t + 40.0
                continue
            r.path = path
            r.yaws = self._fill_yaws(r.pos, path, [None] * (len(path) - 1) + [yaw])
            r.speed, r.scout_tile = 2.4, key
            self._set_mode(r, SURVEY, t)

    def _plan_scout(self, offset: float = 0.0, alt: float | None = None) -> list[list]:
        """Lanes across the whole site at low altitude: the forward camera sees walls and roof
        edges ahead, which is how the building shows up in the map."""
        sx, sy, _ = self.shape
        z = alt if alt is not None else self.cfg.scout_alt
        margin = 8.0
        pts = []
        # First a lap round the edge of the site: it sees whatever stands near the boundary, so
        # the building's far sides are found even though the lanes cannot cross it.
        cx, cy = sx / 2, sy / 2
        x0, x1, y0, y1 = margin, sx - margin, margin, sy - margin
        ring = [(x, y0) for x in np.arange(x0, x1, 10.0)] + [(x1, y) for y in np.arange(y0, y1, 10.0)] \
            + [(x, y1) for x in np.arange(x1, x0, -10.0)] + [(x0, y) for y in np.arange(y1, y0, -10.0)]
        pts += [((float(x), float(y), float(z)), float(np.arctan2(cy - y, cx - x))) for x, y in ring]
        for j, y in enumerate(np.arange(margin + offset, sy - margin, self.cfg.scout_spacing)):
            xs = np.arange(margin, sx - margin + 1, 10.0)
            if j % 2:
                xs = xs[::-1]
            yaw = 0.0 if j % 2 == 0 else np.pi
            pts += [((float(x), float(y), float(z)), yaw) for x in xs]
        return self._split_legs(pts)

    def _split_legs(self, pts: list, per_leg: int = 3) -> list[list]:
        """Cut a route into short legs (a few waypoints each): whoever is free takes the next
        one, so nobody sits idle while others have long stretches left, and a drone that has
        to go home leaves only a little for someone else to pick up."""
        return [pts[i:i + per_leg] for i in range(0, len(pts), per_leg)]

    def _update_envelope(self, t: float) -> None:
        """Estimate the building's footprint and roof height from the map itself: tall solid
        columns, the largest connected blob of them. Only ever grows once found."""
        if self.tick % 4:
            return
        m = self.map
        occ = m.grid(m.occupied)
        sz = self.shape[2]
        col = occ[:, :, 2:9].sum(axis=2) >= 4
        col = ndimage.binary_closing(col, iterations=2)
        lab, n = ndimage.label(col)
        if n == 0:
            return
        areas = ndimage.sum(col, lab, range(1, n + 1))
        k = int(np.argmax(areas)) + 1
        if areas[k - 1] < 250:
            return
        comp = lab == k
        # Walls are the rows/columns with a long run of solid column; clutter touching the
        # building only adds short stubs, so take the extent where the profile is substantial.
        def span(c):
            idx = np.nonzero(c >= 0.3 * c.max())[0]
            return int(idx.min()), int(idx.max()) + 1
        x0, x1 = span(comp.sum(axis=1))
        y0, y1 = span(comp.sum(axis=0))
        if x1 - x0 < 25 or y1 - y0 < 25:
            return  # not enough of it seen yet to call it a building
        foot = comp[x0:x1, y0:y1]
        top = int(min(np.nonzero(occ[x0:x1, y0:y1][foot].any(axis=0))[0].max(), sz - 4))
        new = (x0, y0, x1, y1, top)
        if self.env_known:
            new = (new[0], new[1], new[2], new[3], max(new[4], self.top))  # the roof only rises
            old = (self.x0, self.y0, self.x1, self.y1, self.top)
            if max(abs(a - b) for a, b in zip(new, old)) < 2:
                return
        self._set_envelope(new, replan=self.phase == "scout")

    # ------------------------------------------------------------------ inputs
    def on_frames(self, pkts: list, t: float) -> None:
        """Hand a batch of received frames to the fuse worker (everything numeric for the whole
        batch runs there as a handful of GPU kernels, overlapped with physics and planning on
        this thread). Poses come from the VIO here, because the VIO is this thread's state."""
        if not pkts:
            return
        poses, rots = [], []
        for p in pkts:
            pos, rot = self.vio.pose(p.drone, p.sim_truth)
            poses.append(pos)
            rots.append(rot)
        want_cue = [self.drones[p.drone].mode == ENTER and self.drones[p.drone].stage in ("align", "servo")
                    and self.drones[p.drone].entry is not None for p in pkts]
        job = {"pkts": pkts, "poses": poses, "rots": rots, "want_cue": want_cue, "t": t}
        if self.core is not None:  # ~0.5 ms on the core: fuse inline, no worker thread
            self._deliver(self._fuse_rust(job), t)
            self._person_sightings(t)
            if t - self._mesh_t >= 0.15:  # mesh what these frames just showed, straight away (bounded: it shares the thread)
                self._mesh_t = t
                self.surface.step(t, 64, 0.0, 4)
            return
        try:
            self.fuse_q.put(job, timeout=0.5)
        except queue.Full:  # the worker is far behind: fuse here rather than lose the frames
            self._deliver(self._fuse(job), t)

    def apply_fuse_results(self, t: float) -> None:
        """Apply what the fuse worker found (alignment corrections for the VIO, forward
        clearance and the emergency brake, survivor sightings): master state changes only here."""
        while True:
            try:
                res = self.fuse_out.get_nowait()
            except queue.Empty:
                return
            self._deliver(res, t)

    def _fuse_rust(self, job: dict) -> dict:
        """The same batch of frames, fused by the Rust core (one call: depth network, alignment,
        carving, hits, passes, classification, point store)."""
        pkts, want = job["pkts"], job["want_cue"]
        B, m = len(pkts), self.map
        res = self.core.fuse(
            [p.slot for p in pkts], np.stack(job["poses"]).astype(np.float32), np.stack(job["rots"]).astype(np.float32),
            np.array([p.t for p in pkts], dtype=np.float32), np.array([p.drone for p in pkts], dtype=np.int32),
            [int(p.thumb) for p in pkts], int(self.prng.integers(1 << 62)), self.depth_sigmas[0],
            self.depth_sigmas[1], self.cfg.depth_max, self.tick)
        m._gen += 1
        m.frames += B
        m.npts = int(res["npts"])
        a = np.asarray(res["ares"])
        als = []
        m.align_n += B
        why = np.bincount(a[:, 22].astype(int), minlength=7)[:7]
        self.align_why = getattr(self, "align_why", np.zeros(7, dtype=np.int64)) + why
        self.align_ngood = 0.9 * getattr(self, "align_ngood", 0.0) + 0.1 * float(a[:, 23].mean())
        for b in range(B):
            if a[b, 0] > 0.5:
                m.align_ok += 1
                als.append(Alignment(a[b, 1:4].astype(float), a[b, 4:13].reshape(3, 3).astype(float), float(a[b, 13]), int(a[b, 19]),
                                     a[b, 14:17].astype(float), float(a[b, 17]), float(a[b, 18]), float(a[b, 20]), float(a[b, 21])))
            else:
                als.append(None)
        est = np.asarray(self.core.estimates(B))
        H, W = self.cfg.cam_h, self.cfg.cam_w
        for b, p in enumerate(pkts):
            self.last_depth[p.drone] = est[b].reshape(H, W)
        pos_c, rot_c = np.asarray(res["pos"]).astype(float), np.asarray(res["rot"]).astype(float)
        det = {}
        sv = np.asarray(res["surv"])
        if self.detector is not None:
            # People are found by the detector on the camera frames, at most twice a second per drone
            pick = [b for b, p in enumerate(pkts) if not p.thumb and not self.drones[p.drone].grounded
                    and p.t - self._det_t.get(p.drone, -1.0) >= 0.5]
            if pick and self.person_search and not self.detector.busy and self.detector.ready:
                frames = np.asarray(self.core.rgbs([int(pkts[b].slot) for b in pick])).reshape(len(pick), H, W, 3)
                ctx = [{"drone": pkts[b].drone, "t": pkts[b].t, "pos": pos_c[b].copy(), "rot": rot_c[b].copy(),
                        "depth": est[b].reshape(H, W).copy(), "rgb": frames[i].copy() if os.environ.get("DISASTER_DET_DEBUG") else None}
                       for i, b in enumerate(pick)]
                if self.detector.submit(ctx, frames):
                    for b in pick:
                        self._det_t[pkts[b].drone] = pkts[b].t
            sv = np.zeros((0, 6))
        for b in np.unique(sv[:, 0].astype(int)) if len(sv) else []:
            sel = sv[:, 0].astype(int) == b
            det[int(b)] = (sv[sel, 1:4].astype(float), sv[sel, 4].astype(float))
        return {"pkts": pkts, "poses": [pos_c[b] for b in range(B)], "rots": [rot_c[b] for b in range(B)], "als": als,
                "clear": np.asarray(res["clear"]), "cue": {b: est[b].reshape(H, W) for b in range(B) if want[b]}, "det": det}

    def _fuse_loop(self) -> None:
        while not self._fuse_stop.is_set():
            try:
                job = self.fuse_q.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                t0 = time.perf_counter()
                self.fuse_out.put(self._fuse(job))
                self.fuse_ms = self.fuse_ms * 0.8 + (time.perf_counter() - t0) * 1000 * 0.2
            except Exception as e:  # never take the sim down
                print(f"fuse error: {e!r}", flush=True)
            finally:
                self.fuse_busy = self.fuse_q.qsize() > 0

    @torch.no_grad()
    def _fuse(self, job: dict) -> dict:
        """The GPU half of frame ingestion for one batch (runs in the fuse worker)."""
        pkts, poses, rots = job["pkts"], list(job["poses"]), list(job["rots"])
        m, dev = self.map, DEV
        B = len(pkts)
        if True:  # no long lock: a torn read of the map is harmless for planning, and the planner must not wait
            truth = torch.stack([p.sim_truth["depth"] for p in pkts])  # (B,H,W), never left the GPU
            depth = self.depthnet.estimate_batch(truth, [p.thumb for p in pkts])
            dflat = depth.reshape(B, -1)
            drones = torch.as_tensor([p.drone for p in pkts], device=dev)
            tt = torch.as_tensor([p.t for p in pkts], device=dev, dtype=torch.float32)
            pos_t = torch.as_tensor(np.stack(poses), device=dev, dtype=torch.float32)
            rot_t = torch.as_tensor(np.stack(rots), device=dev, dtype=torch.float32)
            dirs = torch.einsum("nk,bjk->bnj", m.t_rays, rot_t)
            m.align_n += B
            als = align_batch(m, pos_t, dirs, dflat, tt, drones)
            scale = np.ones(B, dtype=np.float32)
            for b, al in enumerate(als):
                if al is not None:
                    m.align_ok += 1
                    poses[b], rots[b], scale[b] = poses[b] + al.dp, al.rot @ rots[b], al.scale
            if any(a is not None for a in als):
                pos_t = torch.as_tensor(np.stack(poses), device=dev, dtype=torch.float32)
                rot_t = torch.as_tensor(np.stack(rots), device=dev, dtype=torch.float32)
                sc = torch.as_tensor(scale, device=dev)
                depth, dflat = depth * sc[:, None, None], dflat * sc[:, None]
                dirs = torch.einsum("nk,bjk->bnj", m.t_rays, rot_t)
            for b, p in enumerate(pkts):
                self.last_depth[p.drone] = depth[b]
            # what each frame shows straight ahead (drift-immune), for the brake and the speed governor
            if self._az is None:
                self._az, self._el = ray_angles(m.k.body_rays)
            if self._cone is None:
                self._cone = (np.abs(self._az) < 0.26) & (np.abs(self._el) < 0.2)
            cone = torch.as_tensor(np.flatnonzero(self._cone), device=dev)
            dc = dflat[:, cone]
            clear = torch.where(dc > 0, dc, torch.full_like(dc, float("inf"))).min(1).values.clamp(max=12.0).cpu().numpy()
            cue_depth = {b: depth[b].cpu().numpy() for b in range(B) if job["want_cue"][b]}
            rgb = torch.stack([p.rgb.reshape(-1, 3) for p in pkts])
            self.surface.add_batch(pos_t, dirs, dflat, rgb)
            det = m.integrate_batch(pos_t, rot_t, dflat, rgb, tt, drones, self.tick)
        return {"pkts": pkts, "poses": poses, "rots": rots, "als": als, "clear": clear, "cue": cue_depth, "det": det}

    def _deliver(self, res: dict, t: float) -> None:
        pkts, poses, rots = res["pkts"], res["poses"], res["rots"]
        for b, al in enumerate(res["als"]):
            if al is None:
                continue
            self.align_dp.append(float(np.linalg.norm(al.dp)))
            self.align_dp = self.align_dp[-200:]
            if al.cross >= 0.3:  # only against what other drones mapped: not chasing its own drift
                self.vio.correct(pkts[b].drone, al.obs_dp, al.obs_dyaw)
        for b, p in enumerate(pkts):
            r = self.drones[p.drone]
            self._note_clear(r, p.t, t, rots[b], float(res["clear"][b]))
            if b in res["cue"] and r.mode == ENTER and r.stage in ("align", "servo") and r.entry is not None:
                self._update_cue(r, p.t, poses[b], rots[b], res["cue"][b])
        for b, (pts, dist) in res["det"].items():
            used = np.zeros(len(pts), dtype=bool)
            for k in range(len(pts)):  # one detection per cluster of survivor pixels
                if used[k]:
                    continue
                near = np.linalg.norm(pts - pts[k], axis=1) < ASSOC_RADIUS
                used |= near
                self._associate(pts[near].mean(axis=0), float(dist[near].min()), pkts[b].drone, t)

    def close(self) -> None:
        self._fuse_stop.set()
        if self.detector is not None:
            self.detector.close()
        if self.smoother is not None:
            self.smoother.close()
        self.surface.close()

    def _note_clear(self, r: DroneRecord, t_cap: float, t: float, rot, clear: float) -> None:
        """Nearest obstacle straight ahead in this frame (drift-immune: it is measured from the
        drone), and the emergency brake: if the drone cannot stop in what it shows, centre the
        sticks now rather than at the next control tick."""
        r.fresh_t, r.fresh_clear = t_cap, clear
        heading = rot[:, 0]
        vf = max(0.0, float(r.vel[0] * heading[0] + r.vel[1] * heading[1]))
        if vf > 0.3 and r.fresh_clear < vf * LATENCY_S + vf * vf / (2 * DECEL) + 0.5 and r.mode not in (TAKEOFF, LANDING):
            if t >= r.brake_until:
                self.brakes += 1
            r.brake_until = t + 0.8

    def _update_cue(self, r: DroneRecord, t: float, pos, rot, depth) -> None:
        """While a drone lines up with / flies through an opening, find the opening in its frame."""
        if r.mode != ENTER or r.stage not in ("align", "servo") or r.entry is None:
            return
        if t - r.cue_t < 0.2:
            return  # the opening is found in the frame at 5 Hz: it is a few ms of image work per drone
        r.cue_t = t
        e = self.entries[r.entry]
        if self._az is None:
            self._az, self._el = ray_angles(self.map.k.body_rays)
        to = rot.T @ (e.center - pos)
        expected = np.array([np.arctan2(to[1], to[0]), np.arctan2(to[2], np.hypot(to[0], to[1]))])
        ax = 0 if abs(e.normal[0]) >= abs(e.normal[1]) else 1
        fit = None
        if e.rect is not None and abs(e.normal[2]) < 0.5:
            yaw = float(np.arctan2(rot[1, 0], rot[0, 0]))
            fit = fit_opening(depth, self.map.k.body_rays, pos, yaw, ax, float(e.rect[1]), e.center)
        if fit is not None and fit["w"] >= 0.8 and fit["h"] >= 0.6:
            cue = {"az": fit["az"], "el": fit["el"], "d": fit["d"], "fill": fit["fill"],
                   "margin": min(fit["w"] / 2, fit["h"] / 2) - DRONE_SIZE}
        else:
            cue = opening_cue(depth, self._az, self._el, expected)
        if cue is not None:
            cue["t"] = t
            h, w = depth.shape
            cue["clear"] = float(np.median(depth[h // 2 - 1:h // 2 + 2, w // 2 - 2:w // 2 + 3][depth[h // 2 - 1:h // 2 + 2, w // 2 - 2:w // 2 + 3] > 0])) \
                if (depth[h // 2 - 1:h // 2 + 2, w // 2 - 2:w // 2 + 3] > 0).any() else 99.0
            r.cue = cue

    def on_telemetry(self, m: ImuPacket, t: float) -> None:
        r = self.drones[m.drone]
        if m.t < r.last_seen:
            return
        if self.lost(r, t) and not m.crashed:
            self._reconnected(r, t)
        self.vio.update(m.drone, m.t, m.sim_truth)
        r.pos, rot = self.vio.pose(m.drone, m.sim_truth)
        r.vel = self.vio.velocity(m.drone, m.sim_truth)
        r.yaw = float(np.arctan2(rot[1, 0], rot[0, 0]))
        r.soc, r.grounded, r.last_seen, r.frozen = m.battery, m.grounded, m.t, m.failsafe
        r.link_cap, r.hops = m.link_bps, m.hops
        r.parent, r.neighbors, r.holding, r.backlog = m.parent, m.neighbors, m.holding, m.backlog
        r.parent_snr = next((s for n, s in m.neighbors if n == m.parent), r.parent_snr if m.link_bps > 0 else -100.0)
        if not r.trail or np.linalg.norm(r.trail[-1] - r.pos) > 2.0:
            r.trail.append(r.pos.copy())
            r.trail = r.trail[-300:]
        if m.crashed and not r.crashed:
            r.crashed = True
            self._set_mode(r, CRASHED, t)
            self._release(r)
            self._event(t, f"Drone {r.id} lost (crash)", "error")

    def on_vitals(self, drone: int, cand: int, reading: dict, t: float) -> None:
        """A vitals reading (Presage, simulated) for survivor `cand`, taken by `drone`: score how urgently they need help,
        and let the drone go if it is still holding on them."""
        r = self.drones[drone]
        c = self.candidates[cand]
        c.vitals = reading
        c.urgency, c.tier = triage(reading["hr"], reading["rr"], reading["confidence"])
        c.t_assessed = t
        self._event(t, f"Survivor #{c.id}: heart rate {reading['hr']}, breathing {reading['rr']}/min "
                       f"(confidence {reading['confidence']:.0%}) -> {c.tier}, urgency {c.urgency}/100 [simulated Presage]",
                    "error" if c.tier == "IMMEDIATE" else "warn" if c.tier == "URGENT" else "success")
        if r.mode == INVESTIGATE and r.candidate == cand:
            self._release(r)
            self._set_mode(r, EXPLORE if self._inside(r.pos) else WAIT, t)
            r.path, r.task = [], None

    def triage_list(self) -> list[dict]:
        """Confirmed survivors, most urgent first (those not yet assessed last)."""
        rows = [c for c in self.candidates if c.confirmed]
        rows.sort(key=lambda c: (c.vitals is None, -c.urgency, c.id))
        return [c.to_dict() for c in rows]

    def _person_sightings(self, t: float) -> None:
        """Turn the detector's boxes into survivor sightings: the person's position is where the box's middle looks, at
        the frame's own depth there."""
        if self.detector is None:
            return
        H, W = self.cfg.cam_h, self.cfg.cam_w
        rays = self.map.k.body_rays
        for ctx_list, dets_list in self.detector.poll():
            for ctx, dets in zip(ctx_list, dets_list):
                for x1, y1, x2, y2, conf, cls in dets:
                    if int(cls) != PERSON or conf < self.person_conf:
                        continue
                    w, h = x2 - x1, y2 - y1
                    if w < 10 or h < 10:
                        continue  # a few pixels: too far to be sure
                    xa, ya = int(x1 + 0.3 * w), int(y1 + 0.3 * h)
                    patch = ctx["depth"][ya:max(int(y2 - 0.3 * h), ya + 1), xa:max(int(x2 - 0.3 * w), xa + 1)]
                    valid = patch[patch > 0]
                    if len(valid) < 3:
                        continue
                    d = float(np.median(valid))
                    if d > 10.0:
                        continue  # the detector is reliable within a few metres; a far "person" is a wall or a window
                    # Is the box the size of a person? Camera focal lengths in pixels (square pixels).
                    fx = (W / 2) / np.tan(np.deg2rad(self.cfg.cam_hfov_deg) / 2)
                    fy = (H / 2) / np.tan(np.deg2rad(self.cfg.cam_vfov_deg) / 2)
                    w_m, h_m = w * d / fx, h * d / fy
                    if not (0.2 <= w_m <= 2.3 and 0.2 <= h_m <= 2.3):
                        continue  # a wall strip or a window frame, not a body
                    # the middle of the box is the body (the corners are whatever is behind it): one compact thing, not a
                    # surface receding into the distance
                    if np.percentile(valid, 90) - np.percentile(valid, 10) > 1.2:
                        continue
                    col, row = int(np.clip((x1 + x2) / 2, 0, W - 1)), int(np.clip((y1 + y2) / 2, 0, H - 1))
                    pt = ctx["pos"] + ctx["rot"] @ rays[row * W + col] * d
                    if ctx.get("rgb") is not None and self._dbg_n < 120:
                        from PIL import Image, ImageDraw
                        self._dbg_n += 1
                        im = Image.fromarray(ctx["rgb"]); dr = ImageDraw.Draw(im)
                        dr.rectangle([x1, y1, x2, y2], outline=(0, 255, 0))
                        os.makedirs(os.path.expanduser("~/det/live"), exist_ok=True)
                        im.save(os.path.expanduser(f"~/det/live/{self._dbg_n:03d}_c{conf:.2f}_d{d:.1f}_p{pt[0]:.0f}_{pt[1]:.0f}_{pt[2]:.0f}.png"))
                    if self.env_known and not (self.x0 + 1.0 < pt[0] < self.x1 - 1.0 and self.y0 + 1.0 < pt[1] < self.y1 - 1.0
                                               and 0.0 < pt[2] < self.top):
                        continue  # survivors are inside the building (not on its outer wall), whose outline the master has been given
                    self._associate(pt, d, ctx["drone"], t)

    def _associate(self, p: np.ndarray, rng: float, drone: int, t: float) -> None:
        for c in self.candidates:
            if np.linalg.norm(c.pos - p) < ASSOC_RADIUS:
                c.pos += (p - c.pos) / (c.n_det + 1)
                c.n_det += 1
                c.best_range = min(c.best_range, rng)
                if not c.confirmed and c.n_det >= CONFIRM_DETECTIONS and c.best_range <= CONFIRM_RANGE:
                    c.confirmed = True
                    fl = int(c.pos[2] // self.cfg.story) + 1
                    self._event(t, f"Survivor #{c.id} confirmed on floor {fl} by drone {drone}", "success")
                return
        self.candidates.append(Candidate(len(self.candidates), p.copy(), best_range=rng))
        self._event(t, f"Drone {drone} feed: possible survivor at ({p[0]:.0f}, {p[1]:.0f}, {p[2]:.0f})", "info")

    # ---------------------------------------------------------------- planning
    def step(self, t: float) -> None:
        self.tick += 1
        self.t_now = t
        self._smooth()
        # plan-assisted: the building is known, so unexplored interior is not assumed to eat the signal
        self.link.refresh(self.interior if self.plan_air is None else np.zeros_like(self.interior))
        self.link.update_coverage(self._nodes_plan, t)
        self._build_nav(t)
        self._update_envelope(t)
        self._detect_entries(t)
        self._update_modes(t)
        if self.phase in ("operate", "verify"):
            self._find_targets(t)
            self._dispatch_investigations(t)
            self._release_for_entry(t)
            self._gap_checks(t)
            self._assign_entries(t)
            self._allocate(t)
        if self.phase in ("scout", "operate"):
            self._assign_scout(t)
        if self.phase in ("scout", "operate", "verify"):
            self._plan_backbone(t)
        self._check_paths(t)

    def _opening_rows(self) -> np.ndarray:
        """Detected windows and doors as rectangles in their wall, for the mesher to square off."""
        rows = []
        for e in self.entries:
            if e.blocked or not e.confirmed or abs(e.normal[2]) > 0.5:
                continue
            if e.rect is not None:
                a, face, (h0, h1), (z0, z1) = e.rect
                inward = 1.0 if e.normal[a] > 0 else -1.0
                rows.append([a, face, face + inward, h0, h1, z0, z1, 0.0])  # both faces of the 1 m wall
                continue
            a = 0 if abs(e.normal[0]) >= abs(e.normal[1]) else 1
            u = 1 - a
            c = float(e.center[a])
            rows.append([a, c - 0.3, c + 0.3, e.center[u] - e.w / 2, e.center[u] + e.w / 2,
                         e.center[2] - e.h / 2, e.center[2] + e.h / 2, 0.0])
        return np.asarray(rows, dtype=np.float32).reshape(-1, 8)

    def _smooth(self) -> None:
        """Merge the smoothing worker's last batch and hand it the next one."""
        if self.core is not None:  # the core smooths on the device: ~1 ms for thousands of points
            if self.tick % 20 == 0 and hasattr(self.surface, "set_openings"):
                self.surface.set_openings(self._opening_rows())
            self.surface.step(self.t_now)
            self.map.smooth_step(SMOOTH_BATCH)
            if self.tick % 10 == 0:
                self.map.redirty_hidden()
            return
        res = self.smoother.poll()
        if res is not None:
            self.map.apply_smoothing(*res)
        if self.tick % 10 == 0:
            self.map.redirty_hidden()
        if not self.smoother.busy:
            job = self.map.smooth_job(SMOOTH_BATCH)
            if job is not None:
                self.smoother.submit(job)

    def control(self, t: float) -> list[tuple[int, StickCommand]]:
        """Stick commands for every drone the master can still reach (run at telemetry rate)."""
        cmds: list[tuple[DroneRecord, StickCommand]] = []
        for r in self.drones:
            if r.crashed or self.lost(r, t) or r.last_seen < 0:
                continue
            idle = r.mode in (IDLE, CHARGING) or (r.mode == LANDING and r.grounded)
            cell = tuple(int(np.clip(v, 0, s - 1)) for v, s in zip(np.floor(r.pos), self.shape))
            if r.mode == ENTER and r.stage == "approach" and self.near_occ[cell]:
                r.speed = min(r.speed or 0.6, 0.6)  # creep near surfaces: the estimate is off by metres
            if r.mode == ENTER and r.stage == "servo":
                cmd = self._servo_command(r, t)
            else:
                cmd = self.pilot.command(r, idle, r.mode == LANDING)
            cmd.retreat = r.mode in (RTB, LANDING, TAKEOFF) or r.reeling
            cmd.cam = "nav" if r.mode == RELAY else "full"
            cmds.append((r, cmd))
        # link margin for every drone that needs a fresh look, in one GPU query
        self._leash_prepare([(r, c) for r, c in cmds if r.mode not in (RTB, LANDING, TAKEOFF, RELAY)], t)
        out = []
        for r, cmd in cmds:
            if r.mode not in (RTB, LANDING, TAKEOFF, RELAY):
                cmd = self._leash(r, cmd, t)
                if cmd.mode == "fly" and not cmd.retreat:  # back-pressure: let the buffer drain
                    k = 0.0 if r.backlog > 100 else (0.5 if r.backlog > 60 else 1.0)
                    cmd.vx, cmd.vy, cmd.vz = cmd.vx * k, cmd.vy * k, cmd.vz * k
                cmd = self._speed_governor(r, cmd, t)
            out.append((r.id, cmd))
            self._watch_stuck(r, cmd, t)
        return out

    def _cmd_velocity(self, r: DroneRecord, cmd: StickCommand):
        if cmd.mode != "fly" or cmd.retreat or r.grounded:
            return None
        c, s = np.cos(r.yaw), np.sin(r.yaw)
        v = np.array([c * cmd.vx - s * cmd.vy, s * cmd.vx + c * cmd.vy, cmd.vz])
        sp = float(np.linalg.norm(v))
        return (v, sp) if sp >= 0.1 else None

    def _leash_prepare(self, items: list, t: float) -> None:
        """Predicted link margin now and LEASH_TAU s ahead for every drone whose cached value is
        stale, from one batched query (3 nearest backbone nodes + the parent link)."""
        need = []
        for r, cmd in items:
            vs = self._cmd_velocity(r, cmd)
            if vs is None:
                continue
            v, sp = vs
            d = v / sp
            if r.leash_dir is None or t - r.leash_t >= 0.25 or float(np.dot(r.leash_dir, d)) < 0.9:
                need.append((r, v, d))
        if not need:
            return
        A, Bp, rows = [], [], []
        for r, v, d in need:
            nodes = sorted(self._nodes_plan, key=lambda n: float(np.linalg.norm(n - r.pos)))[:3]
            pp = None
            if r.parent_snr > -50 and r.parent != -2:
                pp = self.base if r.parent == -1 else self.drones[r.parent].pos
            start = len(A)
            for n in nodes:
                A += [r.pos, r.pos + v * LEASH_TAU]
                Bp += [n, n]
            if pp is not None:
                A.append(r.pos)
                Bp.append(pp)
            rows.append((start, len(nodes), pp is not None))
        s = self.link.snr_many(np.asarray(A), np.asarray(Bp))
        for (r, v, d), (start, nn, has_pp) in zip(need, rows):
            seg = s[start:start + 2 * nn].reshape(nn, 2)
            now, ahead = float(seg[:, 0].max()), float(seg[:, 1].max())
            corr = float(np.clip(r.parent_snr - s[start + 2 * nn], -12.0, 12.0)) if has_pp else 0.0
            ahead += corr
            k = 1.0
            if ahead < M_MIN and ahead < now + corr:
                k = float(np.clip((ahead - M_HOLD) / (M_MIN - M_HOLD), 0.0, 1.0))
                self._need(("leash", r.id), r.pos + v * LEASH_TAU, t)
            r.leash_k, r.leash_t, r.leash_dir = k, t, d
            r.leash_dbg = (now, ahead, corr)

    def _servo_command(self, r: DroneRecord, t: float) -> StickCommand:
        """Sticks that steer on the opening seen in the drone's own latest frame."""
        e = self.entries[r.entry]
        cue = r.cue
        self.pilot.seq += 1
        yaw_in = float(np.arctan2(e.normal[1], e.normal[0]))
        if cue is None or t - cue["t"] > 0.8:  # no fresh view: hold, face the opening's normal
            err = (yaw_in - r.yaw + np.pi) % (2 * np.pi) - np.pi
            return StickCommand(r.id, self.pilot.seq, "fly", 0.0, 0.0, 0.0, float(np.clip(1.5 * err, -0.6, 0.6)))
        vx, vy, vz, yaw = servo_sticks(cue, r.servo_d0, cue.get("clear", 99.0))
        return StickCommand(r.id, self.pilot.seq, "fly", vx, vy, vz, yaw)

    @staticmethod
    def _governor(clear: float) -> float:
        """Fastest speed (m/s) from which the drone can still stop in `clear` metres, given the
        end-to-end latency and its braking: v*LATENCY + v^2/(2*DECEL) <= clear - margin."""
        if clear <= CLEAR_MARGIN:
            return 0.0
        v = DECEL * (-LATENCY_S + np.sqrt(LATENCY_S ** 2 + 2.0 * (clear - CLEAR_MARGIN) / DECEL))
        return float(min(v, V_GOV_MAX))

    def _map_clear(self, r: DroneRecord, d: np.ndarray, unknown_blocks: bool = True) -> float:
        """Distance along unit direction d through cells the map has seen free (cells the drone
        itself flew through count as free); stops at the first occupied cell, and at the first
        unknown cell too unless `unknown_blocks` is off (then fresh frames are the evidence)."""
        steps = np.arange(0.5, 12.5, 0.5)
        pts = r.pos[None, :] + d[None, :] * steps[:, None]
        if self.plan_air is not None:  # the plan says where the walls are
            if r.mode == ENTER:
                return 12.0  # crossing an opening: the frame's own depth (fresh_clear) is the evidence, not a drifted voxel
            ix = np.floor(pts).astype(int)
            ok = ((ix >= 0) & (ix < np.array(self.shape))).all(axis=1)
            free = np.zeros(len(steps), dtype=bool)
            free[ok] = self.plan_air[ix[ok, 0], ix[ok, 1], ix[ok, 2]]
            bad = np.flatnonzero(~free)
            return float(steps[bad[0]] - 0.5) if len(bad) else 12.0
        flat, inside = self.map.flat_of(pts)
        lo = self.map.lo[flat]
        free = ((lo <= FREE_T) if unknown_blocks else (lo < OCC_T)) & inside
        if r.trail:
            tr = np.asarray(r.trail[-40:])
            free |= (np.linalg.norm(pts[:, None, :] - tr[None, :, :], axis=2).min(axis=1) < 1.2) & inside
        bad = np.flatnonzero(~free)
        return float(steps[bad[0]] - 0.5) if len(bad) else 12.0

    def _speed_governor(self, r: DroneRecord, cmd: StickCommand, t: float) -> StickCommand:
        """Speed follows the evidence of clear space ahead. With no range sensor the only
        evidence is the frames, and they are about LATENCY_S old by the time a command acts."""
        if cmd.mode != "fly" or cmd.retreat:
            return cmd
        if t < r.brake_until:  # emergency brake
            cmd.vx = cmd.vy = cmd.vz = 0.0
            return cmd
        c, s_ = np.cos(r.yaw), np.sin(r.yaw)
        v = np.array([c * cmd.vx - s_ * cmd.vy, s_ * cmd.vx + c * cmd.vy, cmd.vz])
        sp = float(np.linalg.norm(v))
        if sp < 0.05:
            return cmd
        d = v / sp
        hor = float(np.hypot(d[0], d[1]))
        aligned = hor < 0.3 or float(d[0] * c + d[1] * s_) / max(hor, 1e-6) > 0.8
        age = t - r.fresh_t
        fresh = age < 0.8
        if aligned and fresh:
            # Looking where it is going with a current frame: the frame's own depth is the
            # evidence (drift-immune, and covers space nobody has mapped yet); the map only
            # vetoes walls it already knows about.
            clear = min(self._map_clear(r, d, unknown_blocks=False), r.fresh_clear if hor >= 0.3 else 12.0)
        else:
            clear = self._map_clear(r, d)  # blind or stale: only cleared space counts
        cap = self._governor(clear)
        # Never starve at the frontier: with a fresh frame showing room ahead, keep creeping so
        # the map can catch up (nothing is gained by hovering and waiting for it).
        if aligned and fresh and r.fresh_clear > 3.0:
            cap = max(cap, 0.6)
        if not aligned:
            # moving where the camera is not looking: blind, so slow, except through space the map has already cleared
            # for a long way (the exterior legs look at the wall and crab along it)
            cap = min(cap, 0.8 + 0.2 * max(0.0, min(clear, 12.0) - 4.0))
        if age > 2.0:
            cap = 0.0  # no recent frames at all: hold
        elif age > 0.8:
            cap = min(cap, 0.4)
        if cap < 0.8 * sp:
            r.slow_why = ("no frames" if age > 2.0 else "stale frames" if age > 0.8 else
                          "not facing travel" if not aligned else f"clear {clear:.0f} m")
        else:
            r.slow_why = ""
        if cap < sp:
            k = cap / sp
            cmd.vx, cmd.vy, cmd.vz = cmd.vx * k, cmd.vy * k, cmd.vz * k
        return cmd

    def _watch_stuck(self, r: DroneRecord, cmd: StickCommand, t: float) -> None:
        """A drone that is told to move but doesn't (pressed against something the map doesn't
        show) gets backed off and the spot is avoided for a while. Judged over a window: how
        far the sticks asked it to go against how far it actually went."""
        asked = float(np.hypot(cmd.vx, cmd.vy)) if cmd.mode == "fly" else 0.0
        if r.grounded or r.mode not in (SURVEY, ENTER, EXPLORE, INVESTIGATE, RTB):
            r.win = None  # holding, relaying, charging: not trying to get anywhere
            return
        if r.win is None:
            r.win = [t, r.pos.copy(), 0.0]
        r.win[2] += asked * 0.05  # control runs at 20 Hz
        if t - r.win[0] >= STUCK_S:
            commanded, moved = r.win[2], float(np.linalg.norm((r.pos - r.win[1])[:2]))
            r.win = [t, r.pos.copy(), 0.0]
            if commanded > 0.5 * STUCK_S * STUCK_CMD and moved < 0.25 * commanded:
                self._on_stuck(r, cmd, t)

    def _on_stuck(self, r: DroneRecord, cmd: StickCommand, t: float) -> None:
        c, s = np.cos(r.yaw), np.sin(r.yaw)
        ahead = r.pos + np.array([c * cmd.vx - s * cmd.vy, s * cmd.vx + c * cmd.vy, 0.0]) / max(np.hypot(cmd.vx, cmd.vy), 1e-6)
        cell = tuple(int(np.clip(v, 0, n - 1)) for v, n in zip(np.floor(ahead), self.shape))
        self.penalty[cell] = t + PENALTY_S
        self._event(t, f"Drone {r.id} stuck at ({r.pos[0]:.0f}, {r.pos[1]:.0f}, {r.pos[2]:.0f}) while {r.mode}: backing off", "warn")
        if r.mode == ENTER and r.entry is not None:
            self._fail_entry(r, t, "stuck")
        elif r.task is not None:
            self.unreachable[r.task] = t + 20.0
            r.task, r.task_vantage, r.arrived_t, r.path = None, None, None, []
        elif r.mode == SURVEY and r.scout_tile is not None:
            self.scout_fail[r.scout_tile] = t + 60.0  # something there the map does not show
            r.scout_tile, r.path = None, []
            self._set_mode(r, WAIT, t)

    def _fail_entry(self, r: DroneRecord, t: float, why: str) -> None:
        """An attempt at an opening failed: back off, avoid it for a while, retire it after
        repeated failures."""
        e = self.entries[r.entry]
        if e.rect is not None and e.fail_rect is not None and \
                (abs(e.rect[1] - e.fail_rect[1]) > 0.5 or abs(e.rect[2][0] - e.fail_rect[2][0]) > 0.5):
            e.fails = max(0, e.fails - 1)  # the opening was re-measured since the last failure: a fresh start
        e.fail_rect = e.rect
        e.fail_log.append((round(t, 1), why, r.id))
        e.fails += 1
        e.busy = None
        r.cool[e.id] = t + ENTRY_COOLDOWN_S
        if e.fails >= ENTRY_MAX_FAILS and not e.retired:
            e.retired = True
            self._event(t, f"Opening #{e.id} given up after {e.fails} failed attempts ({why})", "warn")
        else:
            self._event(t, f"Drone {r.id} failed at opening #{e.id} ({why}); backing off", "warn")
        back = r.trail[-3] if len(r.trail) >= 3 else r.pos - np.array([np.cos(r.yaw), np.sin(r.yaw), 0.0]) * 2.0
        r.path = [tuple(float(v) for v in back)]
        r.yaws, r.speed, r.cue = None, 0.8, None
        r.stage, r.stage_since = "backoff", t
        r.servo_start = None

    def _dil6(self, mask: np.ndarray) -> np.ndarray:
        """6-neighbour binary dilation (native when the Rust core is in use)."""
        return _dilate(mask, 1) if self.core is not None else ndimage.binary_dilation(mask, _SIX)

    def _build_nav(self, t: float = 0.0) -> None:
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        passable = free & ~occ
        if self.plan_air is not None:  # routes follow the plan: everything that is not solid, one voxel clear of every wall
            occ = self.plan_solid
            passable = ~self._dil6(occ)  # unseen space may hold a wall: drones plan only through space the map has cleared
        passable[:, :, 0] = False
        self.keep = self._keepout() if self.phase == "scout" else None
        if self.keep is not None:
            passable &= ~self.keep  # nobody goes in before the whole outside is scanned
        for e in self.entries:  # a measured opening is a doorway the planner can use, with a short corridor either side
            if not (e.confirmed and e.rect is not None) or e.retired or e.blocked or abs(e.normal[2]) > 0.5:
                continue
            ax, face, (h0, h1), (z0, z1) = e.rect
            inw = 1 if e.normal[ax] > 0 else -1
            lay = int(round(face)) if inw > 0 else int(round(face)) - 1
            la, lb = sorted((lay - 3 * inw, lay + 3 * inw))
            hl, hh = int(np.ceil(h0)), max(int(np.floor(h1)), int(np.ceil(h0)) + 1)
            zl, zh = int(np.ceil(z0)), max(int(np.floor(z1)), int(np.ceil(z0)) + 1)
            if ax == 0:
                passable[max(la, 0):lb + 1, max(hl, 0):hh, max(zl, 0):zh] = True
            else:
                passable[max(hl, 0):hh, max(la, 0):lb + 1, max(zl, 0):zh] = True
        self.penalty = {c: x for c, x in self.penalty.items() if x > t}
        for x, y, z in self.penalty:  # places where a drone got stuck
            passable[max(x - 1, 0):x + 2, max(y - 1, 0):y + 2, max(z - 1, 0):z + 2] = False
        if self.core is not None:  # native planner (Rust): A* and the dilations
            self.nav = RustNavGrid(passable, occ)
            self.near_occ = _dilate(occ, 2)
        else:
            self.nav = NavGrid(passable, occ)
            self.near_occ = ndimage.binary_dilation(occ, iterations=2)

    def _keepout(self) -> np.ndarray:
        """Space the exterior phases must stay out of: the building (the estimated footprint
        once known, otherwise whatever tall structure has been seen, with a margin), so no
        route cuts through a door or window that happens to be unseen or open."""
        keep = np.zeros(self.shape, dtype=bool)
        sz = self.shape[2]
        if self.env_known:
            keep[max(self.x0 - 1, 0):self.x1 + 1, max(self.y0 - 1, 0):self.y1 + 1, :min(self.top + 1, sz)] = True
        else:
            occ = self.map.grid(self.map.occupied)
            col = occ[:, :, 2:9].sum(axis=2) >= 4
            if col.any():
                keep[ndimage.binary_dilation(col, iterations=3), :14] = True
        return keep

    def _evict(self, r: DroneRecord, t: float) -> None:
        """A drone that finds itself inside the keep-out (it was there before the building was
        known) flies out by the shortest way."""
        foot = self.keep.any(axis=2)
        cell = (int(np.clip(r.pos[0], 0, self.shape[0] - 1)), int(np.clip(r.pos[1], 0, self.shape[1] - 1)))
        if not foot[cell] or r.pos[2] >= self.top + 1 and self.env_known:
            return
        _, idx = ndimage.distance_transform_edt(foot, return_indices=True)
        out = np.array([idx[0][cell] + 0.5, idx[1][cell] + 0.5, r.pos[2]])
        away = out[:2] - r.pos[:2]
        out[:2] += away / max(np.linalg.norm(away), 1e-6) * 3.0
        if self._fly_to(r, out, None):
            r.speed = 1.5

    def lost(self, r: DroneRecord, t: float) -> bool:
        return r.last_seen >= 0 and t - r.last_seen > LOST_AFTER and not r.grounded

    def _update_modes(self, t: float) -> None:
        cap_j = self.cfg.battery_wh * 3600.0
        self._track_legs(t)
        for r in self.drones:
            if r.mode == CRASHED or self.lost(r, t):
                continue
            if r.mode == IDLE:
                if self.phase != "complete" and t >= 1.0 + 1.2 * r.id and r.soc > 0.5:
                    self._takeoff(r, t)
            elif r.mode == TAKEOFF:
                if r.pos[2] > 3.0:
                    if self.phase == "operate" and self._perimeter_open():
                        self._start_survey_leg(r, t)
                    else:
                        self._set_mode(r, WAIT, t)
                        r.path = []
            elif r.mode in WORKING:
                time_home = self._time_home(r, t)
                need = time_home * CRUISE_POWER_W / cap_j + self.cfg.rtb_reserve
                if r.soc < need:
                    self._event(t, f"Drone {r.id} returning to base (battery {r.soc:.0%})", "warn")
                    self._go_home(r, t)
                    continue
                if r.mode == WAIT and self.phase in ("scout", "operate"):
                    if self.phase == "operate" and t >= r.scout_ready_t and self._perimeter_open():
                        self._start_survey_leg(r, t)  # perimeter team: up to PERIM_TEAM drones on the outside loops
                        continue
                    if self.keep is not None and not r.path:
                        self._evict(r, t)
                if r.mode == WAIT and self.phase in ("operate", "verify") and not r.path:
                    if t - r.mode_since > 25.0 and r.soc < 0.85:
                        self._go_home(r, t)  # nothing to do: charge rather than hover
                        continue
                if r.mode == SURVEY and r.path and np.linalg.norm(r.pos - np.array(r.path[-1])) < 1.5:
                    r.survey_done = True
                    partial_end = r.leg_partial and r.leg is not None
                    if r.leg is not None:
                        if partial_end:
                            r.leg["owner"], r.leg = None, None  # reached the edge of cleared space: the leg stays open
                            r.scout_ready_t = t + SCOUT_LOOK_S
                        else:
                            r.leg["done"], r.leg["owner"], r.leg = True, None, None
                    r.leg_partial = False
                    self._set_mode(r, WAIT, t)
                    r.path = []
                    if self.phase == "scout":  # at the frontier: look, let the map catch up, then move on
                        r.scout_tile, r.scout_ready_t = None, t + SCOUT_LOOK_S
                    if self.phase == "operate" and not partial_end and self._open_legs():
                        self._start_survey_leg(r, t)  # straight on to the next leg: no waiting
                elif (r.mode == SURVEY and r.leg_partial and r.leg is not None and r.path
                      and np.linalg.norm(r.pos - np.array(r.path[-1])) < 5.0 and t - r.leg_replan_t > 1.0):
                    # nearing the edge of cleared space: plan the next stretch now, without stopping
                    r.leg_replan_t = t
                    r.leg["owner"], r.leg = None, None
                    self._start_survey_leg(r, t)
                    r.leg_replan_t = t
                elif r.mode == ENTER:
                    self._step_entry(r, t)
                elif r.mode == INVESTIGATE and r.gap is not None:
                    self._step_gap(r, t)
                elif r.mode == INVESTIGATE:
                    c = self.candidates[r.candidate]
                    if c.confirmed and c.vitals is None and c.vitals_tries < 2:
                        c.vitals_t0 = c.vitals_t0 or t   # confirmed: hold in front of them for a vitals reading
                        if t - c.vitals_t0 > VITALS_TIMEOUT:
                            c.vitals_tries, c.vitals_t0 = c.vitals_tries + 1, None
                            self._release(r)
                            self._set_mode(r, EXPLORE, t)
                            r.path, r.task = [], None
                    elif c.confirmed or t - c.assigned_t > INVESTIGATE_TIMEOUT:
                        if not c.confirmed:
                            c.attempts += 1
                            if c.attempts >= 2:
                                c.dismissed = True
                                self._event(t, f"Candidate #{c.id} dismissed after 2 looks", "warn")
                        self._release(r)
                        self._set_mode(r, EXPLORE, t)
                        r.path, r.task = [], None
            elif r.mode == RTB:
                if r.speed is not None and not self._inside(r.pos, margin=4):
                    r.path = self._path_cells(r.pos, (r.pad[0], r.pad[1], 4.0 + r.id % 4))
                    r.speed = None
                if np.hypot(r.pos[0] - r.pad[0], r.pos[1] - r.pad[1]) < 1.5:
                    self._set_mode(r, LANDING, t)
                    r.path = []
            elif r.mode == LANDING:
                if r.grounded and t - r.mode_since > 1.0:
                    self._set_mode(r, CHARGING, t)
            elif r.mode == CHARGING:
                if r.soc >= 0.97 and self.phase != "complete":
                    self._takeoff(r, t)

        if self.phase == "scout":
            if self.env_known and t - self.phase_since > 4.0:
                self.phase, self.phase_since = "operate", t
                self._begin_legs(self._plan_survey())
                self.entry_change_t = t
                self._event(t, f"Building found: about {self.x1 - self.x0} x {self.y1 - self.y0} m, {self.top} m high. "
                               f"{PERIM_TEAM} drones fly its outside; the rest go in as soon as an opening is confirmed", "success")
            elif t - self.phase_since > self.cfg.scout_max_s:
                self.phase = "complete"
                self._event(t, "Site explored: no building found. Recalling swarm", "error")
                for r in self.drones:
                    if r.mode in WORKING:
                        self._go_home(r, t)
        elif self.phase == "operate":
            # Perimeter, entries and the interior all run at once. When the outside is done, any
            # missed blocks get another look; the mission moves on once nothing is left to explore.
            if self.tick % 4 == 0:
                self.ext_cov, self._gaps = self._exterior_coverage()
            all_done = all(g["done"] for g in self.legs)
            added = 0
            if all_done:
                for key, (p, yaw) in self._gaps:
                    if self.gap_tries.get(key, 0) >= 2:
                        continue
                    self.gap_tries[key] = self.gap_tries.get(key, 0) + 1
                    self.legs.append({"pts": [(p, yaw)], "owner": None, "done": False, "next_i": 0, "gap": key})
                    added += 1
                if added:
                    self._event(t, f"Exterior {self.ext_cov:.0%} seen: re-surveying {added} missed areas", "info")
            open_c = any(not (c.confirmed or c.dismissed) for c in self.candidates)
            idle = not any(g["tile"][0] != "verify" for g in self.targets) and not open_c
            if all_done and not added and self.first_inside_t is not None and idle:
                self.done_since = self.done_since or t
                if t - self.done_since > 8.0:
                    self.phase = "verify"
                    self.verify_since = t
                    n = sum(g["tile"][0] == "verify" for g in self.targets)
                    self._event(t, f"Building scanned (exterior {self.ext_cov:.0%}). Verification pass: {n} low-confidence areas", "info")
            else:
                self.done_since = None
            if t - self.phase_since > self.cfg.operate_max_s:
                self.phase, self.verify_since = "verify", t
                self._event(t, "Mapping time limit reached: verifying what exists", "warn")
        elif self.phase == "verify":
            open_c = any(not (c.confirmed or c.dismissed) for c in self.candidates)
            todo = any(g["tile"][0] == "verify" for g in self.targets)
            self.verify_empty_since = None if todo or open_c else (self.verify_empty_since or t)
            timeout = t - (self.verify_since or t) > self.cfg.verify_max_s
            if (self.verify_empty_since is not None and t - self.verify_empty_since > 8.0) or timeout:
                self.phase = "complete"
                self._event(t, "Map verified: recalling swarm" if not timeout else
                            "Verification time limit reached: recalling swarm", "success")
                for r in self.drones:
                    if r.mode in WORKING:
                        self._go_home(r, t)

    def _stage_point(self, e: Entry) -> np.ndarray:
        return e.center - e.normal * STAGE_DIST

    def _step_entry(self, r: DroneRecord, t: float) -> None:
        e = self.entries[r.entry] if r.entry is not None else None
        if e is None:
            self._set_mode(r, WAIT, t)
            return
        if r.stage == "legacy":  # vertical openings (roof hatches): fly through on the map
            if r.task_vantage is not None and self._inside(r.pos) and np.linalg.norm(r.pos - r.task_vantage) < 1.5:
                self._entered(r, e, t)
        elif r.stage == "approach":
            stage = self._stage_point(e)
            if np.linalg.norm(r.pos - stage) < 1.5 or not r.path:
                r.stage, r.stage_since = "align", t
                r.path = [tuple(float(v) for v in stage)]
                r.yaws, r.speed = [float(np.arctan2(e.normal[1], e.normal[0]))], 0.8
        elif r.stage == "align":
            fresh = r.cue is not None and t - r.cue["t"] < 1.0
            if t - r.stage_since > 2.5 and fresh:
                r.stage, r.stage_since = "servo", t
                r.path, r.yaws = [], None
                r.servo_start = r.pos.copy()
                n = np.array([e.normal[0], e.normal[1], 0.0])
                r.servo_dir = n / max(np.linalg.norm(n), 1e-6)
                r.servo_d0 = float(np.clip(r.cue["d"] if r.cue["d"] is not None else STAGE_DIST, 2.0, 10.0))
            elif t - r.stage_since > 15.0:
                self._fail_entry(r, t, "opening not visible")
        elif r.stage == "servo":
            travel = float(np.dot(r.pos - r.servo_start, r.servo_dir))
            if travel > r.servo_d0 + 2.0:
                self._entered(r, e, t)
            elif t - r.stage_since > SERVO_TIMEOUT_S:
                self._fail_entry(r, t, "no progress")
            elif r.cue is None or t - r.cue["t"] > 8.0:
                self._fail_entry(r, t, "lost sight of the opening")
        elif r.stage == "backoff":
            if t - r.stage_since > 6.0 or (r.path and np.linalg.norm(r.pos - np.asarray(r.path[-1])) < 1.0):
                r.path, r.task, r.task_vantage, r.stage = [], None, None, None
                self._set_mode(r, WAIT, t)

    def _entered(self, r: DroneRecord, e: Entry, t: float) -> None:
        e.busy, e.ok = None, e.ok + 1
        r.stage, r.cue, r.servo_start = None, None, None
        r.path, r.task, r.task_vantage = [], None, None
        if self.first_inside_t is None:
            self.first_inside_t = t
        self._event(t, f"Drone {r.id} is inside via opening #{e.id}", "success")
        self._set_mode(r, EXPLORE, t)

    # ----------------------------------------------------------------- survey
    def _plan_survey(self, standoff: float = SURVEY_STANDOFF) -> list[list]:
        """Perimeter loops at each floor's height plus a roof sweep, split into equal legs."""
        s = standoff
        x0, y0, x1, y1 = self.x0 - s, self.y0 - s, self.x1 + s, self.y1 + s
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        facing = [np.pi / 2, np.pi, -np.pi / 2, 0.0]  # yaw toward the wall from each side
        pts = []
        for k in range(self.cfg.floors):
            z = k * self.cfg.story + (4.5 if k == 0 else 2.5)  # ground loop clears yard clutter
            for side in range(4):
                (ax, ay), (bx, by) = corners[side], corners[side + 1]
                n = max(2, int(np.hypot(bx - ax, by - ay) / 6))
                for j in range(n):
                    f = j / n
                    pts.append(((ax + (bx - ax) * f, ay + (by - ay) * f, z), facing[side]))
        zr = self.top + 4.0  # low enough that the level camera sees the roof a few meters ahead
        for j, y in enumerate(np.arange(self.y0 + 4, self.y1 - 3, 7.0)):
            xs = (self.x0 - 2, self.x1 + 2) if j % 2 == 0 else (self.x1 + 2, self.x0 - 2)
            yaw = 0.0 if xs[1] > xs[0] else np.pi
            for x in np.linspace(xs[0], xs[1], 8):
                pts.append(((float(x), float(y), zr), yaw))
        return self._split_legs(pts)

    def _begin_legs(self, plan: list[list]) -> None:
        self.legs = [{"pts": list(leg), "owner": None, "done": False, "next_i": 0, "gap": None} for leg in plan if leg]
        for r in self.drones:
            r.leg = None

    def _perimeter_open(self) -> bool:
        """Is there outside left to fly and room in the perimeter team?"""
        # Until an opening is confirmed there is nothing to enter by, so the whole fleet flies the
        # outside (every drone has a leg from the start); afterwards a team of PERIM_TEAM stays on it.
        entering = any(e.confirmed and not e.blocked and not e.retired for e in self.entries)
        quota = PERIM_TEAM if entering else len(self.drones)
        return bool(self._open_legs()) and sum(1 for d in self.drones if d.leg is not None) < quota

    def _open_legs(self) -> list[dict]:
        return [g for g in self.legs if not g["done"] and g["owner"] is None]

    def _start_survey_leg(self, r: DroneRecord, t: float) -> None:
        """Take the nearest open leg (or the unflown rest of one another drone had to drop)."""
        while True:
            open_ = self._open_legs()
            if not open_:
                r.survey_done = True
                self._set_mode(r, WAIT, t)
                return
            ok_legs = []
            for g0 in open_:
                wp = np.asarray(g0["pts"][g0["next_i"]][0], dtype=float)
                if self._covered(wp):
                    ok_legs.append(g0)
                else:
                    self._need(("leg", id(g0)), wp, t)  # a relay first, then this leg
            if not ok_legs:
                self._set_mode(r, WAIT, t)
                return
            g = min(ok_legs, key=lambda g: (round(float(np.linalg.norm(np.asarray(g["pts"][g["next_i"]][0]) - r.pos)), 1),
                                            self.legs.index(g)))  # a fixed tie-break: legs are taken in a repeatable order
            pts, yaws, leg_map = [], [], []
            prev, partial = r.pos, False
            for k in range(g["next_i"], len(g["pts"])):
                p, yaw = g["pts"][k]
                if self.keep is not None:
                    c = tuple(int(np.clip(v, 0, n - 1)) for v, n in zip(np.floor(p), self.shape))
                    if self.keep[c]:
                        continue  # a waypoint inside the building (lanes cross it): skip it
                hop = self._path_cells(prev, p, strict=True, max_exp=90000, partial=True)
                if hop is None:
                    continue  # unreachable from here
                if not hop or float(np.linalg.norm(np.asarray(hop[-1]) - np.asarray(p))) > 2.0:
                    partial = True  # cleared space ends short of this waypoint: fly to its edge, look, go on
                if hop:
                    pts += hop
                    cy = self._crab_yaws(hop, yaw)
                    if partial:
                        # nearing the edge of cleared space: face along the way for the last stretch so the camera
                        # clears what is ahead
                        back = np.r_[np.cumsum(np.linalg.norm(np.diff(np.asarray(hop, dtype=float), axis=0), axis=1)[::-1])[::-1], 0.0]
                        cy = [y if d > 6.0 else None for y, d in zip(cy, back)]
                    yaws += cy
                    leg_map += [k] * len(hop)
                if partial:
                    break  # the rest waits until the map has caught up
                prev = np.asarray(p)
            moved = bool(pts) and float(np.linalg.norm(np.asarray(pts[-1]) - r.pos)) >= 2.0
            if pts and (moved or not partial):
                g["stall"] = 0
                break
            g["stall"] = g.get("stall", 0) + (1 if partial else 0)
            if not pts and not partial or g["stall"] >= 3:
                g["done"] = True  # nothing flyable left in this leg (or no progress after three tries)
                continue
            self._set_mode(r, WAIT, t)  # no progress yet: let the map catch up, then try again
            r.scout_ready_t = t + SCOUT_LOOK_S
            return
        g["owner"] = r.id
        r.leg = g
        r.path, r.leg_path, r.leg_map, r.leg_partial = pts, pts, leg_map, partial
        r.yaws = self._fill_yaws(r.pos, pts, yaws)
        r.speed = 2.4  # contact below 3 m/s bounces off the prop guards instead of crashing
        self._set_mode(r, SURVEY, t)

    def _track_legs(self, t: float) -> None:
        """Keep each leg's progress; hand a leg back when its drone stops flying it."""
        for r in self.drones:
            g = r.leg
            if g is None:
                continue
            if r.mode != SURVEY or r.crashed or (self.lost(r, t) and t - r.last_seen > 20.0):
                g["owner"], r.leg = None, None  # abandoned: someone else finishes it
                continue
            if r.path is r.leg_path and r.leg_map:
                g["next_i"] = max(g["next_i"], r.leg_map[min(self.pilot.target_index(r.id), len(r.leg_map) - 1)])

    def _exterior_coverage(self) -> tuple[float, list]:
        """How much of the building's outer surface has been seen, and waypoints for the gaps
        (stand-off points facing the unseen blocks of wall or roof)."""
        m = self.map
        known = m.grid(m.known)
        x0, y0, x1, y1, top = self.x0, self.y0, self.x1, self.y1, self.top
        s = SURVEY_STANDOFF - 1.0
        story = self.cfg.story
        total = seen = 0
        gaps = []
        walls = [("west", known[x0, y0:y1, 1:top], y0, lambda a, z: (x0 - s, a, z), 0.0),
                 ("east", known[x1 - 1, y0:y1, 1:top], y0, lambda a, z: (x1 + s, a, z), np.pi),
                 ("south", known[x0:x1, y0, 1:top], x0, lambda a, z: (a, y0 - s, z), np.pi / 2),
                 ("north", known[x0:x1, y1 - 1, 1:top], x0, lambda a, z: (a, y1 + s, z), -np.pi / 2)]
        for name, plane, origin, place, yaw in walls:
            length = plane.shape[0]
            for a0 in range(0, length, 8):
                for k in range(self.cfg.floors):
                    z0 = k * story
                    blk = plane[a0:a0 + 8, z0:z0 + story]
                    if blk.size == 0:
                        continue
                    total += blk.size
                    seen += int(blk.sum())
                    if blk.mean() < 0.6:
                        z = max(z0 + 1 + story / 2, 2.5)
                        gaps.append(((name, a0, k), (place(origin + a0 + min(4, length - a0) , z), yaw)))
        roof = known[x0:x1, y0:y1, min(top, known.shape[2] - 1)]
        for ax in range(0, roof.shape[0], 10):
            for ay in range(0, roof.shape[1], 10):
                blk = roof[ax:ax + 10, ay:ay + 10]
                total += blk.size
                seen += int(blk.sum())
                if blk.mean() < 0.6:
                    gaps.append((("roof", ax, ay), ((x0 + ax + 5, y0 + ay + 5, top + 4.0), 0.0)))
        return seen / max(total, 1), gaps

    def _path_cells(self, a, b, strict: bool = False, max_exp: int = 25000, partial: bool = False) -> list | None:
        cells = self.nav.astar(np.floor(a), np.floor(b), max_exp, partial) if self.nav else None
        if cells is None and strict:
            return None
        pts = to_waypoints(cells[1:]) if cells else []
        if partial and cells and float(np.linalg.norm(np.array(cells[-1]) + 0.5 - np.asarray(b, dtype=float))) > 2.0:
            return self._center_heights(pts)  # as far as cleared space goes; does not end at the goal
        return self._center_heights(pts) + [tuple(float(v) for v in b)]

    # ---------------------------------------------------------- entry finding
    def _seed_plan_entries(self, plan: list) -> None:
        """Plan-assisted: the operator supplied the building plan's openings. They are exact, so they start out measured,
        confirmed, and open in the map and the mesh; blocked ones stay marked blocked."""
        for p in plan:
            normal = np.asarray(p["normal"], dtype=float)
            center = np.asarray(p["center"], dtype=float)
            e = Entry(len(self.entries), center, normal, float(p["w"]), float(p["h"]), p["kind"], bool(p["blocked"]),
                      t_first=-10.0, t_seen=0.0, fitted=True, quality=1.0)
            if abs(normal[2]) < 0.5:
                ax = 0 if abs(normal[0]) >= abs(normal[1]) else 1
                out = -normal / max(float(np.linalg.norm(normal)), 1e-6)
                face = float(center[ax] + 0.5 * out[ax])
                horiz, zc = float(center[1 - ax]), float(center[2])
                e.rect = (ax, face, (horiz - e.w / 2, horiz + e.w / 2), (zc - e.h / 2, zc + e.h / 2))
                if self.core is not None and not e.blocked:
                    (h0, h1), (z0, z1) = e.rect[2], e.rect[3]
                    (u0, u1), (v0, v1) = ((h0, h1), (z0, z1)) if ax == 0 else ((z0, z1), (h0, h1))
                    layer = int(np.floor(center[ax]))
                    self.core.carve_patch(ax, layer, 1 if normal[ax] > 0 else -1, face, int(round(u0)), max(int(round(u1)), int(round(u0)) + 1),
                                          int(round(v0)), max(int(round(v1)), int(round(v0)) + 1), float(u0), float(u1), float(v0), float(v1), 0)
            self.entries.append(e)

    def _detect_entries(self, t: float) -> None:
        if self.tick % 2 or not self.env_known or self.phase == "scout":
            return
        if self.plan_assist:
            return  # the plan has them all: nothing to detect, nothing to second-guess
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        strong = m.grid(m.lo) <= -8  # free on strong evidence: several rays, not one drifted one
        pv = m.grid(m.pvox)
        found = []
        walls = [("west", "x", self.x0, 1), ("east", "x", self.x1 - 1, -1),
                 ("south", "y", self.y0, 1), ("north", "y", self.y1 - 1, -1)]
        for name, axis, c, step in walls:
            if axis == "x":
                plane = free[c, self.y0:self.y1, 1:self.top] & free[c + step, self.y0:self.y1, 1:self.top]
                plane &= strong[c, self.y0:self.y1, 1:self.top] & strong[c + step, self.y0:self.y1, 1:self.top]
                wallpt = pv[c - 1:c + 2, self.y0:self.y1, 1:self.top].sum(axis=0) > 0  # a surface was seen here
                behind = occ[c + 2 * step, self.y0:self.y1, 1:self.top] | occ[c + 3 * step, self.y0:self.y1, 1:self.top]
            else:
                plane = free[self.x0:self.x1, c, 1:self.top] & free[self.x0:self.x1, c + step, 1:self.top]
                plane &= strong[self.x0:self.x1, c, 1:self.top] & strong[self.x0:self.x1, c + step, 1:self.top]
                wallpt = pv[self.x0:self.x1, c - 1:c + 2, 1:self.top].sum(axis=1) > 0
                behind = occ[self.x0:self.x1, c + 2 * step, 1:self.top] | occ[self.x0:self.x1, c + 3 * step, 1:self.top]
            lab, _ = ndimage.label(plane)
            for k, sl in enumerate(ndimage.find_objects(lab)):
                w, h = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
                if w < 2 or h < 2:
                    continue
                if wallpt[sl][lab[sl] == k + 1].mean() > 0.25 or not self._framed(lab == k + 1, wallpt, w, h, 10, 7):
                    # most of it has points on the wall plane (a wall the drift carved through), or it is too big for a
                    # door or window, or not framed by wall that was seen: probably not a gap. A drone will go and look.
                    self._suspect(name, axis, c, step, sl, lab == k + 1, t)
                    continue
                cells = np.argwhere(lab == k + 1)
                ca, cz = cells.mean(axis=0)
                blocked = bool(behind[sl][lab[sl] == k + 1].mean() > 0.5)
                if axis == "x":
                    center = np.array([c + 0.5, self.y0 + ca + 0.5, 1 + cz + 0.5])
                    normal = np.array([float(step), 0.0, 0.0])
                else:
                    center = np.array([self.x0 + ca + 0.5, c + 0.5, 1 + cz + 0.5])
                    normal = np.array([0.0, float(step), 0.0])
                found.append((center, normal, float(w), float(h), name, blocked))
        # An opening in the roof: the slab voxel and the air under it are both free on strong evidence (several
        # rays), and no surface points were seen on the slab. Without the evidence test, depth estimates that run
        # long carve into the slab and turn the whole roof into one big "opening".
        fp = (slice(self.x0, self.x1), slice(self.y0, self.y1))
        roof = free[fp + (self.top,)] & free[fp + (self.top - 1,)] & strong[fp + (self.top,)] & strong[fp + (self.top - 1,)]
        seen_roof = pv[fp + (slice(self.top - 1, self.top + 2),)].sum(axis=2) > 0
        lab, _ = ndimage.label(roof)
        for k, sl in enumerate(ndimage.find_objects(lab)):
            w, h = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if w < 2 or h < 2:
                continue
            if seen_roof[sl][lab[sl] == k + 1].mean() > 0.25:
                continue  # most of it has a roof surface in the map: carved through, not open
            if not self._framed(lab == k + 1, seen_roof, w, h, 10, 10):
                continue  # not a hatch: too big, or the roof around it was never seen
            cx, cy = np.argwhere(lab == k + 1).mean(axis=0)
            found.append((np.array([self.x0 + cx + 0.5, self.y0 + cy + 0.5, self.top + 0.5]),
                          np.array([0.0, 0.0, -1.0]), float(w), float(h), "roof", False))
        for center, normal, w, h, side, blocked in found:
            match = next((e for e in self.entries if np.linalg.norm(e.center - center) < 4.0), None)
            if match:
                if not match.fitted:
                    match.center, match.w, match.h = center, max(match.w, w), max(match.h, h)
                match.blocked = blocked
                match.t_seen = t
                continue
            e = Entry(len(self.entries), center, normal, w, h, side, blocked, t_first=t, t_seen=t, fitted=side == "roof")
            self.entries.append(e)
            if side != "roof":
                self._entry_check(e)  # a drone will look at it and measure it before anyone flies at it
            self.entry_change_t = t
            where = "roof" if side == "roof" else f"{side} wall, floor {int(center[2] // self.cfg.story) + 1}"
            self._event(t, f"Entry point found: {w:.0f}x{h:.0f} m opening ({where})"
                           f"{' - blocked by debris' if blocked else ''}", "info")

    def _suspect(self, name: str, axis: str, c: int, step: int, sl, comp: np.ndarray, t: float) -> None:
        """Remember a hole in a wall that the evidence does not back, as tiles of at most 6 x 4 m, for a drone to check."""
        ax = 0 if axis == "x" else 1
        if axis == "x":
            lo1, lo2 = self.y0 + sl[0].start, 1 + sl[1].start      # u = y, v = z
            hi1, hi2 = self.y0 + sl[0].stop, 1 + sl[1].stop
        else:
            lo1, lo2 = 1 + sl[1].start, self.x0 + sl[0].start       # u = z, v = x
            hi1, hi2 = 1 + sl[1].stop, self.x0 + sl[0].stop
        face = float(c if step > 0 else c + 1)
        out = np.zeros(3)
        out[ax] = -float(step)
        added = 0
        for u0 in range(lo1, hi1, 6):
            for v0 in range(lo2, hi2, 4 if axis == "x" else 6):
                du, dv = (6, 4) if axis == "x" else (4, 6)
                u1, v1 = min(u0 + du, hi1), min(v0 + dv, hi2)
                # the part of the component inside this tile
                if axis == "x":
                    part = comp[u0 - self.y0:u1 - self.y0, v0 - 1:v1 - 1]
                else:
                    part = comp[v0 - self.x0:v1 - self.x0, u0 - 1:u1 - 1]
                if part.size == 0 or part.mean() < 0.5:
                    continue
                horiz, vert = ((u0 + u1) / 2, (v0 + v1) / 2) if axis == "x" else ((v0 + v1) / 2, (u0 + u1) / 2)
                ctr = np.zeros(3)
                ctr[ax] = face
                ctr[1 - ax] = horiz
                ctr[2] = vert
                if any(f[0] == ax and f[1] == c and f[2] <= (u0 + u1) / 2 < f[3] and f[4] <= (v0 + v1) / 2 < f[5] for f in self.filled):
                    continue
                if any(np.linalg.norm(q["center"] - ctr) < 3.0 for q in self.suspects):
                    continue
                if len(self.suspects) >= 80:
                    return
                self.suspects.append({"id": len(self.suspects), "axis": ax, "layer": c, "face": face, "sign": -float(step),
                                      "a": (u0, u1), "b": (v0, v1), "center": ctr, "out": out, "state": "new", "drone": None,
                                      "tries": 0, "side": name, "t": t, "looks": 0, "prio": 1, "entry": None})
                added += 1
        if added:
            self._event(t, f"{added} suspicious gap(s) in the {name} wall: sending a drone to look", "info")

    def _entry_check(self, e: Entry) -> None:
        """A candidate opening from the map: have a drone look at it from outside and measure its rectangle."""
        ax = 0 if abs(e.normal[0]) >= abs(e.normal[1]) else 1
        out = -np.array([e.normal[0], e.normal[1], 0.0])
        out /= max(float(np.linalg.norm(out)), 1e-6)
        horiz, zc = float(e.center[1 - ax]), float(e.center[2])
        hlo, hhi = int(np.floor(horiz - e.w / 2)), int(np.ceil(horiz + e.w / 2))
        zlo, zhi = int(np.floor(zc - e.h / 2)), int(np.ceil(zc + e.h / 2))
        a_, b_ = ((hlo, hhi), (zlo, zhi)) if ax == 0 else ((zlo, zhi), (hlo, hhi))
        self.suspects.append({"id": len(self.suspects), "axis": ax, "layer": int(np.floor(e.center[ax])),
                              "face": float(e.center[ax] + 0.5 * out[ax]), "sign": float(out[ax]), "a": a_, "b": b_,
                              "center": np.asarray(e.center, dtype=float).copy(), "out": out, "state": "new", "drone": None,
                              "tries": 0, "side": e.side, "t": self.t_now, "looks": 0, "prio": 0, "entry": e.id})

    def _gap_checks(self, t: float) -> None:
        """Dispatch the nearest free drone to each suspicious gap, up to two at a time."""
        busy = sum(1 for q in self.suspects if q["state"] == "assigned")
        # candidate openings first (ground floor before upper windows), then suspicious gaps
        order = sorted((q for q in self.suspects if q["state"] == "new"), key=lambda q: (q["prio"], q["center"][2] > 6.0))
        for q in order:
            if busy >= 2:
                return
            if t < q.get("retry_t", 0.0):
                continue
            avail = [r for r in self.drones if r.mode == WAIT and not self.lost(r, t) and not r.grounded and r.soc > 0.4
                     and r.pos[2] > 2.0]
            if not avail and q["prio"] == 0:  # a candidate opening is worth taking a drone off its outside loop
                avail = [r for r in self.drones if r.mode == SURVEY and not self.lost(r, t) and not r.grounded
                         and r.soc > 0.5 and r.pos[2] > 2.0]
            if not avail:
                return
            vantage = q["center"] + q["out"] * 6.0
            vantage[2] = float(np.clip(q["center"][2], 2.5, self.top + 1.0))
            if not self._covered(vantage):
                self._need(("gap", q["id"]), vantage, t)
                continue
            r = min(avail, key=lambda r: float(np.hypot(*(r.pos[:2] - vantage[:2]))))
            path = self._path_cells(r.pos, tuple(vantage), strict=True, max_exp=60000)
            if path is None:
                q["tries"] += 1
                q["retry_t"] = t + 20.0
                if q["tries"] >= 3:
                    q["state"] = "unreachable"
                continue
            yaw = float(np.arctan2(-q["out"][1], -q["out"][0]))
            if r.leg is not None:
                r.leg["owner"], r.leg = None, None  # the loop stays open for another drone
            r.path = path
            r.yaws = self._fill_yaws(r.pos, path, [None] * (len(path) - 1) + [yaw])
            r.speed, r.gap = 2.4, q
            q["state"], q["drone"], q["t_assign"], q["arrived"] = "assigned", r.id, t, None
            self._set_mode(r, INVESTIGATE, t)
            busy += 1

    def _step_gap(self, r: DroneRecord, t: float) -> None:
        q = r.gap
        vantage = q["center"] + q["out"] * 6.0
        if t - q["t_assign"] > 90.0:
            q["state"], q["tries"], q["retry_t"] = "new", q["tries"] + 1, t + 20.0
            if q["tries"] >= 3:
                q["state"] = "unreachable"
            self._finish_gap(r, t)
            return
        if np.hypot(*(r.pos[:2] - vantage[:2])) > 2.0:
            return
        q["arrived"] = q["arrived"] or t
        if t - q["arrived"] < 3.0:
            return
        verdict, fit = self._gap_verdict(r, q)
        q["looks"] += 1
        ent = self.entries[q["entry"]] if q.get("entry") is not None else None
        if verdict is False:
            # Over time: a wall verdict has to hold on two looks at least 3 s apart (a single frame can be wrong).
            q["wall_votes"] = q.get("wall_votes", 0) + 1
            if q["wall_votes"] < 2 and q["looks"] < 4:
                q["arrived"] = t
                return
            # In space: it only makes sense to fill a hole that sits in a continuous wall, with solid wall around it.
            if not self._wall_around(q):
                self._event(t, f"Gap check by drone {r.id}: looks like wall, but the wall around it is not solid: left as is", "warn")
                q["state"] = "unclear"
                if ent is not None:
                    ent.retired = True
                self._finish_gap(r, t)
                return
        elif verdict is None and q["looks"] < 3:
            q["arrived"] = t  # inconclusive: look again
            return
        if verdict is True:
            if fit is None or not fit["ok"]:
                if q["looks"] < 3:
                    q["arrived"] = t
                    return
                why = "no clean rectangle" if fit is None else f"{fit['w']:.1f}x{fit['h']:.1f} m, fill {fit['fill']:.2f}"
                self._event(t, f"Gap check by drone {r.id}: an opening, but not one a drone can fly through ({why})", "warn")
                if ent is not None:
                    ent.retired = True
                q["state"] = "unclear"
            else:
                self._accept_opening(r, q, fit, t)
                q["state"] = "gap"
        elif verdict is False:
            ax, (u0, u1), (v0, v1) = q["axis"], q["a"], q["b"]
            self.core.fill_patch(int(ax), int(q["layer"]), float(q["face"]), int(u0), int(u1), int(v0), int(v1),
                                 float(u0), float(u1), float(v0), float(v1), float(q["sign"]), int(self.tick))
            self.filled.append((ax, q["layer"], u0, u1, v0, v1))
            q["state"] = "filled"
            if ent is not None:
                ent.retired = True
            self._event(t, f"Gap check by drone {r.id}: it is wall, filled ({q['side']} wall)", "info")
        else:
            q["state"] = "unclear"
        self._finish_gap(r, t)

    def _accept_opening(self, r: DroneRecord, q: dict, fit: dict, t: float) -> None:
        """A drone has measured an opening: make it an entry with that rectangle, open it in the map and the mesh."""
        ax = q["axis"]
        u0, u1, v0, v1 = fit["u0"], fit["u1"], fit["v0"], fit["v1"]
        (h0, h1), (z0, z1) = ((u0, u1), (v0, v1)) if ax == 0 else ((v0, v1), (u0, u1))
        face, normal = float(q["face"]), -q["out"]
        center = fit["center"]
        ent = self.entries[q["entry"]] if q.get("entry") is not None else None
        if ent is None:
            def overlaps(e: Entry) -> bool:
                if not e.fitted or e.rect is None or e.rect[0] != ax or abs(e.rect[1] - face) > 1.5:
                    return False
                (eh0, eh1), (ez0, ez1) = e.rect[2], e.rect[3]
                oh = min(h1, eh1) - max(h0, eh0)
                oz = min(z1, ez1) - max(z0, ez0)
                return oh > 0.4 * min(h1 - h0, eh1 - eh0) and oz > 0.4 * min(z1 - z0, ez1 - ez0)
            same = next((e for e in self.entries if overlaps(e)), None)
            if same is not None:
                ent = same  # the same opening seen again: refine it rather than add another
        if ent is None:
            ent = Entry(len(self.entries), center, normal, h1 - h0, z1 - z0, q["side"], False, t_first=t - 3.0, t_seen=t)
            self.entries.append(ent)
        ent.center, ent.normal, ent.w, ent.h = center, normal, float(h1 - h0), float(z1 - z0)
        ent.rect, ent.fitted, ent.quality, ent.t_seen = (ax, face, (h0, h1), (z0, z1)), True, fit["fill"], t
        ent.t_first = min(ent.t_first, t - 3.0)
        ent.retired, ent.fails = False, 0
        self.entry_change_t = t
        a0, a1 = int(round(u0)), max(int(round(u1)), int(round(u0)) + 1)
        b0, b1 = int(round(v0)), max(int(round(v1)), int(round(v0)) + 1)
        step = 1 if normal[ax] > 0 else -1
        self.core.carve_patch(int(ax), int(q["layer"]), step, face, a0, a1, b0, b1, float(u0), float(u1), float(v0), float(v1), int(self.tick))
        self._event(t, f"Opening #{ent.id} measured by drone {r.id}: {ent.w:.1f}x{ent.h:.1f} m ({q['side']} wall), "
                       f"fill {fit['fill']:.2f}", "success")

    def _wall_around(self, q: dict) -> bool:
        """Is the wall layer solid in a one-voxel ring around the gap's rectangle (at least 60% of it, with no side of the
        ring empty)? A patch is only filled if the wall is continuous across it."""
        occ = self.map.grid(self.map.occupied)
        ax, (u0, u1), (v0, v1) = q["axis"], q["a"], q["b"]
        sides = {"lo_u": [(u0 - 1, v) for v in range(v0, v1)], "hi_u": [(u1, v) for v in range(v0, v1)],
                 "lo_v": [(u, v0 - 1) for u in range(u0, u1)], "hi_v": [(u, v1) for u in range(u0, u1)]}
        fr = []
        for cells in sides.values():
            ok = n = 0
            for u, v in cells:
                c = [0, 0, 0]
                c[ax], c[(ax + 1) % 3], c[(ax + 2) % 3] = q["layer"], u, v
                if min(c) < 0 or any(c[i] >= self.shape[i] for i in range(3)):
                    continue
                n += 1
                ok += bool(occ[tuple(c)])
            if n:
                fr.append(ok / n)
        # the floor and the roof line can be missing from the ring (ground level): allow one side to be empty
        return bool(fr) and float(np.mean(fr)) >= 0.6 and sorted(fr)[1 if len(fr) > 1 else 0] >= 0.3

    def _finish_gap(self, r: DroneRecord, t: float) -> None:
        q = r.gap
        r.gap = None
        if q is not None and q.get("drone") == r.id:
            q["drone"] = None
        self._set_mode(r, WAIT, t)
        r.path, r.yaws, r.speed = [], None, None

    def _gap_verdict(self, r: DroneRecord, q: dict):
        """Look through the gap with the drone's own latest depth frame. Returns (verdict, fit): True if the rays reach
        well past the wall plane (it is open), False if they stop at it (wall), None if too little can be seen; `fit` is
        the measured rectangle of the opening (or None)."""
        depth = self.last_depth[r.id]
        if depth is None:
            return None, None
        H, W = depth.shape
        ax, (u0, u1), (v0, v1) = q["axis"], q["a"], q["b"]
        gu, gv = np.meshgrid(np.linspace(u0 + 0.5, u1 - 0.5, 5), np.linspace(v0 + 0.5, v1 - 0.5, 4), indexing="ij")
        pts = np.zeros((gu.size, 3))
        pts[:, ax] = q["face"]
        pts[:, (ax + 1) % 3] = gu.ravel()
        pts[:, (ax + 2) % 3] = gv.ravel()
        d = pts - r.pos
        dist = np.linalg.norm(d, axis=1)
        c, s_ = np.cos(r.yaw), np.sin(r.yaw)
        body = np.stack([c * d[:, 0] + s_ * d[:, 1], -s_ * d[:, 0] + c * d[:, 1], d[:, 2]], axis=1) / dist[:, None]
        rays = self.map.k.body_rays
        k = plane_scale(depth, rays, r.pos, r.yaw, ax, float(q["face"])) if ax in (0, 1) else 1.0  # the pose drifts
        through = valid = 0
        for b, dd in zip(body, dist):
            if b[0] < 0.2:
                continue
            j = int(np.argmax(rays @ b))
            if float(rays[j] @ b) < 0.995:
                continue  # outside the camera's view
            est = float(depth[j // W, j % W])
            valid += 1
            if est <= 0.0 or est > dd * k + 1.2:
                through += 1
        q["why"] = f"valid={valid} through={through} k={k:.2f} d={float(np.linalg.norm(r.pos - q['center'])):.1f}"
        if valid < 5:
            return None, None
        frac = through / valid
        verdict = True if frac >= 0.6 else False if frac <= 0.25 else None
        fit = fit_opening(depth, rays, r.pos, r.yaw, ax, float(q["face"]), q["center"]) if verdict is True and ax in (0, 1) else None
        if fit is not None:
            q["why"] += f" fit={fit['w']:.1f}x{fit['h']:.1f} fill={fit['fill']:.2f}"
        return verdict, fit

    @staticmethod
    def _framed(region: np.ndarray, seen: np.ndarray, w: int, h: int, max_w: int, max_h: int) -> bool:
        """A real opening is small and has seen wall (or roof) all around it. Space that is merely unobserved, or
        that depth errors carved through, is large and has unseen surface at its border."""
        if w > max_w or h > max_h:
            return False
        ring = ndimage.binary_dilation(region, iterations=2) & ~region
        return not ring.any() or float(seen[ring].mean()) >= 0.6

    def _release_for_entry(self, t: float) -> None:
        """As soon as an opening is confirmed, drones beyond the perimeter team come off their outside legs (the leg
        stays open for whoever continues it) and go in, nearest to the opening first, instead of finishing the loop."""
        usable = [e for e in self.entries if e.confirmed and not e.blocked and not e.retired and e.busy is None]
        if not usable or self.phase != "operate":
            return
        on_leg = [r for r in self.drones if r.leg is not None and r.mode == SURVEY and not self.lost(r, t) and not r.grounded]
        excess = len(on_leg) - PERIM_TEAM
        if excess <= 0:
            return
        waiting = sum(1 for r in self.drones if r.mode == WAIT and not r.grounded)
        n = excess if self.plan_assist else min(excess, max(2 * len(usable) - waiting, 0))
        if n <= 0:
            return
        stages = [self._stage_point(e) for e in usable]
        on_leg.sort(key=lambda r: min(float(np.linalg.norm(r.pos - sp)) for sp in stages))
        for r in on_leg[:n]:
            r.leg["owner"], r.leg = None, None
            r.leg_partial = False
            r.path, r.yaws = [], None
            self._set_mode(r, WAIT, t)
            self._event(t, f"Drone {r.id} leaves the outside loop: an opening is confirmed", "info")

    def _assign_entries(self, t: float) -> None:
        for e in self.entries:  # free openings whose drone is gone
            if e.busy is not None:
                d = self.drones[e.busy]
                if d.mode != ENTER or d.entry != e.id:
                    e.busy = None
        waiting = [r for r in self.drones if r.mode == WAIT and not self.lost(r, t) and not r.grounded]
        usable = [e for e in self.entries if not e.blocked and not e.retired and e.busy is None and e.confirmed]
        if not waiting or not usable:
            return
        BIG = 1e6
        cost = np.array([[BIG if r.cool.get(e.id, -1) > t else float(np.linalg.norm(r.pos - self._stage_point(e))) + (30.0 if e.center[2] > 6.0 else 0.0)  # ground doors and docks first
                          for e in usable] for r in waiting])
        rows, js = linear_sum_assignment(cost)
        for k, j in zip(rows, js):
            r, e = waiting[k], usable[j]
            if cost[k, j] >= BIG:
                continue
            vertical = abs(e.normal[2]) > 0.5 or self.plan_assist   # plan-assisted: the opening is carved in the map, fly it on the map
            stage = self._stage_point(e)
            if not self._covered(stage):
                self._need(("entry", e.id), stage, t)
                continue
            approach = self._path_cells(r.pos, stage, strict=True)
            if approach is None:
                r.cool[e.id] = t + ENTRY_COOLDOWN_S  # no route to it from here: try another
                continue
            if vertical:  # roof hatch: through it on the map
                inside = e.center + e.normal * 1.5
                for depth in (4.0, 3.0, 2.0):
                    cand = e.center + e.normal * depth
                    if self.nav.ok(np.floor(cand)):
                        inside = cand
                        break
                pts = approach + [tuple(e.center), tuple(inside)]
                r.task_vantage, r.stage = np.asarray(inside), "legacy"
                r.speed = self.cfg.indoor_speed
            else:
                pts = approach
                r.task_vantage, r.stage = None, "approach"
                r.speed = 3.0
            r.path = pts
            r.yaws = self._fill_yaws(r.pos, pts, [None] * len(pts))
            r.entry, r.stage_since, r.cue = e.id, t, None
            e.busy = r.id
            self._set_mode(r, ENTER, t)
            self._event(t, f"Drone {r.id} heading for {e.side} opening #{e.id}", "info")

    def _inside(self, p, margin: float = 0.0) -> bool:
        if not self.env_known:
            return False
        return (self.x0 - margin < p[0] < self.x1 + margin and self.y0 - margin < p[1] < self.y1 + margin
                and p[2] < self.top + margin)

    # --------------------------------------------------------------- explore
    def _find_targets(self, t: float) -> None:
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        unknown = ~free & ~occ
        frontier = free & self.interior & self._dil6(unknown) & ~self.ignore
        low_q = m.grid(m.quality < m.q.threshold)
        free_d = self._dil6(free)
        surface = occ & self.interior & low_q & free_d & ~self.ignore
        exposed = occ & self.interior & ~low_q & free_d & ~self.ignore & ~self.verified
        weak = (m.grid(m.npass) < VERIFY_NPASS) | (m.grid(m.vres) > VERIFY_RESID)
        verify = exposed & weak
        targets = []
        story = self.cfg.story
        for kind, mask in (("frontier", frontier), ("surface", surface), ("verify", verify)):
            pts = np.argwhere(mask)
            if len(pts) == 0:
                continue
            keys = (pts[:, 0] // TILE) * 100000 + (pts[:, 1] // TILE) * 100 + pts[:, 2] // story
            order = np.argsort(keys, kind="stable")
            keys, pts = keys[order], pts[order]
            bounds = np.flatnonzero(np.diff(keys)) + 1
            for group, key in zip(np.split(pts, bounds), keys[np.r_[0, bounds]]):
                if len(group) < 3:
                    continue
                tile = (kind, int(key))
                if self.unreachable.get(tile, -1) > t:
                    continue
                c = group.mean(axis=0)
                rep = group[np.argmin(((group - c) ** 2).sum(axis=1))]
                targets.append({"tile": tile, "voxel": rep, "gain": len(group), "cells": group})
        self.targets = targets

    def _vantage(self, tgt: dict):
        """(vantage point, yaw) from which the nose camera sees a target, or None."""
        kind, _ = tgt["tile"]
        v = tgt["voxel"]
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        shape = np.array(self.shape)
        acc = np.zeros(3)
        for d in _DIRS:
            q = v + d
            if (q < 0).any() or (q >= shape).any():
                continue
            if kind == "frontier" and not free[tuple(q)] and not occ[tuple(q)]:
                acc += d  # toward the unknown
            elif kind in ("surface", "verify") and free[tuple(q)]:
                acc += d  # exposed face normal
        if not acc.any():
            return None
        n = acc / np.linalg.norm(acc)
        if kind == "frontier":
            # Look into the unknown just past the frontier; sight line must reach the frontier voxel.
            return self._view_point(v + 0.5 + n * 1.0, n, v, dists=(1.5, 2.5, 3.5))
        if kind == "verify":  # a close second look
            return self._view_point(v + 0.5, n, v + np.round(n).astype(int), dists=(2.5, 2.0, 3.0, 3.5))
        return self._view_point(v + 0.5, n, v + np.round(n).astype(int), dists=(3.0, 2.5, 3.5, 2.0, 1.5))

    def _view_point(self, target: np.ndarray, normal: np.ndarray, sight_cell, dists, lifts=(0.0,)):
        """A free point from which `target` (facing `normal`) is inside the camera's field of
        view, with a clear sight line to `sight_cell`. Walls are viewed head-on; floors and
        ceilings from the side, offset so their elevation stays within the vertical FOV."""
        nh = np.array([normal[0], normal[1], 0.0])
        cands = []
        if np.linalg.norm(nh) >= 0.5:
            nh /= np.linalg.norm(nh)
            for d in dists:
                cands.append(target + nh * d)
        tan_v = np.tan(self.half_vfov)
        sz = np.sign(normal[2]) if abs(normal[2]) > 0.3 else 0.0
        for lift in lifts:   # (a spot may need to be a little higher: routes keep clear of the floor)
            for d in dists:
                dz = sz * min(1.5, d * tan_v * 0.9)
                for ang in np.linspace(0, 2 * np.pi, 8, endpoint=False):
                    cands.append(target + np.array([np.cos(ang) * d, np.sin(ang) * d, dz + lift]))
        sight = np.asarray(sight_cell, dtype=float)
        for c in cands:
            cell = np.floor(c)
            if not self.nav.ok(cell) or not self.nav.line_clear(cell, sight, body=0.2):
                continue
            look = target - c
            dh = np.hypot(look[0], look[1])
            if dh < 0.5 or abs(np.arctan2(look[2], dh)) > self.half_vfov:
                continue
            return c, float(np.arctan2(look[1], look[0]))
        return None

    def _allocate(self, t: float) -> None:
        # Finish looks: after LOOK_TIME at the vantage, write off whatever is still unscanned.
        for r in self.drones:
            if r.mode != EXPLORE or r.task is None or r.task_vantage is None:
                continue
            tgt = next((g for g in self.targets if g["tile"] == r.task), None)
            if tgt is None:
                r.task, r.task_vantage, r.arrived_t, r.path = None, None, None, []  # tile done
            elif np.linalg.norm(r.pos - r.task_vantage) < 1.3:
                r.arrived_t = r.arrived_t or t
                if t - r.arrived_t > LOOK_TIME:
                    c = tgt["cells"]
                    done = self.verified if tgt["tile"][0] == "verify" else self.ignore
                    done[c[:, 0], c[:, 1], c[:, 2]] = True
                    r.task, r.task_vantage, r.arrived_t, r.path = None, None, None, []

        idle = [r for r in self.drones if r.mode == EXPLORE and r.task is None and not self.lost(r, t)]
        taken = {r.task for r in self.drones if r.task is not None}
        avail = [g for g in self.targets if g["tile"] not in taken]
        if not idle or not avail:
            return
        story = self.cfg.story
        vox = np.array([g["voxel"] for g in avail], dtype=float) + 0.5
        gain = np.array([g["gain"] for g in avail], dtype=float)
        cost = np.zeros((len(idle), len(avail)))
        # Re-scans fill in for idle drones; new ground and survivors come first until the sweep.
        vpen = np.array([VERIFY_PENALTY if g["tile"][0] == "verify" and self.phase == "operate" else 0.0
                         for g in avail])
        for k, r in enumerate(idle):
            fl = np.abs(vox[:, 2] // story - r.pos[2] // story)
            cost[k] = np.linalg.norm(vox - r.pos, axis=1) + 15.0 * fl - 3.0 * np.sqrt(gain) + vpen
        rows, cols = linear_sum_assignment(cost)
        plans = 0
        why = {"novantage": 0, "uncovered": 0, "noroute": 0, "assigned": 0}
        for k, j in sorted(zip(rows, cols), key=lambda kj: cost[kj]):
            if plans >= MAX_PLANS_PER_TICK:
                break  # bound A* work per tick; the rest get targets next tick
            r, g = idle[k], avail[j]
            vt = self._vantage(g)
            if vt is None:
                self.unreachable[g["tile"]] = t + 20.0
                why["novantage"] += 1
                continue
            vantage, yaw = vt
            if not self._covered(vantage):
                self._need(("vant", g["tile"]), vantage, t)  # a relay first, then the look
                why["uncovered"] += 1
                continue
            plans += 1
            if not self._fly_to(r, vantage, yaw):
                self.unreachable[g["tile"]] = t + 20.0
                why["noroute"] += 1
                continue
            why["assigned"] += 1
            r.task, r.task_vantage, r.arrived_t = g["tile"], np.asarray(vantage), None
        if os.environ.get("DISASTER_ALLOC_DEBUG") and self.tick % 10 == 0:
            print(f"[alloc] t={t:.0f} idle={len(idle)} avail={len(avail)} targets={len(self.targets)} {why}", flush=True)

    def _fly_to(self, r: DroneRecord, goal, yaw) -> bool:
        cells = self.nav.astar(np.floor(r.pos), np.floor(goal))
        if cells is None:
            return False
        pts = to_waypoints(cells[1:]) or [tuple(goal)]
        pts[-1] = tuple(float(v) for v in goal)
        pts = self._center_heights(pts)
        r.path = pts
        r.yaws = self._fill_yaws(r.pos, pts, [None] * (len(pts) - 1) + [yaw])
        r.speed = self.cfg.indoor_speed
        return True

    def _center_heights(self, pts: list) -> list:
        """Center indoor waypoints in the free space around them so drones keep clear of
        floors, lintels and door/window jambs: z goes to the middle of the free vertical gap
        (when that gap lies within one story; shafts keep their climb heights), and x/y go to
        the middle of narrow openings and corridors. The final waypoint (a vantage) is kept."""
        free = self.map.grid(self.map.free)
        out = []
        sx, sy, sz = self.shape
        story = self.cfg.story
        for k, p in enumerate(pts):
            x, y, z = (int(np.floor(c)) for c in p)
            if (k == len(pts) - 1 or not self._inside(p, margin=2) or not (0 <= z < sz)
                    or not free[x, y, z]):
                out.append(tuple(p))
                continue
            q = [float(p[0]), float(p[1]), float(p[2])]
            lo, hi = self._gap(free[x, y, :], z, sz)
            if hi + 1 - lo <= story:
                mid = (lo + hi + 1) / 2.0
                q[2] = float(np.clip(mid, lo + 0.9, hi + 1 - 0.6)) if hi + 1 - lo >= 1.5 else mid
            for axis, line in ((0, free[max(x - 3, 0):x + 4, y, z]), (1, free[x, max(y - 3, 0):y + 4, z])):
                c = (x, y)[axis]
                i0 = c - max(c - 3, 0)
                lo, hi = self._gap(line, i0, len(line))
                if lo > 0 and hi < len(line) - 1:  # bounded on both sides within 3 m: narrow
                    q[axis] = (c - i0) + (lo + hi + 1) / 2.0
            out.append(tuple(q))
        return out

    @staticmethod
    def _gap(line: np.ndarray, i: int, n: int) -> tuple[int, int]:
        lo = hi = i
        while lo - 1 >= 0 and line[lo - 1]:
            lo -= 1
        while hi + 1 < n and line[hi + 1]:
            hi += 1
        return lo, hi

    @staticmethod
    def _crab_yaws(hop, facing: float) -> list:
        """Heading along a stretch that should look at a wall: turned toward it, but never more than CRAB_MAX away from
        the direction of travel, so the camera still sees what the drone is flying into (a drone that looks square at
        the wall cannot see its own path, and the master then slows it to a crawl)."""
        pts = np.asarray(hop, dtype=float)
        if len(pts) < 2:
            return [facing] * len(pts)
        d = np.diff(pts[:, :2], axis=0)
        ty = np.arctan2(d[:, 1], d[:, 0])
        short = np.hypot(d[:, 0], d[:, 1]) < 0.3
        for i in range(len(ty)):
            if short[i]:
                ty[i] = ty[i - 1] if i else facing
        ty = np.r_[ty, ty[-1]]
        delta = (facing - ty + np.pi) % (2 * np.pi) - np.pi
        return [float(v) for v in ty + np.clip(delta, -CRAB_MAX, CRAB_MAX)]

    @staticmethod
    def _fill_yaws(start, pts, yaws):
        """Face the direction of travel on legs without an explicit heading."""
        out = []
        prev = np.asarray(start, dtype=float)
        for p, y in zip(pts, yaws):
            d = np.asarray(p) - prev
            if y is None:
                y = float(np.arctan2(d[1], d[0])) if np.hypot(d[0], d[1]) > 0.3 else (out[-1] if out else 0.0)
            out.append(float(y))
            prev = np.asarray(p, dtype=float)
        return out

    def _dispatch_investigations(self, t: float) -> None:
        if os.environ.get("DISASTER_VITALS_DEBUG") and self.tick % 10 == 0:
            av = [(r.id, r.mode) for r in self.drones if r.mode in (EXPLORE, WAIT) and not self.lost(r, t) and not r.grounded
                  and (r.mode == EXPLORE or self._inside(r.pos)) and r.soc > 0.3]
            for c in self.candidates:
                if c.confirmed:
                    print(f"[dispatch] t={t:.0f} cand {c.id} at {np.round(c.pos, 1)}: assigned={c.assigned} dismissed={c.dismissed} "
                          f"vitals={c.vitals is not None} tries={c.vitals_tries} view_fails={c.view_fails} retry_in={max(0.0, c.retry_t - t):.0f} "
                          f"available={av}", flush=True)
        for c in self.candidates:
            if (c.dismissed and not c.confirmed) or c.assigned is not None or t < c.retry_t \
                    or (c.confirmed and (c.vitals is not None or c.vitals_tries >= 2 or c.view_fails >= 6)):
                continue
            avail = [r for r in self.drones if r.mode in (EXPLORE, WAIT) and not self.lost(r, t) and not r.grounded
                     and (r.mode == EXPLORE or self._inside(r.pos)) and r.soc > 0.3]
            if not avail:
                return
            order = sorted(avail, key=lambda r: np.linalg.norm(r.pos - c.pos))
            vt = None
            for k in range(2):  # survivors lie on floors: view from the side, a little above
                if c.confirmed:   # a vitals look: level with them, a few metres off, high enough to fly
                    vt = self._view_point(c.pos + [0, 0, 0.2], np.zeros(3), np.floor(c.pos + [0, 0, 0.6]),
                                          dists=(2.5, 3.0, 3.5, 4.5), lifts=(0.0, 0.6, 1.0, 1.5))
                else:
                    vt = self._view_point(c.pos + [0, 0, 0.2], np.array([0.0, 0.0, 1.0]),
                                          np.floor(c.pos + [0, 0, 0.6]), dists=(3.0, 3.5, 2.5, 4.0))
                if vt is not None:
                    break
            if vt is None:
                if c.confirmed:  # a confirmed survivor is never written off: try again from another spot a little later
                    c.view_fails += 1
                    c.retry_t = t + 15.0
                else:
                    c.attempts += 1
                    c.dismissed = c.attempts >= 3
                continue
            vantage, yaw = vt
            r = next((d for d in order[:4] if self._fly_to(d, vantage, yaw)), None)   # the nearest drone that has a route
            if r is None:
                c.view_fails += 1
                c.retry_t = t + 10.0
                continue
            r.task, r.task_vantage = None, None
            c.assigned, c.assigned_t = r.id, t
            r.candidate = c.id
            self._set_mode(r, INVESTIGATE, t)

    # ----------------------------------------------------------------- relays
    def _predict_cap(self, a: np.ndarray, b: np.ndarray) -> float:
        """Link capacity the master expects between two points, judged from its own map."""
        d = float(np.linalg.norm(b - a))
        n = max(int(d / 0.5), 1)
        pts = a[None, :] + (b - a)[None, :] * (np.arange(n) + 0.5)[:, None] / n
        flat, inside = self.map.flat_of(pts)
        occ = self.map.occupied[flat] & inside
        unknown = ~(self.map.occupied[flat] | self.map.free[flat]) & inside & self.interior.reshape(-1)[flat]
        runs = np.count_nonzero(np.diff(np.concatenate([[0], occ.astype(np.int8)])) == 1)
        per = WALL_DB if abs(b[2] - a[2]) < 3.0 else SLAB_DB
        loss = path_loss_db(np.array(d)) + runs * per + 0.2 * unknown.sum()
        return float(capacity_for(np.array(TX_DBM - loss - NOISE_DBM)))

    def _reconnected(self, r: DroneRecord, t: float) -> None:
        """A drone that froze after losing its link is back in contact (usually through a
        relay that was sent out for it): give it fresh orders rather than its stale path."""
        self._event(t, f"Drone {r.id} back in contact", "success")
        if r.mode in (RELAY, RTB, LANDING, TAKEOFF, SURVEY):
            return  # those keep their goals
        if r.mode in (ENTER, INVESTIGATE):
            self._release(r)
            self._set_mode(r, EXPLORE if self._inside(r.pos) else WAIT, t)
        r.path, r.task, r.task_vantage, r.arrived_t = [], None, None, None

    # ------------------------------------------------------------ comms backbone
    def _need(self, key, point, t: float) -> None:
        """Somebody wants to be at `point`; record it so coverage can be extended there."""
        self.demand[key] = (np.asarray(point, dtype=float), t)

    def _covered(self, p) -> bool:
        return self.link.margin_at(np.asarray(p, dtype=float), self._nodes_plan) >= M_MIN

    def _plan_backbone(self, t: float) -> None:
        """Relay backbone: relay slots are placed so every place the swarm wants to be is
        covered, drones are assigned to them, relays are relieved before their battery runs
        low, and slots nothing uses are given up. Scanners are only admitted to tasks inside
        coverage (`_covered`), so a relay always gets there first."""
        # contact bookkeeping; a drone at the edge or silent is a demand for coverage
        for r in self.drones:
            lost = self.lost(r, t) and not r.crashed
            if lost and not r.was_lost:
                self.lost_events += 1
                self._event(t, f"Drone {r.id} lost contact at ({r.pos[0]:.0f}, {r.pos[1]:.0f}, {r.pos[2]:.0f}): "
                               f"holding until a relay reaches it", "error")
            r.was_lost = lost
            if lost:
                self._need(("lost", r.id), r.pos, t)
            elif r.holding and r.mode not in (RTB, LANDING, TAKEOFF):
                self._need(("hold", r.id), r.pos, t)
        # While there is outside left to fly and the building is known, ask for relay posts at its four corners up front:
        # from a corner the two sides it borders are in line of sight, so the loops are covered before anyone flies them
        # (waiting for a drone to reach the edge of coverage and then calling a relay left the survey drones frozen)
        if self.env_known and self.phase == "operate" and self._open_legs():
            m_ = 10.0
            for i, (cx_, cy_) in enumerate([(self.x0 - m_, self.y0 - m_), (self.x1 + m_, self.y0 - m_),
                                            (self.x1 + m_, self.y1 + m_), (self.x0 - m_, self.y1 + m_)]):
                self._need(("ring", i), np.array([cx_, cy_, 8.0]), t)
        self.demand = {k: v for k, v in self.demand.items() if t - v[1] <= DEMAND_TTL_S}

        # slots: who is on station, relief, usage, release
        for sl in list(self.slots):
            d = self.drones[sl["drone"]] if sl["drone"] is not None else None
            if d is not None and (d.crashed or d.mode != RELAY or d.slot is not sl or self.lost(d, t)):
                if d.slot is sl:
                    d.slot = None
                sl["drone"], sl["on_station"] = None, False
                d = None
            if d is not None:
                sl["on_station"] = bool(np.linalg.norm(d.pos - sl["pos"]) < 3.0 and d.link_cap > 0)
                if d.soc < RELIEF_SOC and sl["relief"] is None:
                    sl["need_relief"] = True
            rf = self.drones[sl["relief"]] if sl["relief"] is not None else None
            if rf is not None:
                if rf.crashed or rf.mode != RELAY or rf.slot is not sl:
                    sl["relief"] = None
                elif np.linalg.norm(rf.pos - sl["pos"]) < 3.0 and rf.link_cap > 0:  # relief is up: hand over
                    if d is not None:
                        d.slot, d.path = None, []
                        self._set_mode(d, WAIT, t)
                    sl["drone"], sl["relief"], sl["need_relief"], sl["on_station"] = rf.id, None, False, True
                    d = rf
            used = d is not None and any(o.parent == d.id and not o.grounded and not o.crashed for o in self.drones)
            used = used or any(np.linalg.norm(p - sl["pos"]) < 45.0 for p, _ in self.demand.values())
            if used or sl["drone"] is None:
                sl["last_used"] = t
            elif t - sl["last_used"] > SLOT_IDLE_S:  # nothing uses it any more
                if d is not None:
                    d.slot, d.path = None, []
                    self._set_mode(d, WAIT, t)
                if rf is not None:
                    rf.slot, rf.path = None, []
                    self._set_mode(rf, WAIT, t)
                self.slots.remove(sl)
        self._nodes = [self.base] + [self.drones[sl["drone"]].pos for sl in self.slots
                                     if sl["drone"] is not None and sl["on_station"]]
        # tasks may be admitted around a post whose relay is already on its way
        self._nodes_plan = self._nodes + [sl["pos"] for sl in self.slots
                                          if sl["drone"] is not None and not sl["on_station"]]
        self.link.update_coverage(self._nodes_plan, t)

        # coverage gaps: plan the relay chain for the most urgent unmet demand
        planned = 0
        order = sorted(self.demand.items(), key=lambda kv: (kv[0][0] != "lost", kv[0][0] != "hold",
                                                            float(np.linalg.norm(kv[1][0] - self.base))))
        for key, (q, _) in order:
            if planned >= 3 or len(self.slots) >= self.max_slots:
                break
            urgent = key[0] in ("lost", "hold")
            if not urgent and self._covered(q):
                continue
            if any(np.linalg.norm(q - sl["pos"]) < 6.0 for sl in self.slots) and not urgent:
                continue  # a relay is already on its way there
            if t - self.demand_planned.get(key, -99.0) < 4.0:
                continue
            self.demand_planned[key] = t
            planned += 1
            floor = M_MIN
            if urgent:  # the prediction said covered but the drone is not: demand a stronger plan
                floor = M_MIN + 6.0
            anchors = list(self._nodes) + [sl["pos"] for sl in self.slots if not sl["on_station"]]
            anchors.sort(key=lambda a: float(np.linalg.norm(a - q)))
            best = None
            for a in anchors[:3]:
                path = self._path_cells(a, q, strict=True, max_exp=60000)
                if path is None:
                    continue
                ch = plan_chain(self.link, path, a, q, floor)
                if ch is not None and (best is None or len(ch) < len(best)):
                    best = ch
            for pos in best or []:
                if len(self.slots) >= self.max_slots or any(np.linalg.norm(pos - sl["pos"]) < 6.0 for sl in self.slots):
                    continue
                self.slot_n += 1
                self.slots.append({"id": self.slot_n, "pos": np.asarray(pos, dtype=float), "drone": None,
                                   "relief": None, "need_relief": False, "on_station": False, "last_used": t})

        # assign drones to empty slots and to relief posts
        posts = [(sl, "drone") for sl in self.slots if sl["drone"] is None and sl["relief"] is None] + \
                [(sl, "relief") for sl in self.slots if sl["need_relief"] and sl["relief"] is None and sl["drone"] is not None]
        if posts:
            standby = (WAIT, IDLE, CHARGING)
            work = (SURVEY, EXPLORE)
            def eligible(h, modes):
                return (h.mode in modes and not h.crashed and not self.lost(h, t) and h.slot is None
                        and (not h.grounded or h.soc >= 0.8) and h.soc >= 0.5)
            pool = [h for h in self.drones if eligible(h, standby)]
            if not [h for h in pool if not h.grounded]:
                pool += [h for h in self.drones if eligible(h, work)]  # nobody spare: a scanner stays behind
            airborne = [h for h in pool if not h.grounded]
            if not airborne:
                for h in pool:  # fresh drones on the pads: get them up
                    if h.grounded and h.mode in (IDLE, CHARGING):
                        self._takeoff(h, t)
                        break
            elif airborne:
                cost = np.array([[float(np.linalg.norm(h.pos - sl["pos"])) + (0.0 if h.mode in standby else 20.0)
                                  for sl, _ in posts] for h in airborne])
                rows, cols = linear_sum_assignment(cost)
                for i, j in sorted(zip(rows, cols), key=lambda ij: cost[ij])[:2]:
                    h, (sl, kind) = airborne[i], posts[j]
                    if not self._fly_to(h, sl["pos"], None):
                        continue
                    self._release(h)
                    h.task, h.task_vantage, h.arrived_t, h.slot = None, None, None, sl
                    if not self._inside(h.pos):
                        h.speed = 3.0
                    sl[kind] = h.id
                    self._set_mode(h, RELAY, t)
                    self._event(t, f"Drone {h.id} to relay post {sl['id']} ({sl['pos'][0]:.0f}, {sl['pos'][1]:.0f}, "
                                   f"{sl['pos'][2]:.0f}){' (relief)' if kind == 'relief' else ''}", "info")

        # a drone that has been holding at the edge too long reels in toward coverage
        for r in self.drones:
            if r.holding and not self.lost(r, t) and r.mode in (SURVEY, EXPLORE, INVESTIGATE, WAIT):
                r.hold_since = r.hold_since if r.hold_since is not None else t
                if t - r.hold_since > 25.0 and not r.path:
                    back = next((p for p in reversed(r.trail) if self._covered(p)), self.base)
                    self._fly_to(r, back, None)
                    r.reeling = True
            else:
                r.hold_since, r.reeling = None, False

    def _leash(self, r: DroneRecord, cmd: StickCommand, t: float) -> StickCommand:
        """Control barrier on link margin (values from `_leash_prepare`): never ask a drone to go
        where its link would fall below M_HOLD; slows the command as the predicted margin
        shrinks. Margin is judged against the backbone (base + relay posts, on station or on
        their way), not against whichever scanner the mesh routes through. The drone's own
        reflex does the same from its measurement; this is the predictive half."""
        if self._cmd_velocity(r, cmd) is None:
            return cmd
        k = r.leash_k
        if k < 1.0:
            cmd.vx, cmd.vy, cmd.vz = cmd.vx * k, cmd.vy * k, cmd.vz * k
            if k < 0.8:
                r.slow_why = f"link leash {k:.1f} now={r.leash_dbg[0]:.0f} ahead={r.leash_dbg[1]:.0f} corr={r.leash_dbg[2]:.0f}"
        return cmd

    # ------------------------------------------------------------ path upkeep
    def _check_paths(self, t: float) -> None:
        """Replan when the map shows something new in the way."""
        for r in self.drones:
            if not r.path or r.mode in (TAKEOFF, LANDING, CRASHED) or self.lost(r, t) or \
                    (r.mode == SURVEY and self.phase != "scout"):
                continue
            prev = np.floor(r.pos)
            for p in r.path[:6]:
                cur = np.floor(np.asarray(p))
                if self.nav.line_clear(prev, cur):
                    prev = cur
                    continue
                goal = np.asarray(r.path[-1])
                yaw = r.yaws[-1] if r.yaws else None
                if not self._fly_to(r, goal, yaw):
                    if r.mode == ENTER and r.entry is not None and r.stage in ("approach", "legacy"):
                        self._fail_entry(r, t, "route blocked")
                        break
                    r.path, r.task, r.task_vantage = [], None, None
                    if r.mode == SURVEY:  # a leg it can't fly: written off, not retried
                        r.survey_done = True
                        if r.scout_tile is not None:
                            self.scout_fail[r.scout_tile] = t + 40.0
                            r.scout_tile = None
                        if r.leg is not None:
                            r.leg["done"], r.leg["owner"], r.leg = True, None, None
                        self._set_mode(r, WAIT, t)
                    if r.mode in (ENTER, INVESTIGATE, RELAY):
                        self._release(r)
                        self._set_mode(r, EXPLORE if self._inside(r.pos) else WAIT, t)
                break

    # ---------------------------------------------------------------- downlink
    # ----------------------------------------------------------------- helpers
    def _takeoff(self, r: DroneRecord, t: float) -> None:
        self._set_mode(r, TAKEOFF, t)
        r.path, r.yaws, r.speed = [(r.pad[0], r.pad[1], 4.0 + r.id % 4)], None, None

    def _time_home(self, r: DroneRecord, t: float) -> float:
        """Flight time back to the pad along the real path through cleared space (re-planned
        every 5 s per drone), slow indoors and at cruise outside; the old straight-line
        estimate is the fallback when no path exists."""
        cached = self.home_len.get(r.id)
        if cached is None or t - cached[0] > 5.0:
            hover = (r.pad[0], r.pad[1], 4.0 + r.id % 4)
            path = self._path_cells(r.pos, hover, strict=True, max_exp=40000, partial=False)
            length = None
            if path is not None:
                pts = np.array([r.pos] + [np.asarray(p, dtype=float) for p in path])
                length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
            cached = (t, length)
            self.home_len[r.id] = cached
        length = cached[1]
        if length is not None:
            speed = 0.7 * self.cfg.indoor_speed if self._inside(r.pos, margin=2) else 0.6 * self.cfg.max_speed
            return 1.4 * length / speed + 8.0
        exit_pt = r.pos
        indoor = 0.0
        if self._inside(r.pos):
            usable = [e.center for e in self.entries if not e.blocked]
            if usable:
                exit_pt = min(usable, key=lambda c: np.linalg.norm(c - r.pos))
                indoor = 1.8 * np.linalg.norm(exit_pt - r.pos) / (0.7 * self.cfg.indoor_speed)
        d = np.linalg.norm(exit_pt[:2] - np.array(r.pad))
        return indoor + 1.6 * d / (0.6 * self.cfg.max_speed) + exit_pt[2] / 1.8 + 8.0

    def _go_home(self, r: DroneRecord, t: float) -> None:
        self._release(r)
        hover = (r.pad[0], r.pad[1], 4.0 + r.id % 4)
        r.path = self._path_cells(r.pos, hover)
        # Indoors at indoor speed; once clear of the building the path is re-sent at cruise.
        r.yaws, r.speed = None, (self.cfg.indoor_speed if self._inside(r.pos, margin=2) else None)
        r.task, r.task_vantage = None, None
        self._set_mode(r, RTB, t)

    def _release(self, r: DroneRecord) -> None:
        if r.candidate is not None:
            c = self.candidates[r.candidate]
            if c.assigned == r.id:
                c.assigned = None
            r.candidate = None
        if r.gap is not None:
            if r.gap.get("drone") == r.id:
                r.gap["drone"], r.gap["state"] = None, "new"
            r.gap = None
        r.serves = None

    def _set_mode(self, r: DroneRecord, mode: str, t: float) -> None:
        r.mode = mode
        r.mode_since = t

    def _event(self, t: float, text: str, level: str) -> None:
        self.events.append({"t": round(t, 1), "text": text, "level": level})
