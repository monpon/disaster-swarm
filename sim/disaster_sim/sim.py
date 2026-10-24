"""Simulation: drones (physics + onboard autopilot + sensors) talking to the central master."""
from __future__ import annotations

import numpy as np

from .autopilot import Autopilot
from .comms import Link
from .config import SimConfig
from .control import FlightController
from .mapping import OBSTACLE, FacadeMap, OccupancyGrid, ScanModel
from .master import MasterController
from .physics import F_MAX, QuadrotorFleet
from .sensors import Camera
from .world import generate_world

GUST_TAU = 4.0
SHARED_STAMP = -2  # stamp for cells received from the master, so they are never echoed back


class Simulation:
    def __init__(self, cfg: SimConfig | None = None):
        self.reset(cfg or SimConfig())

    def reset(self, cfg: SimConfig | None = None) -> None:
        if cfg is not None:
            self.cfg = cfg
        cfg = self.cfg
        self.rng = np.random.default_rng(cfg.seed + 1000)
        self.world = generate_world(cfg)
        n = cfg.n_drones
        self.pads = self.world.pad_positions(n)
        start = np.column_stack([self.pads, self.world.height_at(self.pads[:, 0], self.pads[:, 1])])
        self.fleet = QuadrotorFleet(n, start, yaw=np.full(n, np.pi / 4), battery_wh=cfg.battery_wh)
        self.fc = FlightController(n, max_speed=cfg.max_speed)
        self.fc.pos_sp[:] = start
        self.fc.yaw_sp[:] = np.pi / 4
        self.local_maps = [OccupancyGrid(self.world.n) for _ in range(n)]
        self.local_facades = [FacadeMap(len(self.world.facades)) for _ in range(n)]
        pitch = np.deg2rad(cfg.cam_pitch_deg)
        self.autopilots = [Autopilot(i, self.local_maps[i], self.world.cell_of, pitch, cfg.max_speed)
                           for i in range(n)]
        self.camera = Camera(self.world, self.rng, cfg)
        self.scan_model = ScanModel(cfg.scan_near, cfg.cam_range, cfg.proper_scan_range)
        # What each camera is looking at right now: per cell, the closest viewer (id + 1, 0 = none)
        # and that view's scan quality (0-255). Streamed to the viewer for FOV footprints.
        self.view_owner = np.zeros(self.world.n ** 2, dtype=np.uint8)
        self.view_quality = np.zeros(self.world.n ** 2, dtype=np.uint8)
        self.patch_owner = np.zeros(len(self.world.facades), dtype=np.uint8)
        self.patch_view_q = np.zeros(len(self.world.facades), dtype=np.uint8)
        self.master = MasterController(cfg, self.pads, self.world)
        self.uplinks = [Link(cfg.link_latency, cfg.link_dropout, self.rng) for _ in range(n)]
        self.downlinks = [Link(cfg.link_latency, cfg.link_dropout, self.rng) for _ in range(n)]
        self.pending_detections: list[list[tuple]] = [[] for _ in range(n)]
        self.shared_tick = -1
        self.cam_on = np.zeros(n, dtype=bool)
        self.agl = np.zeros(n)

        self.dt = 1.0 / cfg.physics_hz
        self.t = 0.0
        self.tick = 0
        self.gust = np.zeros(3)
        ang = np.deg2rad(cfg.wind_dir_deg)
        self.wind_mean = cfg.wind_speed * np.array([np.cos(ang), np.sin(ang), 0.0])
        self.wind = self.wind_mean.copy()
        self.history: list[tuple[float, float, int]] = []  # (t, coverage, confirmed)

    def _every(self, hz: int) -> bool:
        return self.tick % max(1, round(self.cfg.physics_hz / hz)) == 0

    def step(self) -> None:
        cfg, dt = self.cfg, self.dt

        # Wind gusts: Ornstein-Uhlenbeck process.
        sigma = cfg.gust_strength
        self.gust += (-self.gust / GUST_TAU) * dt + sigma * np.sqrt(2 * dt / GUST_TAU) * self.rng.normal(size=3) * np.array([1, 1, 0.3])
        self.wind = self.wind_mean + self.gust

        if self._every(cfg.master_hz):
            for cmd_drone, cmd in self.master.step(self.t):
                self.downlinks[cmd_drone].send(self.t, cmd)
            self._share_map()
        for i, link in enumerate(self.downlinks):
            for msg in link.receive(self.t):
                if isinstance(msg, dict):  # merged-map update from the master
                    self.local_maps[i].apply_cells(*msg["cells"], tick=SHARED_STAMP)
                else:
                    self.autopilots[i].on_command(msg)

        if self._every(cfg.autopilot_hz):
            for ap in self.autopilots:
                ap.update(self.fleet, self.fc, 1.0 / cfg.autopilot_hz)
            self._charge(1.0 / cfg.autopilot_hz)

        if self._every(cfg.sensor_hz):
            self._sense()

        if self._every(cfg.uplink_hz):
            self._uplink()
        for link in self.uplinks:
            for pkt in link.receive(self.t):
                self.master.ingest(pkt, self.t)

        self.fc.update(self.fleet, dt)
        self.fleet.step(dt, self.wind, self.world)

        self.tick += 1
        self.t += dt
        if self._every(1):
            self.history.append((round(self.t, 1), self.scanned_fraction(), self.confirmed_count()))

    def advance(self, seconds: float) -> None:
        for _ in range(int(round(seconds / self.dt))):
            self.step()

    def _share_map(self) -> None:
        """Broadcast obstacle cells the master learned since the last share to every drone."""
        idx, s, h, sg, q = self.master.map.cells_since(self.shared_tick)
        self.shared_tick = self.master.tick
        keep = s == OBSTACLE
        if not keep.any():
            return
        payload = {"cells": (idx[keep], s[keep], h[keep], sg[keep], q[keep])}
        for link in self.downlinks:
            link.send(self.t, payload, size=9 * int(keep.sum()))

    def _sense(self) -> None:
        f = self.fleet
        active = ~f.crashed & ~f.grounded
        yaw = np.arctan2(f.rot[:, 1, 0], f.rot[:, 0, 0])
        pitch = np.array([ap.gimbal for ap in self.autopilots])
        agl, cam_on, views, dets = self.camera.sense(f.pos, yaw, pitch, active)
        self.cam_on = cam_on
        self.agl = agl
        for arr in (self.view_owner, self.view_quality, self.patch_owner, self.patch_view_q):
            arr[:] = 0
        sm = self.scan_model
        for i, v in enumerate(views):
            if v is None:
                continue
            self.local_maps[i].observe(v.cells, v.cell_dist, self.world.heightmap, self.tick, self.t, sm, self.rng)
            self.local_facades[i].observe(v.patches, v.patch_dist, v.patch_facing, self.tick, self.t, sm, self.rng)
            q = np.rint(sm.quality(v.cell_dist) * 255).astype(np.uint8)
            closer = q >= self.view_quality[v.cells]
            self.view_owner[v.cells[closer]] = i + 1
            self.view_quality[v.cells[closer]] = q[closer]
            q = np.rint(sm.quality(v.patch_dist) * (0.35 + 0.65 * v.patch_facing) * 255).astype(np.uint8)
            closer = q >= self.patch_view_q[v.patches]
            self.patch_owner[v.patches[closer]] = i + 1
            self.patch_view_q[v.patches[closer]] = q[closer]
        for d in dets:
            self.pending_detections[d.drone].append((d.x, d.y, d.range))

    def _uplink(self) -> None:
        f = self.fleet
        for i in range(f.n):
            if f.crashed[i] and self.master.drones[i].crashed:
                continue
            acked = int(self.master.acked_tick[i])
            cells = self.local_maps[i].cells_since(acked)
            idx = cells[0]
            seen_idx, seen_t = self.local_maps[i].seen_since(acked)
            facade = self.local_facades[i].since(acked)
            facade_seen = self.local_facades[i].seen_since(acked)
            pkt = {
                "drone": i, "t": self.t, "tick": self.tick,
                "pos": f.pos[i].copy(), "vel": f.vel[i].copy(), "soc": float(f.soc[i]),
                "grounded": bool(f.grounded[i]), "crashed": bool(f.crashed[i]),
                "cells": cells, "seen": (seen_idx, seen_t),
                "facade": facade, "facade_seen": facade_seen,
                "detections": self.pending_detections[i],
            }
            self.pending_detections[i] = []
            # Re-sightings are sent as a compact bitmap + timestamp, not per-cell records.
            size = 64 + 13 * len(idx) + 10 * len(facade[0]) + 12 * len(pkt["detections"]) + (self.world.n ** 2) // 8 * bool(len(seen_idx))
            self.uplinks[i].send(self.t, pkt, size=size)

    def _charge(self, dt: float) -> None:
        f = self.fleet
        on_pad = f.grounded & ~f.crashed & (np.hypot(f.pos[:, 0] - self.pads[:, 0], f.pos[:, 1] - self.pads[:, 1]) < 2.0)
        rate = f.battery_cap_j / self.cfg.charge_time_s
        f.battery_j = np.where(on_pad, np.minimum(f.battery_j + rate * dt, f.battery_cap_j), f.battery_j)

    # ----------------------------------------------------------------- metrics
    def scanned_fraction(self) -> float:
        return self.master.map.scanned(self.scan_model.threshold)

    def walls_scanned(self) -> float:
        return self.master.facades.scanned(self.scan_model.threshold)

    def confirmed_count(self) -> int:
        return sum(c.confirmed for c in self.master.candidates)

    def found_survivor_ids(self) -> list[int]:
        """Ground-truth survivors matched by a confirmed candidate (for display/scoring)."""
        out = []
        for c in self.master.candidates:
            if not c.confirmed:
                continue
            best = min(self.world.survivors, key=lambda s: np.hypot(s.x - c.x, s.y - c.y), default=None)
            if best is not None and np.hypot(best.x - c.x, best.y - c.y) < 5.0:
                out.append(best.id)
        return sorted(set(out))

    def metrics(self) -> dict:
        f = self.fleet
        up = sum(l.bytes for l in self.uplinks)
        sent = sum(l.sent for l in self.uplinks) + sum(l.sent for l in self.downlinks)
        dropped = sum(l.dropped for l in self.uplinks) + sum(l.dropped for l in self.downlinks)
        return {
            "t": round(self.t, 2),
            "coverage": round(self.scanned_fraction(), 4),
            "seen_frac": round(self.master.map.coverage(), 4),
            "walls": round(self.walls_scanned(), 4),
            "scan_threshold": round(self.scan_model.threshold, 3),
            "found": len(self.found_survivor_ids()),
            "survivors": len(self.world.survivors),
            "candidates": len(self.master.candidates),
            "airborne": int((~f.grounded & ~f.crashed).sum()),
            "crashed": int(f.crashed.sum()),
            "avg_soc": round(float(f.soc.mean()), 3),
            "uplink_kb": round(up / 1024, 1),
            "packet_loss": round(dropped / max(sent, 1), 3),
            "wind": [round(float(v), 2) for v in self.wind[:2]],
            "mission_done": self.master.mission_done,
            **self._freshness(),
        }

    def _freshness(self, stale_after: float = 120.0) -> dict:
        seen = self.master.map.seen
        known = seen >= 0
        if not known.any():
            return {"mean_age": 0.0, "stale_frac": 0.0}
        age = self.t - seen[known]
        return {"mean_age": round(float(age.mean()), 1), "stale_frac": round(float((age > stale_after).mean()), 3)}

    def drone_states(self) -> list[dict]:
        f = self.fleet
        out = []
        for i in range(f.n):
            r = self.master.drones[i]
            ap = self.autopilots[i]
            out.append({
                "id": i,
                "p": [round(float(v), 3) for v in f.pos[i]],
                "q": [round(float(v), 4) for v in f.quat[i]],
                "v": [round(float(v), 2) for v in f.vel[i]],
                "soc": round(float(f.soc[i]), 3),
                "power": round(float(f.power[i]), 1),
                "throttle": round(float(f.motor[i].mean() / F_MAX), 3),
                "mode": r.mode,
                "avoiding": ap.avoiding,
                "holding": r.holding,
                "crashed": bool(f.crashed[i]),
                "grounded": bool(f.grounded[i]),
                "cam_on": bool(self.cam_on[i]),
                "gimbal": round(float(np.rad2deg(ap.gimbal)), 1),
                "scanning": ap.scanning,
                "agl": round(float(self.agl[i]), 2),
                "cruise_alt": r.cruise_alt,
                "target": None if r.target is None else [round(v, 2) for v in r.target],
                "path": [[round(v, 2) for v in p] for p in ap.cmd.path[ap.wp:]] if ap.cmd.kind == "path" else [],
                "link_age": round(self.t - r.last_seen, 2) if r.last_seen >= 0 else None,
            })
        return out
