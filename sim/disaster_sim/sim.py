"""Simulation: drones (physics, stock flight controller, camera, ESP32) <-> ESP mesh <->
central node (perception, planning, piloting)."""
from __future__ import annotations

import time
from collections import deque

import numpy as np

from . import materials as M
from .building import generate_building
from .camera import RGBDCamera
from .config import SimConfig
from .control import FlightController
from .esp import EspFleet
from .master import MasterController
from .packets import ImuPacket
from .physics import F_MAX, QuadrotorFleet
from .radio import Radio

GUST_TAU = 4.0
NAV_BYTES = 3000  # a thumbnail: what a frame shrinks to when the link cannot carry the full one
FRAME_BUFFER = 160  # frames a drone can hold onboard while its link is down (~40 s)


class Simulation:
    def __init__(self, cfg: SimConfig | None = None):
        self.reset(cfg or SimConfig())

    def reset(self, cfg: SimConfig | None = None) -> None:
        if cfg is not None:
            self.cfg = cfg
        cfg = self.cfg
        if hasattr(self, "master"):
            self.master.smoother.close()
            self.master.surface.close()
        self.rng = np.random.default_rng(cfg.seed + 1000)
        self.b = generate_building(cfg)
        n = cfg.n_drones
        self.pads = self.b.pads
        start = np.column_stack([self.pads, np.ones(n)])
        self.fleet = QuadrotorFleet(n, start, yaw=np.zeros(n), battery_wh=cfg.battery_wh)
        self.fc = FlightController(n, max_speed=cfg.max_speed)
        self.esp = EspFleet(n, self.rng)
        self.camera = RGBDCamera(self.b, cfg, self.rng)
        self.radio = Radio(self.b, cfg, self.rng)
        self.master = MasterController(cfg, self.b.vox.shape,
                                       (self.b.x0, self.b.y0, self.b.x1, self.b.y1, self.b.top) if cfg.known_outline else None,
                                       self.pads, self.b.base, np.random.default_rng(cfg.seed + 2000))
        self.last_frames: list = [None] * n  # most recent frame the master received per drone
        self.backlog = [deque() for _ in range(n)]  # frames waiting for radio capacity

        self.dt = 1.0 / cfg.physics_hz
        self.t = 0.0
        self.tick = 0
        self.gust = np.zeros(3)
        ang = np.deg2rad(cfg.wind_dir_deg)
        self.wind_mean = cfg.wind_speed * np.array([np.cos(ang), np.sin(ang), 0.0])
        self.history: list[tuple] = []  # (t, explored, scanned, survivors)
        self._truth_cache = None
        self.map_error_cache: dict = {}
        self.cam_tick = 0
        self.prof: dict[str, float] = {}  # smoothed ms per call of each stage
        self._err_rng = np.random.default_rng(cfg.seed + 3000)

    def _tick(self, name: str, t0: float) -> None:
        d = (time.perf_counter() - t0) * 1000
        self.prof[name] = self.prof.get(name, d) * 0.95 + d * 0.05

    def _should_capture(self, i: int) -> bool:
        """The ESP's camera policy: full rate normally; one frame a second for a relay, or a
        drone holding still (it would only photograph the same view); off on command."""
        mode = self.esp.cam_mode[i]
        if mode == "off":
            return False
        if mode == "nav" or self.esp.failsafe[i] or self.esp.link_hold[i]:
            return self.cam_tick % 4 == i % 4
        return True

    def _every(self, hz: float) -> bool:
        return self.tick % max(1, round(self.cfg.physics_hz / hz)) == 0

    def step(self) -> None:
        cfg, dt, f = self.cfg, self.dt, self.fleet
        self.gust += (-self.gust / GUST_TAU) * dt + cfg.gust_strength * np.sqrt(2 * dt / GUST_TAU) \
            * self.rng.normal(size=3) * np.array([1, 1, 0.3])
        wind = np.where(self.b.inside_building(f.pos)[:, None], 0.0, (self.wind_mean + self.gust)[None, :])

        if self._every(cfg.master_hz):
            t0 = time.perf_counter()
            self.radio.update(f.pos, ~f.crashed)
            self.master.step(self.t)
            self._tick("master_step", t0)
        self.radio.tick(dt)

        for direction, drone, msg in self.radio.receive(self.t):
            if direction == "down":
                self.esp.on_command(msg, self.t)
            elif isinstance(msg, ImuPacket):
                self.master.on_telemetry(msg, self.t)
            else:
                t0 = time.perf_counter()
                self.master.on_frame(msg, self.t)
                self._tick("on_frame", t0)
                self.last_frames[drone] = msg

        if self._every(cfg.telemetry_hz):
            for pkt in self.esp.packets(f, self.t, dt, self.radio, [len(q) for q in self.backlog]):
                self.radio.send_up(self.t, pkt.drone, pkt, pkt.nbytes)
            t0 = time.perf_counter()
            cmds = self.master.control(self.t)
            self._tick("control", t0)
            for drone, cmd in cmds:
                self.radio.send_down(self.t, drone, cmd, cmd.nbytes)

        if self._every(cfg.autopilot_hz):
            self.esp.apply(f, self.fc, self.t, 1.0 / cfg.autopilot_hz, self.radio)
            self._charge(1.0 / cfg.autopilot_hz)

        if self._every(cfg.camera_hz):
            t0 = time.perf_counter()
            self.cam_tick += 1
            ids = [i for i in range(f.n) if not (f.crashed[i] or f.grounded[i]) and self._should_capture(i)]
            frames = self.camera.capture_many([(i, f.pos[i], f.rot[i], f.omega[i]) for i in ids], self.t)
            self._tick("camera", t0)
            for i, pkt in zip(ids, frames):
                q = self.backlog[i]
                q.append(pkt)
                if len(q) > FRAME_BUFFER:
                    q.popleft()  # onboard buffer full: oldest frame is lost
                    self.radio.frame_stats[i, 1] += 1
            for i, q in enumerate(self.backlog):  # send buffered frames, oldest first
                while q:
                    pk = q[0]
                    if self.radio.send_frame(self.t, i, pk, pk.nbytes):
                        q.popleft()
                    elif self.radio.send_frame(self.t, i, pk, NAV_BYTES):  # shrink it rather than let it wait
                        pk.thumb, pk.nbytes = True, NAV_BYTES
                        self.radio.stats["thumbs"] += 1
                        q.popleft()
                    else:
                        break

        self.fc.vel_meas = self.esp.flow_velocity(f)
        self.fc.update(f, dt)
        t0 = time.perf_counter()
        f.step(dt, wind, self.b)
        self._tick("physics", t0)
        self.esp.sample(f, dt)
        self.tick += 1
        self.t += dt
        if self._every(0.5):
            self.map_error_cache = self.map_error()
        if self._every(1):
            m = self.coverage()
            self.history.append((round(self.t, 1), m["explored"], m["scanned"], self.confirmed_count()))

    def advance(self, seconds: float) -> None:
        for _ in range(int(round(seconds / self.dt))):
            self.step()

    def _charge(self, dt: float) -> None:
        f = self.fleet
        on_pad = f.grounded & ~f.crashed & (np.hypot(f.pos[:, 0] - self.pads[:, 0], f.pos[:, 1] - self.pads[:, 1]) < 1.5)
        rate = f.battery_cap_j / self.cfg.charge_time_s
        f.battery_j = np.where(on_pad, np.minimum(f.battery_j + rate * dt, f.battery_cap_j), f.battery_j)

    # ----------------------------------------------------------------- metrics
    def _truth(self):
        """Ground-truth interior air and exposed interior surfaces (for scoring only)."""
        if self._truth_cache is None:
            from scipy import ndimage
            v = self.b.vox
            air = v == M.AIR
            b = self.b  # scored against the true building, whatever the master believes
            interior = np.zeros(v.shape, dtype=bool)
            interior[b.x0 + 1:b.x1 - 1, b.y0 + 1:b.y1 - 1, 1:b.top] = True
            reach = ndimage.binary_dilation(air, ndimage.generate_binary_structure(3, 1))
            surface = (v != M.AIR) & interior & reach
            self._truth_cache = ((air & interior).reshape(-1), surface.reshape(-1))
        return self._truth_cache

    def coverage(self) -> dict:
        air, surf = self._truth()
        m = self.master.map
        explored = float((m.free & air).sum() / max(air.sum(), 1))
        scanned = float(((m.quality >= m.q.threshold) & surf).sum() / max(surf.sum(), 1))
        return {"explored": round(explored, 4), "scanned": round(scanned, 4)}

    def map_error(self, n: int = 4000) -> dict:
        """Distance of map points to the true surface (scoring only; the master never sees it).
        Reported for the raw running-average cloud and for the smoothed one."""
        m = self.master.map
        if m.npts < 100:
            return {}
        ids = self._err_rng.choice(m.npts, min(n, m.npts), replace=False)
        ids = ids[~m.hidden(ids)]
        if len(ids) < 50:
            return {}
        v = self.b.vox
        solid = v != M.AIR
        sh = np.array(v.shape)
        out = {}
        for name, pos in (("raw", m.praw[ids]), ("smooth", m.spos[ids])):
            c = np.floor(pos).astype(int)
            offs = np.array([(a, b, d) for a in (-1, 0, 1) for b in (-1, 0, 1) for d in (-1, 0, 1)])
            cells = c[:, None, :] + offs[None]
            ok = ((cells >= 0) & (cells < sh)).all(-1)
            cc = np.clip(cells, 0, sh - 1)
            sol = solid[cc[..., 0], cc[..., 1], cc[..., 2]] & ok
            air = ~solid[cc[..., 0], cc[..., 1], cc[..., 2]] & ok
            lo, hi = cells.astype(float), cells + 1.0
            gap = np.maximum(np.maximum(lo - pos[:, None], pos[:, None] - hi), 0.0)
            dist = np.linalg.norm(gap, axis=-1)
            inside = solid[np.clip(c[:, 0], 0, sh[0] - 1), np.clip(c[:, 1], 0, sh[1] - 1), np.clip(c[:, 2], 0, sh[2] - 1)]
            # in solid: distance to the nearest air cell; in air: to the nearest solid cell
            d = np.where(inside, np.where(air, dist, 9.0).min(1), np.where(sol, dist, 9.0).min(1))
            d = np.minimum(d, 1.0)
            out[name] = (round(float(np.sqrt(np.mean(d ** 2))), 3), round(float((d < 0.10).mean()), 3))
        return {"rms_raw": out["raw"][0], "ok_raw": out["raw"][1], "rms_smooth": out["smooth"][0],
                "ok_smooth": out["smooth"][1]}

    def verified_fraction(self) -> float:
        air, surf = self._truth()
        m = self.master.map
        return round(float(((m.npass >= 2) & surf).sum() / max(surf.sum(), 1)), 4)

    def confirmed_count(self) -> int:
        return sum(c.confirmed for c in self.master.candidates)

    def found_survivor_ids(self) -> list[int]:
        out = set()
        for c in self.master.candidates:
            if not c.confirmed:
                continue
            for s in self.b.survivors:
                if np.linalg.norm(np.array([s.x + 0.5, s.y + 0.5, s.z + 0.5]) - c.pos) < 2.5:
                    out.add(s.id)
        return sorted(out)

    def metrics(self) -> dict:
        f = self.fleet
        cov = self.coverage()
        return {
            "t": round(self.t, 2),
            "phase": self.master.phase,
            **cov,
            "entries": len(self.master.entries),
            "entries_usable": sum(not e.blocked for e in self.master.entries),
            "found": len(self.found_survivor_ids()),
            "survivors": len(self.b.survivors),
            "candidates": len(self.master.candidates),
            "airborne": int((~f.grounded & ~f.crashed).sum()),
            "crashed": int(f.crashed.sum()),
            "relays": sum(r.mode == "relay" for r in self.master.drones),
            "avg_soc": round(float(f.soc.mean()), 3),
            "frames_ok": int(self.radio.frame_stats[:, 0].sum()),
            "frames_dropped": int(self.radio.frame_stats[:, 1].sum()),
            "radio_mb": round(self.radio.stats["bytes"] / 1e6, 2),
            "mapped_voxels": int(self.master.map.occupied.sum()),
            "wind": [round(float(v), 2) for v in (self.wind_mean + self.gust)[:2]],
            "verified": self.verified_fraction(),
            "align_ok": round(self.master.map.align_ok / max(self.master.map.align_n, 1), 3),
            "align_mm": round(1000 * float(np.mean(self.master.align_dp or [0.0])), 0),
            "points": int(self.master.map.npts),
            "prof": {k: round(v, 2) for k, v in self.prof.items()},
            "lost_events": int(self.master.lost_events),
            "slots": len(self.master.slots),
            "thumbs": int(self.radio.stats["thumbs"]),
            "ext_cov": round(float(self.master.ext_cov), 3),
            "smoother": self.master.smoother.backend,
            "mesh": {"backend": self.master.surface.backend,
                     "tris": int(self.master.surface.tris) if self.master.surface.available else 0,
                     "chunks": len(self.master.surface.chunks) if self.master.surface.available else 0,
                     "ms": round(self.master.surface.last_ms, 1) if self.master.surface.available else 0.0},
            "smooth_ms": round(self.master.smoother.last_ms, 1),
            **self.map_error_cache,
            "drift": round(float(np.mean([self.master.vio.drift(i) for i in range(f.n)
                                          if not f.grounded[i] and not f.crashed[i]] or [0.0])), 2),
        }

    def radio_mesh(self) -> list[list]:
        """Every usable peer-to-peer link: [node a, node b, Mbps] with node -1 = base station."""
        f = self.fleet
        up = np.r_[True, ~f.crashed & ~f.grounded]
        cap = self.radio.link_cap
        a, b = np.nonzero(np.triu(cap > 0, 1) & up[:, None] & up[None, :])
        return [[int(i) - 1, int(j) - 1, round(float(cap[i, j]) / 1e6, 1)] for i, j in zip(a, b)]

    def drone_states(self) -> list[dict]:
        f = self.fleet
        out = []
        for i in range(f.n):
            r = self.master.drones[i]
            wp = self.master.pilot.target_index(i)
            route = self.radio.routes[i]
            out.append({
                "id": i,
                "p": [round(float(v), 3) for v in f.pos[i]],
                "q": [round(float(v), 4) for v in f.quat[i]],
                "v": [round(float(v), 2) for v in f.vel[i]],
                "soc": round(float(f.soc[i]), 3),
                "power": round(float(f.power[i]), 1),
                "throttle": round(float(f.motor[i].mean() / F_MAX), 3),
                "mode": r.mode,
                "crashed": bool(f.crashed[i]),
                "grounded": bool(f.grounded[i]),
                "frozen": bool(self.esp.failsafe[i]),
                "holding": bool(self.esp.link_hold[i]),
                "snr": round(float(self.master.drones[i].parent_snr), 1),
                "slot": None if self.master.drones[i].slot is None else int(self.master.drones[i].slot["id"]),
                "landing_auto": bool(self.esp.auto_land[i]),
                # What the master believes (VIO estimate): where the map view draws it.
                "ep": [round(float(v), 3) for v in r.pos],
                "eq": [round(float(v), 4) for v in _yaw_corrected_quat(f.quat[i], self.master.vio.err_yaw[i])],
                "drift": round(self.master.vio.drift(i), 2),
                "link": round(route.capacity / 1e6, 2),
                "hops": route.hops,
                "route": [int(v) for v in route.path],
                "frames": [int(v) for v in self.radio.frame_stats[i]],
                "backlog": len(self.backlog[i]),
                "path": [[round(float(v), 2) for v in p] for p in r.path[wp:wp + 40]] if r.path else [],
                "serves": None if r.serves is None else int(r.serves),
            })
        return out


def _yaw_corrected_quat(q: np.ndarray, dyaw: float) -> np.ndarray:
    """Quaternion (w, x, y, z) rotated by dyaw about world z: the attitude the master
    believes the drone has when its VIO heading is off by dyaw."""
    c, s = np.cos(dyaw / 2), np.sin(dyaw / 2)
    w, x, y, z = q
    return np.array([c * w - s * z, c * x - s * y, c * y + s * x, c * z + s * w])
