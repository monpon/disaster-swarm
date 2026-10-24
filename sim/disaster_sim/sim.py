"""Simulation: drones (physics, stock flight controller, camera, ESP32) <-> ESP mesh <->
central node (perception, planning, piloting)."""
from __future__ import annotations

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
FRAME_BUFFER = 160  # frames a drone can hold onboard while its link is down (~40 s)


class Simulation:
    def __init__(self, cfg: SimConfig | None = None):
        self.reset(cfg or SimConfig())

    def reset(self, cfg: SimConfig | None = None) -> None:
        if cfg is not None:
            self.cfg = cfg
        cfg = self.cfg
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
        self.master = MasterController(cfg, self.b.vox.shape, (self.b.x0, self.b.y0, self.b.x1, self.b.y1, self.b.top),
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

    def _every(self, hz: float) -> bool:
        return self.tick % max(1, round(self.cfg.physics_hz / hz)) == 0

    def step(self) -> None:
        cfg, dt, f = self.cfg, self.dt, self.fleet
        self.gust += (-self.gust / GUST_TAU) * dt + cfg.gust_strength * np.sqrt(2 * dt / GUST_TAU) \
            * self.rng.normal(size=3) * np.array([1, 1, 0.3])
        wind = np.where(self.b.inside_building(f.pos)[:, None], 0.0, (self.wind_mean + self.gust)[None, :])

        if self._every(cfg.master_hz):
            self.radio.update(f.pos, ~f.crashed)
            self.master.step(self.t)
        self.radio.tick(dt)

        for direction, drone, msg in self.radio.receive(self.t):
            if direction == "down":
                self.esp.on_command(msg, self.t)
            elif isinstance(msg, ImuPacket):
                self.master.on_telemetry(msg, self.t)
            else:
                self.master.on_frame(msg, self.t)
                self.last_frames[drone] = msg

        if self._every(cfg.telemetry_hz):
            for pkt in self.esp.packets(f, self.t, dt, self.radio.routes):
                self.radio.send_up(self.t, pkt.drone, pkt, pkt.nbytes)
            for drone, cmd in self.master.control(self.t):
                self.radio.send_down(self.t, drone, cmd, cmd.nbytes)

        if self._every(cfg.autopilot_hz):
            self.esp.apply(f, self.fc, self.t, 1.0 / cfg.autopilot_hz)
            self._charge(1.0 / cfg.autopilot_hz)

        if self._every(cfg.camera_hz):
            for i in range(f.n):
                if f.crashed[i] or f.grounded[i]:
                    continue
                q = self.backlog[i]
                q.append(self.camera.capture(i, self.t, f.pos[i], f.rot[i], f.omega[i]))
                if len(q) > FRAME_BUFFER:
                    q.popleft()  # onboard buffer full: oldest frame is lost
                    self.radio.frame_stats[i, 1] += 1
            for i, q in enumerate(self.backlog):  # send buffered frames, oldest first
                while q and self.radio.send_frame(self.t, i, q[0], q[0].nbytes):
                    q.popleft()

        self.fc.vel_meas = self.esp.flow_velocity(f)
        self.fc.update(f, dt)
        f.step(dt, wind, self.b)
        self.esp.sample(f, dt)
        self.tick += 1
        self.t += dt
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
            interior = self.master.interior
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
