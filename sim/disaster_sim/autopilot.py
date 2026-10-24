"""Onboard autopilot: executes master commands and keeps the drone clear of known terrain.

The autopilot only sees the drone's own local map (no ground truth). It turns
high-level commands into position setpoints for the flight controller.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .mapping import OBSTACLE, OccupancyGrid

WAYPOINT_RADIUS = 2.5
SAFETY_MARGIN = 4.0
LOOKAHEAD_S = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
SCAN_RATE = 0.35  # rad/s yaw sweep while holding, so the forward camera keeps looking around


@dataclass
class Command:
    seq: int
    kind: str  # idle | path | land | hold
    path: list[tuple[float, float, float]] = field(default_factory=list)
    pad: tuple[float, float] | None = None
    look_at: tuple[float, float] | None = None  # face this point at the final waypoint
    # Scan pass: from waypoint `scan_from` on, hold heading `face_yaw`, tilt the gimbal to
    # `gimbal_deg` below horizon and fly no faster than `scan_speed`.
    scan_from: int | None = None
    face_yaw: float | None = None
    gimbal_deg: float | None = None
    scan_speed: float | None = None


class Autopilot:
    def __init__(self, idx: int, local_map: OccupancyGrid, cell_of, default_pitch: float,
                 max_speed: float):
        self.i = idx
        self.default_pitch = default_pitch
        self.max_speed = max_speed
        self.gimbal = default_pitch  # radians below horizon
        self.scanning = False
        self.map = local_map
        self.cell_of = cell_of
        self.cmd = Command(0, "idle")
        self.wp = 0
        self.hold_point: np.ndarray | None = None
        self.avoiding = False

    def on_command(self, cmd: Command) -> None:
        if cmd.seq <= self.cmd.seq:
            return  # stale or duplicate (links can reorder)
        key = lambda c: (c.kind, c.path, c.pad, c.look_at, c.scan_from, c.face_yaw)
        changed = key(cmd) != key(self.cmd)
        self.cmd = cmd
        if changed:
            self.wp = 0
            self.hold_point = None

    def _required_alt(self, p: np.ndarray, v: np.ndarray) -> float:
        ahead = p[None, :2] + np.array(LOOKAHEAD_S)[:, None] * v[None, :2]
        around = p[None, :2] + np.array([[2.0, 0], [-2.0, 0], [0, 2.0], [0, -2.0]])
        pts = np.vstack([ahead, around])
        ix, iy = self.cell_of(pts[:, 0], pts[:, 1])
        # Obstacle heights padded by their measurement uncertainty (far scans are rough).
        top = self.map.height[ix, iy] + 2.0 * self.map.sigma[ix, iy]
        obstacle = self.map.state[ix, iy] == OBSTACLE
        if not obstacle.any():
            return 0.0
        return float(top[obstacle].max()) + SAFETY_MARGIN

    def update(self, fleet, fc, dt: float) -> None:
        i = self.i
        p, v = fleet.pos[i], fleet.vel[i]
        if fleet.crashed[i]:
            fc.armed[i] = False
            return
        cmd = self.cmd
        target = p.copy()
        landing_final = False
        scanning = False

        if cmd.kind == "idle":
            if fleet.grounded[i]:
                fc.armed[i] = False
                return
            cmd = Command(cmd.seq, "hold")

        if cmd.kind == "hold":
            if self.hold_point is None:
                self.hold_point = p.copy()
            target = self.hold_point.copy()
            scanning = True
        elif cmd.kind == "path" and cmd.path:
            while self.wp < len(cmd.path) - 1 and np.linalg.norm(np.array(cmd.path[self.wp]) - p) < WAYPOINT_RADIUS:
                self.wp += 1
            target = np.array(cmd.path[self.wp], dtype=float)
        elif cmd.kind == "land" and cmd.pad is not None:
            dxy = np.hypot(cmd.pad[0] - p[0], cmd.pad[1] - p[1])
            if dxy > 1.0 and not fleet.grounded[i]:
                target = np.array([cmd.pad[0], cmd.pad[1], p[2]])
            else:
                landing_final = True
                target = np.array([cmd.pad[0], cmd.pad[1], p[2] - 3.0])
                if fleet.grounded[i]:
                    fc.armed[i] = False
                    return

        # Reflex: never descend into or fly toward known structure.
        self.avoiding = False
        if not landing_final and not fleet.grounded[i]:
            req = self._required_alt(p, v)
            if req > target[2]:
                target[2] = req
            if p[2] < req - 0.5:
                target[:2] = p[:2]  # stop and climb first
                self.avoiding = True

        d = target[:2] - p[:2]
        final_leg = cmd.kind == "path" and cmd.path and self.wp == len(cmd.path) - 1
        self.scanning = (cmd.kind == "path" and cmd.scan_from is not None and self.wp >= cmd.scan_from
                         and not self.avoiding)
        self.gimbal = np.deg2rad(cmd.gimbal_deg) if self.scanning and cmd.gimbal_deg is not None else self.default_pitch
        fc.speed_limit[i] = cmd.scan_speed if self.scanning and cmd.scan_speed else self.max_speed
        if self.scanning and cmd.face_yaw is not None:
            fc.yaw_sp[i] = cmd.face_yaw
        elif cmd.look_at is not None and final_leg and np.hypot(*d) < 6.0:
            fc.yaw_sp[i] = np.arctan2(cmd.look_at[1] - p[1], cmd.look_at[0] - p[0])
        elif scanning and not self.avoiding:
            fc.yaw_sp[i] += SCAN_RATE * dt
        elif np.hypot(*d) > 3.0:
            fc.yaw_sp[i] = np.arctan2(d[1], d[0])
        fc.armed[i] = True
        fc.pos_sp[i] = target
