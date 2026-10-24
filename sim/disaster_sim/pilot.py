"""Central-node pilot: closes each drone's position loop over the radio.

The drones only fly velocity sticks, so the master turns its plans (waypoint paths, holds,
landings) into stick commands at a fixed rate, using its own VIO estimate of each drone's
pose. Estimate drift, radio latency and the drone's optical-flow drift all show up as
tracking error, which is what a real centrally-piloted swarm has to live with.
"""
from __future__ import annotations

import numpy as np

from .packets import StickCommand

WAYPOINT_RADIUS = 0.7
KP_POS = 1.0
KP_Z = 1.2
KP_YAW = 2.0
MAX_YAW_RATE = 1.2
MAX_CLIMB, MAX_SINK = 2.0, 1.5
HOLD_SWEEP = 0.9  # rad: a held drone looks this far to each side of its heading, then back (never a full turn)
HOLD_PERIOD = 12.0  # s per back-and-forth look


class Pilot:
    def __init__(self, n: int, max_speed: float):
        self.max_speed = max_speed
        self.wp = [0] * n
        self.key: list = [None] * n
        self.hold: list = [None] * n
        self.hold_yaw: list = [0.0] * n
        self.hold_n = [0] * n
        self.seq = 0

    def target_index(self, i: int) -> int:
        return self.wp[i]

    def command(self, r, idle: bool, landing: bool) -> StickCommand:
        """Stick command for drone record `r` (fields: id, pos, vel, yaw, path, yaws, speed,
        pad, grounded)."""
        self.seq += 1
        i = r.id
        if idle:
            self.hold[i] = None
            return StickCommand(i, self.seq, "disarm")
        p = r.pos
        yaw_t = None
        speed = r.speed or self.max_speed
        if landing:
            d = np.array(r.pad) - p[:2]
            if np.hypot(*d) < 0.8 or r.grounded:
                return StickCommand(i, self.seq, "land")
            target = np.array([r.pad[0], r.pad[1], p[2]])
            speed = min(speed, 2.0)
        elif r.path:
            key = (id(r.path), len(r.path))
            if key != self.key[i]:
                self.key[i], self.wp[i] = key, 0
            path = r.path
            while self.wp[i] < len(path) - 1 and np.linalg.norm(np.asarray(path[self.wp[i]]) - p) < WAYPOINT_RADIUS:
                self.wp[i] += 1
            w = self.wp[i]
            target = np.asarray(path[w], dtype=float)
            if w + 1 < len(path):  # slow down before sharp turns
                a, b = target - p, np.asarray(path[w + 1], dtype=float) - target
                na, nb = np.linalg.norm(a), np.linalg.norm(b)
                if na > 1e-3 and nb > 1e-3 and np.dot(a, b) / (na * nb) < 0.7:
                    speed = min(speed, max(0.6, 1.0 * na))
            if r.yaws:
                yaw_t = r.yaws[min(w, len(r.yaws) - 1)]
            self.hold[i] = None
        else:
            if self.hold[i] is None:
                self.hold[i] = p.copy()
                self.hold_yaw[i], self.hold_n[i] = r.yaw, 0
            target = self.hold[i]
            self.hold_n[i] += 1
            ph = 2 * np.pi * self.hold_n[i] * 0.05 / HOLD_PERIOD   # control runs at 20 Hz
            yaw_t = self.hold_yaw[i] + HOLD_SWEEP * np.sin(ph)

        err = target - p
        v = KP_POS * err[:2]
        n = np.hypot(*v)
        if n > speed:
            v *= speed / n
        vz = float(np.clip(KP_Z * err[2], -MAX_SINK, MAX_CLIMB))
        if yaw_t is None and np.hypot(*err[:2]) > 1.5:
            yaw_t = float(np.arctan2(err[1], err[0]))
        yaw_rate = 0.0
        if yaw_t is not None:
            e = (yaw_t - r.yaw + np.pi) % (2 * np.pi) - np.pi
            yaw_rate = float(np.clip(KP_YAW * e, -MAX_YAW_RATE, MAX_YAW_RATE))
        c, s = np.cos(r.yaw), np.sin(r.yaw)
        return StickCommand(i, self.seq, "fly", float(c * v[0] + s * v[1]), float(-s * v[0] + c * v[1]),
                            vz, yaw_rate)
