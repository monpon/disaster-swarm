"""The ESP32 module on each drone (simulated). It does no perception or planning.

* Samples its IMU hat (accelerometer + gyro, with noise and wandering biases) every physics
  step and ships the samples to the central node in batches.
* Forwards the drone camera's JPEG frames (the simulation produces them in `camera.py`).
* Passes the central node's stick commands to the drone's stock flight controller.
* Failsafes: if commands stop arriving it centers the sticks, so the drone holds roughly in
  place on its optical flow ("frozen") until the link returns; on a nearly flat battery
  the stock firmware lands wherever it is.
"""
from __future__ import annotations

import numpy as np

from .packets import ImuPacket, StickCommand
from .comms import M_HOLD, M_RESUME
from .physics import G

STICK_TIMEOUT = 0.5  # s without a command -> neutral sticks
AUTO_LAND_SOC = 0.06
LAND_RATE = 0.7  # m/s
ACCEL_NOISE, GYRO_NOISE = 0.06, 0.004
ACCEL_BIAS_WALK, GYRO_BIAS_WALK = 0.002, 0.0002  # per sqrt(s)
FLOW_BIAS_WALK, FLOW_BIAS_MAX = 0.02, 0.06  # optical-flow velocity bias (m/s)


class EspFleet:
    def __init__(self, n: int, rng: np.random.Generator):
        self.n = n
        self.rng = rng
        self.cmd = [StickCommand(i, 0, "disarm") for i in range(n)]
        self.cmd_t = np.full(n, -1e9)
        self.failsafe = np.zeros(n, dtype=bool)
        self.auto_land = np.zeros(n, dtype=bool)
        self.link_hold = np.zeros(n, dtype=bool)  # link reflex: parent link too weak to move on
        self.cam_mode = ["full"] * n
        self.snr_hist: list[list] = [[] for _ in range(n)]
        self.accel_bias = rng.normal(0.0, 0.05, (n, 3))
        self.gyro_bias = rng.normal(0.0, 0.003, (n, 3))
        self.flow_bias = np.zeros((n, 2))
        self._acc: list[np.ndarray] = []
        self._gyr: list[np.ndarray] = []

    # ------------------------------------------------------------------ sensing
    def sample(self, fleet, dt: float) -> None:
        """One IMU sample per drone (called every physics step) + bias random walks."""
        rot_t = fleet.rot.transpose(0, 2, 1)
        f_world = fleet.acc + np.array([0.0, 0.0, G])
        acc = np.einsum("nij,nj->ni", rot_t, f_world) + self.accel_bias + self.rng.normal(0, ACCEL_NOISE, (self.n, 3))
        gyr = fleet.omega + self.gyro_bias + self.rng.normal(0, GYRO_NOISE, (self.n, 3))
        self._acc.append(acc)
        self._gyr.append(gyr)
        s = np.sqrt(dt)
        self.accel_bias += self.rng.normal(0, ACCEL_BIAS_WALK * s, (self.n, 3))
        self.gyro_bias += self.rng.normal(0, GYRO_BIAS_WALK * s, (self.n, 3))
        self.flow_bias = np.clip(self.flow_bias + self.rng.normal(0, FLOW_BIAS_WALK * s, (self.n, 2)),
                                 -FLOW_BIAS_MAX, FLOW_BIAS_MAX)

    def _link_reflex(self, i: int, cmd: StickCommand, t: float, snr: float, grounded: bool) -> None:
        """Stop at the edge of coverage on the drone's own signal measurement: below M_HOLD the
        sticks are centred (hover) even though commands keep arriving, until the link is back
        above M_RESUME or is clearly improving. Retreat commands (home, back into coverage)
        are never held. The master answers a holding drone by placing a relay."""
        h = self.snr_hist[i]
        h.append((t, snr))
        while h and t - h[0][0] > 1.0:
            h.pop(0)
        if grounded or cmd.mode in ("land", "disarm") or snr <= 0 or cmd.retreat:
            self.link_hold[i] = False
            return
        rising = len(h) > 3 and snr - h[0][1] > 1.0
        if self.link_hold[i]:
            if snr >= M_RESUME or rising:
                self.link_hold[i] = False
        elif snr < M_HOLD:
            self.link_hold[i] = True

    def flow_velocity(self, fleet) -> np.ndarray:
        """The stock FC's own velocity estimate (optical flow + baro), biased."""
        v = fleet.vel.copy()
        v[:, :2] += self.flow_bias
        return v

    def packets(self, fleet, t: float, dt: float, radio, backlog) -> list[ImuPacket]:
        """Batch the IMU samples gathered since the last call into one packet per drone."""
        if not self._acc:
            return []
        acc, gyr = np.stack(self._acc, axis=1), np.stack(self._gyr, axis=1)  # (n, k, 3)
        self._acc, self._gyr = [], []
        out = []
        for i in range(self.n):
            out.append(ImuPacket(
                i, t, dt, acc[i], gyr[i], float(fleet.soc[i]), bool(fleet.grounded[i]),
                bool(fleet.crashed[i]), bool(self.failsafe[i]), radio.routes[i].capacity, radio.routes[i].hops,
                radio.parent_of(i), radio.neighbors(i), bool(self.link_hold[i]), int(backlog[i]),
                sim_truth={"pos": fleet.pos[i].copy(), "vel": fleet.vel[i].copy(),
                           "rot": fleet.rot[i].copy(), "grounded": bool(fleet.grounded[i])}))
        return out

    # ------------------------------------------------------------------ control
    def on_command(self, cmd: StickCommand, t: float) -> None:
        if cmd.seq < self.cmd[cmd.drone].seq:
            return  # stale (links reorder)
        self.cmd[cmd.drone] = cmd
        self.cmd_t[cmd.drone] = t

    def apply(self, fleet, fc, t: float, dt: float, radio=None) -> None:
        """Turn the latest sticks into the stock flight controller's setpoints."""
        yaw = np.arctan2(fleet.rot[:, 1, 0], fleet.rot[:, 0, 0])
        for i in range(self.n):
            if fleet.crashed[i]:
                fc.armed[i] = False
                continue
            cmd = self.cmd[i]
            self.cam_mode[i] = cmd.cam
            if radio is not None:
                self._link_reflex(i, cmd, t, radio.parent_snr(i), bool(fleet.grounded[i]))
            self.failsafe[i] = t - self.cmd_t[i] > STICK_TIMEOUT and not fleet.grounded[i]
            self.auto_land[i] |= fleet.soc[i] < AUTO_LAND_SOC and not fleet.grounded[i]
            if self.auto_land[i] or (cmd.mode == "land" and not self.failsafe[i]):
                if fleet.grounded[i]:
                    fc.armed[i] = False
                    continue
                fc.vel_sp[i] = (0.0, 0.0, -LAND_RATE)
                fc.armed[i] = True
                continue
            if self.failsafe[i] or self.link_hold[i]:  # centered sticks: hold on optical flow
                fc.vel_sp[i] = 0.0
                fc.armed[i] = True
                continue
            if cmd.mode == "disarm" or (fleet.grounded[i] and cmd.vz <= 0.05):
                fc.armed[i] = False
                fc.vel_sp[i] = 0.0
                fc.yaw_sp[i] = yaw[i]
                continue
            c, s = np.cos(yaw[i]), np.sin(yaw[i])
            fc.vel_sp[i] = (c * cmd.vx - s * cmd.vy, s * cmd.vx + c * cmd.vy, cmd.vz)
            fc.yaw_sp[i] = yaw[i] + float(np.clip(cmd.yaw_rate, -1.5, 1.5)) / 3.0  # rate via heading lead (kp_att z = 3)
            fc.armed[i] = True
        self.auto_land &= ~fleet.grounded
