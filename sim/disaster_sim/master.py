"""Central master computer: all perception and decision making happens here.

Inputs are only what arrives over the radio: camera frames (fused into the voxel map)
and small telemetry packets. Outputs are waypoint commands. The master never reads
ground truth; it knows only the building's rough outline (operator input).

Mission phases:
  survey   -> drones circle the building and sweep the roof, looking for openings
  interior -> drones fan out through the openings and explore/scan the inside
  complete -> everything reachable is mapped; the swarm is recalled
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage
from scipy.optimize import linear_sum_assignment

from .autopilot import Command
from .camera import Frame
from .config import SimConfig
from .planner3d import NavGrid, to_waypoints
from .radio import NOISE_DBM, SLAB_DB, TX_DBM, WALL_DB, capacity_for, path_loss_db
from .voxelmap import VoxelMap

IDLE, TAKEOFF, SURVEY, WAIT, ENTER, EXPLORE, INVESTIGATE, RELAY, RTB, LANDING, CHARGING, CRASHED = (
    "idle", "takeoff", "survey", "wait", "enter", "explore", "investigate", "relay", "rtb", "landing",
    "charging", "crashed")
WORKING = (SURVEY, ENTER, EXPLORE, INVESTIGATE, RELAY, WAIT)

CRUISE_POWER_W = 175.0
RESEND_PERIOD = 2.0
LOST_AFTER = 3.0
LOOK_TIME = 1.5
TILE = 4
FRAME_NEED_BPS = 4.0e5  # what a camera stream needs to get through
RELAY_TARGET_BPS = 2.0e6
SURVEY_STANDOFF = 8.0
ASSOC_RADIUS = 2.0
CONFIRM_DETECTIONS = 3
CONFIRM_RANGE = 6.0
INVESTIGATE_TIMEOUT = 40.0
MAX_PLANS_PER_TICK = 4
RELAY_SETTLE_S = 10.0  # a relay on station this long without restoring contact -> chain another

_SIX = ndimage.generate_binary_structure(3, 1)
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
    entry: int | None = None
    serves: int | None = None  # relay: the drone it keeps connected
    link_cap: float = 0.0
    hops: int = 0
    trail: list = field(default_factory=list)
    sent: tuple | None = None
    sent_t: float = -1e9
    survey_done: bool = False


@dataclass
class Entry:
    id: int
    center: np.ndarray
    normal: np.ndarray
    w: float
    h: float
    side: str
    blocked: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "center": [round(float(v), 2) for v in self.center],
                "normal": [float(v) for v in self.normal], "w": float(self.w), "h": float(self.h),
                "side": self.side, "blocked": self.blocked}


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

    def to_dict(self) -> dict:
        return {"id": self.id, "pos": [round(float(v), 2) for v in self.pos], "n": self.n_det,
                "confirmed": self.confirmed, "dismissed": self.dismissed, "drone": self.assigned}


class MasterController:
    def __init__(self, cfg: SimConfig, shape, outline, pads: np.ndarray, base):
        self.cfg = cfg
        self.map = VoxelMap(shape, cfg)
        self.shape = tuple(shape)
        self.x0, self.y0, self.x1, self.y1, self.top = outline
        self.base = np.array(base, dtype=float)
        self.drones = [DroneRecord(i, (float(pads[i, 0]), float(pads[i, 1]))) for i in range(len(pads))]
        self.phase = "survey"
        self.entries: list[Entry] = []
        self.candidates: list[Candidate] = []
        self.events: list[dict] = []
        self.tick = 0
        self.seq = 0
        self.nav: NavGrid | None = None
        self.ignore = np.zeros(self.shape, dtype=bool)
        self.unreachable: dict[tuple, float] = {}
        self.targets: list[dict] = []
        self.done_since: float | None = None
        sx, sy, sz = self.shape
        self.interior = np.zeros(self.shape, dtype=bool)
        self.interior[self.x0 + 1:self.x1 - 1, self.y0 + 1:self.y1 - 1, 1:self.top] = True
        outdoor = np.ones(self.shape, dtype=bool)
        outdoor[max(self.x0 - 1, 0):self.x1 + 1, max(self.y0 - 1, 0):self.y1 + 1, :self.top + 2] = False
        outdoor[:, :, 0] = False
        outdoor[:, :, sz - 2:] = False
        self.outdoor = outdoor
        self.map.sparse2d = outdoor[:, :, 1].copy()
        # Usable half of the vertical field of view: the camera is fixed to the nose, so a
        # target must sit within this elevation of the vantage point to be seen.
        self.half_vfov = np.deg2rad(cfg.cam_vfov_deg / 2 - 6.0)
        self.survey_legs = self._plan_survey()

    # ------------------------------------------------------------------ inputs
    def on_frame(self, f: Frame, t: float) -> None:
        det = self.map.integrate(f, self.tick)
        pts, dist = det["survivor_pts"], det["survivor_dist"]
        used = np.zeros(len(pts), dtype=bool)
        for i in range(len(pts)):  # one detection per cluster of survivor pixels
            if used[i]:
                continue
            near = np.linalg.norm(pts - pts[i], axis=1) < ASSOC_RADIUS
            used |= near
            self._associate(pts[near].mean(axis=0), float(dist[near].min()), f.drone, t)

    def on_telemetry(self, m: dict, t: float) -> None:
        r = self.drones[m["drone"]]
        if m["t"] < r.last_seen:
            return
        if self.lost(r, t) and not m["crashed"]:
            self._reconnected(r, t)
        r.pos, r.vel, r.soc = np.asarray(m["pos"]), np.asarray(m["vel"]), m["soc"]
        r.grounded, r.last_seen = m["grounded"], m["t"]
        r.link_cap, r.hops = m["link_cap"], m["hops"]
        if not r.trail or np.linalg.norm(r.trail[-1] - r.pos) > 2.0:
            r.trail.append(r.pos.copy())
            r.trail = r.trail[-300:]
        if m["crashed"] and not r.crashed:
            r.crashed = True
            self._set_mode(r, CRASHED, t)
            self._release(r)
            self._event(t, f"Drone {r.id} lost (crash)", "error")

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
    def step(self, t: float) -> list[tuple[int, Command]]:
        self.tick += 1
        self._build_nav()
        self._detect_entries(t)
        self._update_modes(t)
        if self.phase == "interior":
            self._find_targets(t)
            self._dispatch_investigations(t)
            self._assign_entries(t)
            self._allocate(t)
            self._plan_relays(t)
        self._check_paths(t)
        return self._emit(t)

    def _build_nav(self) -> None:
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        passable = free | (self.outdoor & ~occ)
        passable[:, :, 0] = False
        self.nav = NavGrid(passable, occ)

    def lost(self, r: DroneRecord, t: float) -> bool:
        return r.last_seen >= 0 and t - r.last_seen > LOST_AFTER and not r.grounded

    def _update_modes(self, t: float) -> None:
        cap_j = self.cfg.battery_wh * 3600.0
        for r in self.drones:
            if r.mode == CRASHED or self.lost(r, t):
                continue
            if r.mode == IDLE:
                if self.phase != "complete" and t >= 1.0 + 1.2 * r.id and r.soc > 0.5:
                    self._takeoff(r, t)
            elif r.mode == TAKEOFF:
                if r.pos[2] > 3.0:
                    if self.phase == "survey" and not r.survey_done:
                        self._start_survey_leg(r, t)
                    else:
                        self._set_mode(r, WAIT, t)
                        r.path = []
            elif r.mode in WORKING:
                time_home = self._time_home(r)
                need = time_home * CRUISE_POWER_W / cap_j + self.cfg.rtb_reserve
                if r.soc < need:
                    self._event(t, f"Drone {r.id} returning to base (battery {r.soc:.0%})", "warn")
                    self._go_home(r, t)
                    continue
                if r.mode == SURVEY and r.path and np.linalg.norm(r.pos - np.array(r.path[-1])) < 1.5:
                    r.survey_done = True
                    self._set_mode(r, WAIT, t)
                    r.path = []
                elif r.mode == ENTER and r.task_vantage is not None and self._inside(r.pos) \
                        and np.linalg.norm(r.pos - r.task_vantage) < 1.5:
                    self._set_mode(r, EXPLORE, t)
                    r.path, r.task, r.task_vantage = [], None, None
                elif r.mode == INVESTIGATE:
                    c = self.candidates[r.candidate]
                    if c.confirmed or t - c.assigned_t > INVESTIGATE_TIMEOUT:
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

        if self.phase == "survey":
            surveying = [r for r in self.drones if r.mode == SURVEY or (r.mode in (IDLE, TAKEOFF) and not r.survey_done)]
            if (not surveying and t > 10) or t > 300:
                self.phase = "interior"
                usable = [e for e in self.entries if not e.blocked]
                self._event(t, f"Exterior survey complete: {len(self.entries)} openings, {len(usable)} usable. "
                               f"Interior volume initialized ({self.cfg.floors} floors)", "success")
        elif self.phase == "interior":
            open_c = any(not (c.confirmed or c.dismissed) for c in self.candidates)
            if not self.targets and not open_c:
                self.done_since = self.done_since or t
                if t - self.done_since > 8.0:
                    self.phase = "complete"
                    self._event(t, "Building mapped: recalling swarm", "success")
                    for r in self.drones:
                        if r.mode in WORKING:
                            self._go_home(r, t)
            else:
                self.done_since = None

    # ----------------------------------------------------------------- survey
    def _plan_survey(self) -> list[list]:
        """Perimeter loops at each floor's height plus a roof sweep, split into equal legs."""
        s = SURVEY_STANDOFF
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
        for j, y in enumerate(np.arange(self.y0 + 4, self.y1 - 3, 10.0)):
            xs = (self.x0 - 2, self.x1 + 2) if j % 2 == 0 else (self.x1 + 2, self.x0 - 2)
            yaw = 0.0 if xs[1] > xs[0] else np.pi
            for x in np.linspace(xs[0], xs[1], 8):
                pts.append(((float(x), float(y), zr), yaw))
        n = len(self.drones)
        chunk = int(np.ceil(len(pts) / n))
        return [pts[i * chunk:(i + 1) * chunk] for i in range(n)]

    def _start_survey_leg(self, r: DroneRecord, t: float) -> None:
        leg = self.survey_legs[r.id]
        if not leg:
            r.survey_done = True
            self._set_mode(r, WAIT, t)
            return
        approach = self._path_cells(r.pos, leg[0][0])[:-1]
        pts = approach + [p for p, _ in leg]
        r.path = pts
        r.yaws = self._fill_yaws(r.pos, pts, [None] * len(approach) + [y for _, y in leg])
        r.speed = 3.0
        self._set_mode(r, SURVEY, t)

    def _path_cells(self, a, b) -> list:
        cells = self.nav.astar(np.floor(a), np.floor(b)) if self.nav else None
        pts = to_waypoints(cells[1:]) if cells else []
        return self._center_heights(pts) + [tuple(float(v) for v in b)]

    # ---------------------------------------------------------- entry finding
    def _detect_entries(self, t: float) -> None:
        if self.tick % 2:
            return
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        found = []
        walls = [("west", "x", self.x0, 1), ("east", "x", self.x1 - 1, -1),
                 ("south", "y", self.y0, 1), ("north", "y", self.y1 - 1, -1)]
        for name, axis, c, step in walls:
            if axis == "x":
                plane = free[c, self.y0:self.y1, 1:self.top] & free[c + step, self.y0:self.y1, 1:self.top]
                behind = occ[c + 2 * step, self.y0:self.y1, 1:self.top] | occ[c + 3 * step, self.y0:self.y1, 1:self.top]
            else:
                plane = free[self.x0:self.x1, c, 1:self.top] & free[self.x0:self.x1, c + step, 1:self.top]
                behind = occ[self.x0:self.x1, c + 2 * step, 1:self.top] | occ[self.x0:self.x1, c + 3 * step, 1:self.top]
            lab, _ = ndimage.label(plane)
            for k, sl in enumerate(ndimage.find_objects(lab)):
                w, h = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
                if w < 2 or h < 2:
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
        roof = free[self.x0:self.x1, self.y0:self.y1, self.top] & free[self.x0:self.x1, self.y0:self.y1, self.top - 1]
        lab, _ = ndimage.label(roof)
        for k, sl in enumerate(ndimage.find_objects(lab)):
            w, h = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if w < 2 or h < 2:
                continue
            cx, cy = np.argwhere(lab == k + 1).mean(axis=0)
            found.append((np.array([self.x0 + cx + 0.5, self.y0 + cy + 0.5, self.top + 0.5]),
                          np.array([0.0, 0.0, -1.0]), float(w), float(h), "roof", False))
        for center, normal, w, h, side, blocked in found:
            match = next((e for e in self.entries if np.linalg.norm(e.center - center) < 4.0), None)
            if match:
                match.center, match.w, match.h, match.blocked = center, max(match.w, w), max(match.h, h), blocked
                continue
            e = Entry(len(self.entries), center, normal, w, h, side, blocked)
            self.entries.append(e)
            where = "roof" if side == "roof" else f"{side} wall, floor {int(center[2] // self.cfg.story) + 1}"
            self._event(t, f"Entry point found: {w:.0f}x{h:.0f} m opening ({where})"
                           f"{' - blocked by debris' if blocked else ''}", "info")

    def _assign_entries(self, t: float) -> None:
        waiting = [r for r in self.drones if r.mode == WAIT and not self.lost(r, t)]
        usable = [e for e in self.entries if not e.blocked]
        if not waiting or not usable:
            return
        reps = int(np.ceil(len(waiting) / len(usable)))
        cols = [e for _ in range(reps) for e in usable]
        pen = np.repeat(np.arange(reps) * 40.0, len(usable))
        cost = np.array([[np.linalg.norm(r.pos - (e.center - e.normal * 3)) for e in cols] for r in waiting]) + pen
        rows, js = linear_sum_assignment(cost)
        for k, j in zip(rows, js):
            r, e = waiting[k], cols[j]
            outside = e.center - e.normal * 3.0
            inside = e.center + e.normal * 1.5
            for depth in (4.0, 3.0, 2.0):
                cand = e.center + e.normal * depth
                if self.nav.ok(np.floor(cand)):
                    inside = cand
                    break
            pts = self._path_cells(r.pos, outside) + [tuple(e.center), tuple(inside)]
            r.path, r.yaws, r.speed = pts, None, self.cfg.indoor_speed
            r.yaws = self._fill_yaws(r.pos, pts, [None] * len(pts))
            r.task_vantage = np.asarray(inside)
            r.entry = e.id
            self._set_mode(r, ENTER, t)
            self._event(t, f"Drone {r.id} entering through {e.side} opening #{e.id}", "info")

    def _inside(self, p, margin: float = 0.0) -> bool:
        return (self.x0 - margin < p[0] < self.x1 + margin and self.y0 - margin < p[1] < self.y1 + margin
                and p[2] < self.top + margin)

    # --------------------------------------------------------------- explore
    def _find_targets(self, t: float) -> None:
        m = self.map
        free = m.grid(m.free)
        occ = m.grid(m.occupied)
        unknown = ~free & ~occ
        frontier = free & self.interior & ndimage.binary_dilation(unknown, _SIX) & ~self.ignore
        low_q = m.grid(m.quality < m.q.threshold)
        surface = occ & self.interior & low_q & ndimage.binary_dilation(free, _SIX) & ~self.ignore
        targets = []
        story = self.cfg.story
        for kind, mask in (("frontier", frontier), ("surface", surface)):
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
            elif kind == "surface" and free[tuple(q)]:
                acc += d  # exposed face normal
        if not acc.any():
            return None
        n = acc / np.linalg.norm(acc)
        if kind == "frontier":
            # Look into the unknown just past the frontier; sight line must reach the frontier voxel.
            return self._view_point(v + 0.5 + n * 1.0, n, v, dists=(1.5, 2.5, 3.5))
        return self._view_point(v + 0.5, n, v + np.round(n).astype(int), dists=(3.0, 2.5, 3.5, 2.0, 1.5))

    def _view_point(self, target: np.ndarray, normal: np.ndarray, sight_cell, dists):
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
        for d in dists:
            dz = sz * min(1.5, d * tan_v * 0.9)
            for ang in np.linspace(0, 2 * np.pi, 8, endpoint=False):
                cands.append(target + np.array([np.cos(ang) * d, np.sin(ang) * d, dz]))
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
                    self.ignore[c[:, 0], c[:, 1], c[:, 2]] = True
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
        for k, r in enumerate(idle):
            fl = np.abs(vox[:, 2] // story - r.pos[2] // story)
            cost[k] = np.linalg.norm(vox - r.pos, axis=1) + 15.0 * fl - 3.0 * np.sqrt(gain)
        rows, cols = linear_sum_assignment(cost)
        plans = 0
        for k, j in sorted(zip(rows, cols), key=lambda kj: cost[kj]):
            if plans >= MAX_PLANS_PER_TICK:
                break  # bound A* work per tick; the rest get targets next tick
            r, g = idle[k], avail[j]
            vt = self._vantage(g)
            if vt is None:
                self.unreachable[g["tile"]] = t + 20.0
                continue
            vantage, yaw = vt
            plans += 1
            if not self._fly_to(r, vantage, yaw):
                self.unreachable[g["tile"]] = t + 20.0
                continue
            r.task, r.task_vantage, r.arrived_t = g["tile"], np.asarray(vantage), None

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
        for c in self.candidates:
            if c.confirmed or c.dismissed or c.assigned is not None:
                continue
            avail = [r for r in self.drones if r.mode == EXPLORE and not self.lost(r, t)]
            if not avail:
                return
            r = min(avail, key=lambda r: np.linalg.norm(r.pos - c.pos))
            vt = None
            for k in range(2):  # survivors lie on floors: view from the side, a little above
                vt = self._view_point(c.pos + [0, 0, 0.2], np.array([0.0, 0.0, 1.0]),
                                      np.floor(c.pos + [0, 0, 0.6]), dists=(3.0, 3.5, 2.5, 4.0))
                if vt is not None:
                    break
            if vt is None:
                c.attempts += 1
                c.dismissed = c.attempts >= 3
                continue
            vantage, yaw = vt
            if not self._fly_to(r, vantage, yaw):
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
        relays = [h for h in self.drones if h.mode == RELAY and h.serves == r.id]
        via = f" via relay D{relays[-1].id}" if relays else ""
        self._event(t, f"Drone {r.id} back in contact{via}", "success")
        if r.mode in (RELAY, RTB, LANDING, TAKEOFF, SURVEY):
            return  # those keep their goals
        if r.mode in (ENTER, INVESTIGATE):
            self._release(r)
            self._set_mode(r, EXPLORE if self._inside(r.pos) else WAIT, t)
        r.path, r.task, r.task_vantage, r.arrived_t = [], None, None, None

    def _plan_relays(self, t: float) -> None:
        for rl in [r for r in self.drones if r.mode == RELAY]:
            served = self.drones[rl.serves] if rl.serves is not None else None
            keep = served is not None and not served.crashed and (
                served.mode in (ENTER, EXPLORE, INVESTIGATE, RELAY) or self.lost(served, t))
            if not keep:
                why = "crashed" if served is not None and served.crashed else (served.mode if served else "none")
                self._event(t, f"Drone {rl.id} released from relay duty (served drone: {why})", "info")
                rl.serves = None
                self._set_mode(rl, EXPLORE if self._inside(rl.pos) else WAIT, t)
                rl.path, rl.task, rl.arrived_t = [], None, None
            elif rl.arrived_t is None and (not rl.path or np.linalg.norm(rl.pos - np.asarray(rl.path[-1])) < 1.5):
                rl.arrived_t = t
        relays = [r for r in self.drones if r.mode == RELAY]

        # 1) Drones that went silent are frozen where they lost the link: bring a relay to
        #    them. If the relays already sent are on station and it is still silent, chain
        #    another one further out.
        for r in self.drones:
            if not self.lost(r, t) or r.crashed or r.mode == LANDING:
                continue
            if len(relays) >= max(2, len(self.drones) // 2):
                break
            mine = [rl for rl in relays if rl.serves == r.id]
            if any(rl.arrived_t is None or t - rl.arrived_t < RELAY_SETTLE_S or self.lost(rl, t) for rl in mine):
                continue
            if self._post_relay(r, relays, t, rescue=True):
                return  # one new relay per tick

        # 2) Connected drones whose link is too weak for their camera stream.
        if len(relays) >= max(1, len(self.drones) // 3):
            return
        served = {r.serves for r in relays}
        for r in self.drones:
            if r.mode not in (EXPLORE, INVESTIGATE) or r.id in served or len(r.trail) < 3 or self.lost(r, t):
                continue
            if r.link_cap >= FRAME_NEED_BPS:
                continue
            if self._post_relay(r, relays, t, rescue=False):
                return

    def _post_relay(self, r: DroneRecord, relays: list, t: float, rescue: bool) -> bool:
        """Send the best available drone to a point on `r`'s trail that bridges the mesh
        (base station plus every drone still in contact) and `r`'s last known position."""
        if len(r.trail) < 2:
            return False
        chain = [self.base] + [h.pos for h in self.drones
                               if h.id != r.id and not h.crashed and not h.grounded and not self.lost(h, t)
                               and h.link_cap > 0]
        best, best_score = None, -1.0
        for p in r.trail[::-1]:
            to_chain = max(self._predict_cap(p, c) for c in chain)
            score = min(to_chain, self._predict_cap(p, r.pos))
            if score > best_score:
                best, best_score = p, score
            if score >= RELAY_TARGET_BPS:
                break
        ok_modes = (EXPLORE, WAIT) if not rescue else (EXPLORE, WAIT, IDLE, CHARGING)
        helpers = [h for h in self.drones if h.mode in ok_modes and h.id != r.id and not self.lost(h, t)
                   and (not h.grounded or h.soc >= 0.8)]
        if best is None or not helpers:
            return False
        h = min(helpers, key=lambda h: np.linalg.norm(h.pos - best))
        look = r.pos - best
        if not self._fly_to(h, best, float(np.arctan2(look[1], look[0]))):
            return False
        self._release(h)
        h.task, h.task_vantage, h.serves, h.arrived_t = None, None, r.id, None
        self._set_mode(h, RELAY, t)
        if rescue:
            self._event(t, f"Drone {r.id} silent, frozen at ({r.pos[0]:.0f}, {r.pos[1]:.0f}, {r.pos[2]:.0f}): "
                           f"sending drone {h.id} as relay", "warn")
        else:
            self._event(t, f"Drone {h.id} posted as radio relay for drone {r.id}", "warn")
        return True

    # ------------------------------------------------------------ path upkeep
    def _check_paths(self, t: float) -> None:
        """Replan when the map shows something new in the way."""
        for r in self.drones:
            if not r.path or r.mode in (TAKEOFF, LANDING, CRASHED, SURVEY) or self.lost(r, t):
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
                    r.path, r.task, r.task_vantage = [], None, None
                    if r.mode in (ENTER, INVESTIGATE, RELAY):
                        self._release(r)
                        self._set_mode(r, EXPLORE if self._inside(r.pos) else WAIT, t)
                break

    # ---------------------------------------------------------------- downlink
    def _emit(self, t: float) -> list[tuple[int, Command]]:
        out = []
        for r in self.drones:
            if r.mode == CRASHED:
                continue
            if r.mode in (IDLE, CHARGING):
                desired, make = ("idle",), (lambda seq: Command(seq, "idle"))
            elif r.mode == LANDING:
                desired, make = ("land", r.pad), (lambda seq, r=r: Command(seq, "land", pad=r.pad))
            elif r.path:
                desired = ("path", tuple(r.path), tuple(r.yaws or ()), r.speed)
                make = lambda seq, r=r: Command(seq, "path", list(r.path), r.yaws, r.speed,
                                                keep_on_loss=r.mode == RTB)
            else:
                desired, make = ("hold",), (lambda seq: Command(seq, "hold"))
            if desired != r.sent or t - r.sent_t > RESEND_PERIOD:
                self.seq += 1
                out.append((r.id, make(self.seq)))
                r.sent, r.sent_t = desired, t
        return out

    # ----------------------------------------------------------------- helpers
    def _takeoff(self, r: DroneRecord, t: float) -> None:
        self._set_mode(r, TAKEOFF, t)
        r.path, r.yaws, r.speed = [(r.pad[0], r.pad[1], 4.0 + r.id % 4)], None, None

    def _time_home(self, r: DroneRecord) -> float:
        """Rough flight time back to the pad: slow indoor leg to the nearest opening, then
        cruise outside."""
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
        r.serves = None

    def _set_mode(self, r: DroneRecord, mode: str, t: float) -> None:
        r.mode = mode
        r.mode_since = t

    def _event(self, t: float, text: str, level: str) -> None:
        self.events.append({"t": round(t, 1), "text": text, "level": level})
