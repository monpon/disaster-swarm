"""Onboard autopilot. Drones do no mapping or planning: they fly the master's waypoints.

Onboard logic is limited to what a real airframe does without a map:
* follow waypoints with a commanded heading per leg (the camera is fixed to the nose, so
  heading is the only way to aim it),
* a time-of-flight reflex that backs away from anything closer than REFLEX_DIST,
* a lost-link failsafe: freeze in place (so the master knows where to send a relay) and
  only retrace the drone's own breadcrumb trail if the battery runs critically low.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .camera import RANGER_DIRS

WAYPOINT_RADIUS = 0.7
REFLEX_DIST = 0.7  # plus stopping distance at the current closing speed
BRAKE_DECEL = 2.5
LOST_FREEZE_S = 1.0  # link silence before freezing in place
LOW_BATTERY_RETRACE = 0.22  # frozen drones head back along their trail below this charge
BREADCRUMB_SPACING = 2.0
CONFINED_RANGE = 3.9  # anything the rangers can see -> confined-space speed limit
CONFINED_SPEED = 2.0
MAX_BREADCRUMBS = 400


@dataclass
class Command:
    seq: int
    kind: str  # idle | path | land | hold
    path: list[tuple[float, float, float]] = field(default_factory=list)
    yaws: list[float] | None = None  # heading to hold on each leg (None -> face travel)
    speed: float | None = None
    pad: tuple[float, float] | None = None
    keep_on_loss: bool = False  # keep flying this path if the link drops (going home)

    def key(self):
        return (self.kind, tuple(self.path), None if self.yaws is None else tuple(self.yaws), self.pad)


class Autopilot:
    def __init__(self, idx: int, max_speed: float):
        self.i = idx
        self.max_speed = max_speed
        self.cmd = Command(0, "idle")
        self.wp = 0
        self.hold_point: np.ndarray | None = None
        self.avoiding = False
        self.connected = True
        self.lost_since: float | None = None
        self.breadcrumbs: list[np.ndarray] = []
        self.returning = False
        self.frozen = False  # holding position after losing the link, waiting for a relay
        self.freeze_point: np.ndarray | None = None

    def on_command(self, cmd: Command) -> None:
        if cmd.seq <= self.cmd.seq:
            return  # stale or duplicate (links reorder)
        if cmd.key() != self.cmd.key():
            self.wp = 0
            self.hold_point = None
        self.cmd = cmd
        self.returning = False

    def set_link(self, connected: bool, t: float) -> None:
        if connected:
            self.lost_since = None
            self.frozen = False
            self.freeze_point = None
            if self.returning:  # reconnected: stop and wait for the master
                self.returning = False
                self.cmd = Command(self.cmd.seq, "hold")
                self.hold_point = None
        elif self.lost_since is None:
            self.lost_since = t
        self.connected = connected

    def _crumb(self, p: np.ndarray) -> None:
        if not self.breadcrumbs or np.linalg.norm(p - self.breadcrumbs[-1]) > BREADCRUMB_SPACING:
            self.breadcrumbs.append(p.copy())
            if len(self.breadcrumbs) > MAX_BREADCRUMBS:
                self.breadcrumbs.pop(0)

    def update(self, fleet, fc, rangers: np.ndarray, t: float) -> None:
        i = self.i
        p, v = fleet.pos[i], fleet.vel[i]
        if fleet.crashed[i]:
            fc.armed[i] = False
            return
        if not fleet.grounded[i]:
            self._crumb(p)

        # Lost link: freeze where the link dropped and wait for the master to bring a relay
        # into range. Only a nearly empty battery sends the drone back along its own trail.
        cmd = self.cmd
        lost = self.lost_since is not None and t - self.lost_since > LOST_FREEZE_S and not fleet.grounded[i]
        if lost and fleet.soc[i] < LOW_BATTERY_RETRACE:
            self.returning, self.frozen = True, False
        elif lost and not self.returning and not (cmd.keep_on_loss and cmd.kind == "path"):
            if not self.frozen:
                self.frozen = True
                self.freeze_point = p.copy()
        target = p.copy()
        yaw = None
        speed = cmd.speed or self.max_speed

        if self.frozen and self.freeze_point is not None:
            target = self.freeze_point.copy()
            yaw = fc.yaw_sp[i]
        elif self.returning and self.breadcrumbs:
            target = self.breadcrumbs[-1].copy()
            if np.linalg.norm(target - p) < WAYPOINT_RADIUS and len(self.breadcrumbs) > 1:
                self.breadcrumbs.pop()
            speed = min(speed, 2.0)
        elif cmd.kind == "idle":
            if fleet.grounded[i]:
                fc.armed[i] = False
                return
            if self.hold_point is None:
                self.hold_point = p.copy()
            target = self.hold_point.copy()
        elif cmd.kind == "hold":
            if self.hold_point is None:
                self.hold_point = p.copy()
            target = self.hold_point.copy()
            yaw = fc.yaw_sp[i] + 0.3 / 20  # slow look-around sweep
        elif cmd.kind == "path" and cmd.path:
            while self.wp < len(cmd.path) - 1 and np.linalg.norm(np.array(cmd.path[self.wp]) - p) < WAYPOINT_RADIUS:
                self.wp += 1
            target = np.array(cmd.path[self.wp], dtype=float)
            if self.wp + 1 < len(cmd.path):  # brake before sharp turns
                nxt = np.array(cmd.path[self.wp + 1], dtype=float)
                a, b = target - p, nxt - target
                if np.linalg.norm(a) > 1e-3 and np.linalg.norm(b) > 1e-3:
                    cos = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
                    if cos < 0.7:
                        speed = min(speed, max(0.8, 1.2 * np.linalg.norm(a)))
            if cmd.yaws is not None:
                yaw = cmd.yaws[min(self.wp, len(cmd.yaws) - 1)]
        elif cmd.kind == "land" and cmd.pad is not None:
            if np.hypot(cmd.pad[0] - p[0], cmd.pad[1] - p[1]) > 0.8 and not fleet.grounded[i]:
                target = np.array([cmd.pad[0], cmd.pad[1], p[2]])
            else:
                target = np.array([cmd.pad[0], cmd.pad[1], p[2] - 3.0])
                if fleet.grounded[i]:
                    fc.armed[i] = False
                    return

        # Time-of-flight reflex: stop short of anything in the direction of travel (using the
        # stopping distance at the current closing speed), and hop over low obstacles.
        self.avoiding = False
        if not fleet.grounded[i] and cmd.kind != "land":
            closing = np.maximum(RANGER_DIRS @ v, 0.0)
            trigger = REFLEX_DIST + closing ** 2 / (2 * BRAKE_DECEL) + 0.15 * closing
            want = RANGER_DIRS @ (target - p) > 0.2
            for k in np.flatnonzero((rangers < trigger) & ((closing > 0.15) | want)):
                along = np.dot(target - p, RANGER_DIRS[k])
                target = target - RANGER_DIRS[k] * (along + max(trigger[k] - rangers[k], 0.0) * 0.5)
                self.avoiding = True
                if k < 4 and rangers[4] > 3.0:  # blocked sideways with headroom: climb over it
                    target[2] = max(target[2], p[2] + 1.5)

        if (rangers[:5] < CONFINED_RANGE).any() and not fleet.grounded[i]:  # walls/ceiling, not ground
            speed = min(speed, CONFINED_SPEED)

        d = target[:2] - p[:2]
        if yaw is None and np.hypot(*d) > 1.5:
            yaw = np.arctan2(d[1], d[0])
        if yaw is not None:
            fc.yaw_sp[i] = yaw
        fc.speed_limit[i] = speed
        fc.armed[i] = True
        fc.pos_sp[i] = target
