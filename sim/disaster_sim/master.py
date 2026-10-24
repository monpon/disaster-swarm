"""Central master computer: the single orchestrator for the whole swarm.

The master never sees ground truth. It learns about the world only through
telemetry and map/detection packets arriving over the (lossy, delayed) uplink,
and it controls drones only by sending high-level commands over the downlink.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

from .autopilot import Command
from .config import SimConfig
from .mapping import OccupancyGrid, ScanModel
from .planner import Frontier, astar, blocked_mask, find_frontiers, line_clear

IDLE, TAKEOFF, EXPLORE, INVESTIGATE, RTB, LANDING, CHARGING, CRASHED, DONE = (
    "idle", "takeoff", "explore", "investigate", "rtb", "landing", "charging", "crashed", "done")

CRUISE_POWER_W = 175.0
CONFIRM_DETECTIONS = 4
ASSOC_RADIUS = 6.0
INVESTIGATE_TIMEOUT = 30.0
MAX_ATTEMPTS = 2
LOOK_TIME = 3.0  # seconds at a vantage point before an unscannable target is written off
LOW_HOP = 70.0  # hops shorter than this stay at scanning altitude instead of climbing to cruise
VANTAGE_DIRS = 8  # candidate directions to scan a target from
RESEND_PERIOD = 2.0
SEPARATION_H = 8.0
SEPARATION_V = 2.5


@dataclass
class DroneRecord:
    id: int
    pad: tuple[float, float]
    cruise_alt: float
    mode: str = IDLE
    pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
    vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    soc: float = 1.0
    grounded: bool = True
    crashed: bool = False
    last_seen: float = -1.0
    mode_since: float = 0.0
    target: tuple[float, float, float] | None = None
    path: list[tuple[float, float, float]] = field(default_factory=list)
    candidate: int | None = None
    look_at: tuple[float, float] | None = None
    frontier: tuple[int, int] | None = None
    arrived_t: float | None = None
    holding: bool = False
    sent: tuple | None = None
    sent_t: float = -1e9


@dataclass
class Candidate:
    id: int
    x: float
    y: float
    n_det: int = 1
    best_range: float = 1e9
    confirmed: bool = False
    assigned: int | None = None
    assigned_t: float = 0.0
    confirmed_t: float | None = None
    attempts: int = 0
    dismissed: bool = False

    def to_dict(self) -> dict:
        return {"id": self.id, "x": round(self.x, 2), "y": round(self.y, 2),
                "n": self.n_det, "confirmed": self.confirmed, "dismissed": self.dismissed,
                "drone": self.assigned}


class MasterController:
    def __init__(self, cfg: SimConfig, pads: np.ndarray, geom):
        self.cfg = cfg
        self.geom = geom  # grid geometry only: cell_of, cell_center, n
        self.map = OccupancyGrid(geom.n)
        self.scan = ScanModel(cfg.scan_near, cfg.cam_range, cfg.proper_scan_range)
        self.tan_pitch = np.tan(np.deg2rad(cfg.cam_pitch_deg))
        self.drones = [
            DroneRecord(i, (float(pads[i, 0]), float(pads[i, 1])),
                        cfg.cruise_alt + (i % cfg.n_alt_layers) * cfg.alt_layer_step)
            for i in range(len(pads))
        ]
        self.candidates: list[Candidate] = []
        self.acked_tick = np.full(len(pads), -1, dtype=np.int64)
        self.seq = 0
        self.tick = 0
        self.events: list[dict] = []
        self.frontiers: list[Frontier] = []
        self.ignore = np.zeros((geom.n, geom.n), dtype=bool)
        self.mission_done = False
        self._blocked_cache: dict[float, np.ndarray] = {}

    # ------------------------------------------------------------------ uplink
    def ingest(self, pkt: dict, t: float) -> None:
        r = self.drones[pkt["drone"]]
        if pkt["t"] < r.last_seen:
            return  # reordered, older than what we have
        r.pos = np.asarray(pkt["pos"])
        r.vel = np.asarray(pkt["vel"])
        r.soc = pkt["soc"]
        r.grounded = pkt["grounded"]
        r.last_seen = pkt["t"]
        if pkt["crashed"] and not r.crashed:
            r.crashed = True
            self._set_mode(r, CRASHED, t)
            self._event(t, f"Drone {r.id} lost (crash)", "error")
            self._release_candidate(r)
        if len(pkt["cells"][0]) and self.map.apply_cells(*pkt["cells"], tick=self.tick):
            self._blocked_cache.clear()
        self.map.apply_seen(*pkt["seen"])
        self.acked_tick[r.id] = max(self.acked_tick[r.id], pkt["tick"])
        for (x, y, rng) in pkt["detections"]:
            self._associate(x, y, rng, r.id, t)

    def _associate(self, x: float, y: float, rng: float, drone: int, t: float) -> None:
        for c in self.candidates:
            if np.hypot(c.x - x, c.y - y) < ASSOC_RADIUS:
                c.x += (x - c.x) / (c.n_det + 1)
                c.y += (y - c.y) / (c.n_det + 1)
                c.n_det += 1
                c.best_range = min(c.best_range, rng)
                if (not c.confirmed and c.n_det >= CONFIRM_DETECTIONS
                        and c.best_range <= self.cfg.confirm_range):
                    c.confirmed = True
                    c.confirmed_t = t
                    self._event(t, f"Survivor #{c.id} confirmed by drone {drone} at "
                                   f"({c.x:.0f}, {c.y:.0f})", "success")
                return
        c = Candidate(len(self.candidates), x, y, best_range=rng)
        self.candidates.append(c)
        self._event(t, f"Drone {drone} spotted possible survivor at ({x:.0f}, {y:.0f})", "info")

    # ---------------------------------------------------------------- planning
    def step(self, t: float) -> list[tuple[int, Command]]:
        self.tick += 1
        self._update_modes(t)
        self._write_off_unseen(t)
        self.frontiers = find_frontiers(self.map, self.scan.threshold, self.ignore)
        self._dispatch_investigations(t)
        self._allocate_frontiers(t)
        self._check_paths()
        self._separation()
        return self._emit(t)

    def _update_modes(self, t: float) -> None:
        cap_j = self.cfg.battery_wh * 3600.0
        open_candidates = any(not (c.confirmed or c.dismissed) for c in self.candidates)
        work_left = bool(self.frontiers) or open_candidates
        for r in self.drones:
            if r.mode == CRASHED:
                continue
            if r.mode == IDLE:
                if not self.mission_done and t >= 1.0 + 1.5 * r.id and r.soc > 0.5:
                    self._takeoff(r, t)
            elif r.mode == TAKEOFF:
                if r.pos[2] >= r.cruise_alt - 2.0:
                    self._set_mode(r, EXPLORE, t)
            elif r.mode in (EXPLORE, INVESTIGATE, DONE):
                dist = np.hypot(r.pos[0] - r.pad[0], r.pos[1] - r.pad[1])
                time_home = dist / (0.75 * self.cfg.max_speed) + r.pos[2] / 1.8 + 5.0
                need = time_home * CRUISE_POWER_W / cap_j + self.cfg.rtb_reserve
                if r.soc < need:
                    self._event(t, f"Drone {r.id} returning to base (battery {r.soc:.0%})", "warn")
                    self._go_home(r, t)
                elif r.mode == INVESTIGATE:
                    c = self.candidates[r.candidate]
                    if c.confirmed or t - c.assigned_t > INVESTIGATE_TIMEOUT:
                        if not c.confirmed:
                            c.attempts += 1
                            if c.attempts >= MAX_ATTEMPTS:
                                c.dismissed = True
                                self._event(t, f"Candidate #{c.id} dismissed after {c.attempts} "
                                               "inconclusive passes", "warn")
                        self._release_candidate(r)
                        self._set_mode(r, EXPLORE, t)
                elif r.mode == EXPLORE and not self.frontiers and not open_candidates:
                    self._go_home(r, t)
                elif r.mode == DONE:
                    self._go_home(r, t)
            elif r.mode == RTB:
                if np.hypot(r.pos[0] - r.pad[0], r.pos[1] - r.pad[1]) < 3.0:
                    self._set_mode(r, LANDING, t)
                    r.path, r.target = [], None
            elif r.mode == LANDING:
                if r.grounded and t - r.mode_since > 1.0:
                    self._set_mode(r, CHARGING, t)
            elif r.mode == CHARGING:
                if r.soc >= 0.97:
                    if work_left and not self.mission_done:
                        self._takeoff(r, t)
                    else:
                        self._set_mode(r, IDLE, t)

        if not self.mission_done and self.tick > 20 and self.map.known.any() and not work_left:
            self.mission_done = True
            self._event(t, "Area fully mapped, recalling swarm", "success")
            for r in self.drones:
                if r.mode in (EXPLORE, INVESTIGATE, TAKEOFF):
                    self._set_mode(r, DONE, t)

    def _dispatch_investigations(self, t: float) -> None:
        for c in self.candidates:
            if c.confirmed or c.dismissed or c.assigned is not None:
                continue
            avail = [r for r in self.drones if r.mode == EXPLORE]
            if not avail:
                return
            r = min(avail, key=lambda r: np.hypot(r.pos[0] - c.x, r.pos[1] - c.y))
            c.assigned, c.assigned_t = r.id, t
            r.candidate = c.id
            self._set_mode(r, INVESTIGATE, t)
            # The camera looks forward and down, so stand off from the candidate and face it.
            # Each retry approaches from a different side in case a wall blocked the view.
            ang = np.arctan2(c.y - r.pos[1], c.x - r.pos[0]) + c.attempts * np.pi / 2
            standoff = self.cfg.investigate_agl / np.tan(np.deg2rad(self.cfg.cam_pitch_deg))
            ax, ay = c.x - standoff * np.cos(ang), c.y - standoff * np.sin(ang)
            cx_i, cy_i = self.geom.cell_of(c.x, c.y)
            ax_i, ay_i = self.geom.cell_of(ax, ay)
            safe = self.map.safe_height()
            ground = max(float(safe[cx_i, cy_i]), float(safe[ax_i, ay_i]))
            self._plan_to(r, (ax, ay, r.cruise_alt), final=(ax, ay, ground + self.cfg.investigate_agl))
            r.look_at = (c.x, c.y)

    def _write_off_unseen(self, t: float) -> None:
        """Targets still not properly scanned after looking from the vantage point are written off."""
        for r in self.drones:
            if r.mode != EXPLORE or r.frontier is None or not r.path:
                r.arrived_t = None
                continue
            vp = np.asarray(r.path[-1])
            if np.linalg.norm(r.pos - vp) > 4.0:
                r.arrived_t = None
                continue
            if r.arrived_t is None:
                r.arrived_t = t
                # Now that the surroundings are mapped, a lower vantage may be safe.
                plan = self._vantage(r, *r.frontier)
                if plan is not None and plan[2] < vp[2] - 3.0:
                    self._fly_scan(r, plan)
                    r.arrived_t = None
            elif t - r.arrived_t > LOOK_TIME:
                ix, iy = r.frontier
                win = (slice(max(ix - 1, 0), ix + 2), slice(max(iy - 1, 0), iy + 2))
                self.ignore[win] |= self.map.quality[win] < self.scan.threshold
                r.frontier, r.target, r.arrived_t = None, None, None

    def _vantage(self, r: DroneRecord, ix: int, iy: int):
        """Best hover point to properly scan cell (ix, iy): (vx, vy, alt, fx, fy) or None.

        The camera looks forward and down, so the drone hovers `scan_agl` above the target,
        set back so the target sits in the middle of the view. Several approach directions
        are tried; the lowest safe hover wins (closer = better scan).
        """
        fx, fy = (float(v) for v in self.geom.cell_center(ix, iy))
        th = float(self.map.height[ix, iy]) if self.map.quality[ix, iy] > 0 else 0.0
        safe = self.map.safe_height()
        known = self.map.quality > 0
        half = self.cfg.world_size / 2 - 2.0
        base = np.arctan2(fy - r.pos[1], fx - r.pos[0])
        best = None
        for k in range(VANTAGE_DIRS):
            ang = base + k * 2 * np.pi / VANTAGE_DIRS
            zs = th + self.cfg.scan_agl
            for _ in range(2):  # hover height depends on standoff and vice versa
                standoff = (zs - th) / self.tan_pitch
                vx = float(np.clip(fx - standoff * np.cos(ang), -half, half))
                vy = float(np.clip(fy - standoff * np.sin(ang), -half, half))
                vi, vj = (int(v) for v in self.geom.cell_of(vx, vy))
                win = (slice(max(vi - 2, 0), vi + 3), slice(max(vj - 2, 0), vj + 3))
                if not known[win].all():
                    zs = max(zs, r.cruise_alt)  # unmapped below the hover point: stay high
                zs = max(zs, float(safe[win].max()) + 6.0)
            cost = (zs - th) + 4.0 * min(k, VANTAGE_DIRS - k)  # prefer low, then straight ahead
            if best is None or cost < best[0]:
                best = (cost, (vx, vy, float(min(zs, 60.0)), fx, fy))
        return best[1] if best else None

    def _fly_scan(self, r: DroneRecord, plan) -> None:
        vx, vy, zs, fx, fy = plan
        hop = np.hypot(vx - r.pos[0], vy - r.pos[1])
        leg_alt = zs if hop < LOW_HOP else max(r.cruise_alt, zs)
        self._plan_to(r, (vx, vy, leg_alt), alt=leg_alt,
                      final=(vx, vy, zs) if abs(leg_alt - zs) > 0.5 else None)
        if not r.path:
            self._plan_to(r, (vx, vy, r.cruise_alt), final=(vx, vy, zs))
        r.look_at = (fx, fy)

    def _allocate_frontiers(self, t: float) -> None:
        explorers = [r for r in self.drones if r.mode == EXPLORE]
        if not explorers or not self.frontiers:
            return
        fr = self.frontiers
        fxy = np.array([self.geom.cell_center(f.ix, f.iy) for f in fr])
        gain = np.array([f.gain for f in fr], dtype=float)
        reps = int(np.ceil(len(explorers) / len(fr)))
        fxy_all = np.tile(fxy, (reps, 1))
        gain_all = np.tile(gain, reps)
        dup_penalty = np.repeat(np.arange(reps) * 60.0, len(fr))

        cost = np.zeros((len(explorers), len(fxy_all)))
        for k, r in enumerate(explorers):
            d = np.hypot(fxy_all[:, 0] - r.pos[0], fxy_all[:, 1] - r.pos[1])
            home = np.hypot(fxy_all[:, 0] - r.pad[0], fxy_all[:, 1] - r.pad[1])
            c = d - 4.0 * np.sqrt(gain_all) + dup_penalty + home * (1 - r.soc) * 0.6
            if r.frontier is not None:
                cur = self.geom.cell_center(*r.frontier)
                stick = np.hypot(fxy_all[:, 0] - cur[0], fxy_all[:, 1] - cur[1]) < 6.0
                c = c - 20.0 * stick
            cost[k] = c
        rows, cols = linear_sum_assignment(cost)
        for k, j in zip(rows, cols):
            r = explorers[k]
            fx, fy = float(fxy_all[j, 0]), float(fxy_all[j, 1])
            if r.frontier is not None and r.target is not None:
                cur = self.geom.cell_center(*r.frontier)
                if np.hypot(fx - cur[0], fy - cur[1]) <= 6.0:
                    continue  # keep current assignment
            cell = tuple(int(v) for v in self.geom.cell_of(fx, fy))
            plan = self._vantage(r, *cell)
            if plan is None:
                continue
            self._fly_scan(r, plan)
            r.frontier = cell

    def _blocked(self, alt: float) -> np.ndarray:
        if alt not in self._blocked_cache:
            self._blocked_cache[alt] = blocked_mask(self.map, alt)
        return self._blocked_cache[alt]

    def _plan_to(self, r: DroneRecord, goal, final=None, alt: float | None = None) -> None:
        r.look_at = None
        alt = r.cruise_alt if alt is None else float(alt)
        blocked = self._blocked(alt)
        start = tuple(int(v) for v in self.geom.cell_of(r.pos[0], r.pos[1]))
        end = tuple(int(v) for v in self.geom.cell_of(goal[0], goal[1]))
        cells = astar(blocked, start, end)
        if cells is None:
            r.path, r.target = [], goal
            return
        pts = [tuple(float(v) for v in self.geom.cell_center(*c)) + (alt,) for c in cells[1:]]
        goal_free = not blocked[end]
        if pts and goal_free:
            pts[-1] = (goal[0], goal[1], alt)
        elif not pts:
            pts = [(goal[0], goal[1], alt)] if goal_free else [
                tuple(float(v) for v in self.geom.cell_center(*cells[-1])) + (alt,)]
        if not goal_free:
            goal = (pts[-1][0], pts[-1][1], goal[2])
            if final is not None:
                final = (goal[0], goal[1], final[2])
        if final is not None:
            pts.append(tuple(float(v) for v in final))
        # Change altitude in place before moving horizontally.
        if r.pos[2] < alt - 3.0:
            pts.insert(0, (float(r.pos[0]), float(r.pos[1]), alt))
        elif r.pos[2] > alt + 3.0:
            if blocked[start]:
                r.path, r.target = [], None  # can't descend here; caller falls back to cruise
                return
            pts.insert(0, (float(r.pos[0]), float(r.pos[1]), alt))
        r.path = pts
        r.target = goal

    def _check_paths(self) -> None:
        """Replan any path that now crosses structure discovered since it was planned."""
        for r in self.drones:
            if r.mode not in (EXPLORE, INVESTIGATE, RTB) or not r.path or r.target is None:
                continue
            prev = tuple(int(v) for v in self.geom.cell_of(r.pos[0], r.pos[1]))
            ok = True
            for (x, y, z) in r.path:
                blocked = self._blocked(round(z, 1))
                cur = tuple(int(v) for v in self.geom.cell_of(x, y))
                if not line_clear(blocked, prev, cur) or blocked[cur]:
                    ok = False
                    break
                prev = cur
            if ok:
                continue
            if r.mode == EXPLORE and r.frontier is not None:
                plan = self._vantage(r, *r.frontier)
                if plan is not None:
                    self._fly_scan(r, plan)
                    continue
            final = r.path[-1] if r.path[-1][2] < r.cruise_alt - 1 else None
            look_at = r.look_at
            self._plan_to(r, r.target, final=final)
            r.look_at = look_at

    def _separation(self) -> None:
        air = [r for r in self.drones if r.mode not in (IDLE, CHARGING, CRASHED) and not r.grounded]
        for r in self.drones:
            r.holding = False
        for a in range(len(air)):
            for b in range(a + 1, len(air)):
                ra, rb = air[a], air[b]
                dz = abs(ra.pos[2] - rb.pos[2])
                dh = np.hypot(*(ra.pos[:2] - rb.pos[:2]))
                if dz < SEPARATION_V and dh < SEPARATION_H:
                    closing = np.dot(rb.pos[:2] - ra.pos[:2], rb.vel[:2] - ra.vel[:2]) < 0
                    if closing:
                        (rb if rb.id > ra.id else ra).holding = True

    # ---------------------------------------------------------------- downlink
    def _emit(self, t: float) -> list[tuple[int, Command]]:
        out = []
        for r in self.drones:
            if r.mode == CRASHED:
                continue
            if r.mode in (IDLE, CHARGING):
                desired = ("idle", (), None, None)
            elif r.mode == LANDING:
                desired = ("land", (), r.pad, None)
            elif r.holding:
                desired = ("hold", (), None, None)
            elif r.path:
                desired = ("path", tuple(r.path), None, r.look_at)
            else:
                desired = ("hold", (), None, None)
            if desired != r.sent or t - r.sent_t > RESEND_PERIOD:
                self.seq += 1
                out.append((r.id, Command(self.seq, desired[0], list(desired[1]), desired[2], desired[3])))
                r.sent, r.sent_t = desired, t
        return out

    # ----------------------------------------------------------------- helpers
    def _takeoff(self, r: DroneRecord, t: float) -> None:
        self._set_mode(r, TAKEOFF, t)
        r.path = [(r.pad[0], r.pad[1], r.cruise_alt)]
        r.target = r.path[0]
        r.look_at = None

    def _go_home(self, r: DroneRecord, t: float) -> None:
        self._release_candidate(r)
        self._set_mode(r, RTB, t)
        self._plan_to(r, (r.pad[0], r.pad[1], r.cruise_alt))

    def _release_candidate(self, r: DroneRecord) -> None:
        if r.candidate is not None:
            c = self.candidates[r.candidate]
            if c.assigned == r.id:
                c.assigned = None
            r.candidate = None

    def _set_mode(self, r: DroneRecord, mode: str, t: float) -> None:
        r.mode = mode
        r.mode_since = t
        if mode != EXPLORE:
            r.frontier = None

    def _event(self, t: float, text: str, level: str) -> None:
        self.events.append({"t": round(t, 1), "text": text, "level": level})
