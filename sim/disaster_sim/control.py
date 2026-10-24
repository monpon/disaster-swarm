"""Cascaded flight controller: position -> velocity -> attitude -> body rate -> motors."""
from __future__ import annotations

import numpy as np

from .physics import ALLOC_INV, F_MAX, G, INERTIA, MASS, cross

MAX_TILT = np.deg2rad(30)


class FlightController:
    def __init__(self, n: int, max_speed: float = 8.0):
        self.n = n
        self.kp_pos = np.array([1.0, 1.0, 1.4])
        self.kp_vel = np.array([2.6, 2.6, 4.0])
        self.ki_vel = np.array([0.6, 0.6, 1.2])
        self.kp_att = np.array([8.0, 8.0, 3.0])
        self.kp_rate = np.array([22.0, 22.0, 10.0])
        self.max_speed_h = max_speed
        self.max_speed_up = 3.0
        self.max_speed_down = 2.0
        self.max_rate = np.array([4.0, 4.0, 1.5])
        self.vel_int = np.zeros((n, 3))

        self.pos_sp = np.zeros((n, 3))
        self.yaw_sp = np.zeros(n)
        self.speed_limit = np.full(n, max_speed)
        self.armed = np.zeros(n, dtype=bool)

    def reset_integrators(self, mask: np.ndarray) -> None:
        self.vel_int[mask] = 0.0

    def update(self, fleet, dt: float) -> None:
        pos, vel, R, omega = fleet.pos, fleet.vel, fleet.rot, fleet.omega

        # Position loop -> velocity setpoint with separate horizontal/vertical limits.
        v_sp = self.kp_pos * (self.pos_sp - pos)
        vh = np.hypot(v_sp[:, 0], v_sp[:, 1])
        lim = np.minimum(self.speed_limit, self.max_speed_h)
        scale = np.where(vh > lim, lim / np.maximum(vh, 1e-9), 1.0)
        v_sp[:, :2] *= scale[:, None]
        v_sp[:, 2] = np.clip(v_sp[:, 2], -self.max_speed_down, self.max_speed_up)

        # Velocity loop -> desired acceleration (PI, anti-windup by clamping).
        err = v_sp - vel
        self.vel_int = np.clip(self.vel_int + err * dt, -3.0, 3.0)
        self.vel_int[fleet.grounded] = 0.0
        a_sp = self.kp_vel * err + self.ki_vel * self.vel_int
        a_sp[:, 2] += G

        # Tilt limit: cap horizontal accel relative to vertical.
        a_sp[:, 2] = np.maximum(a_sp[:, 2], 0.3 * G)
        ah = np.hypot(a_sp[:, 0], a_sp[:, 1])
        ah_max = a_sp[:, 2] * np.tan(MAX_TILT)
        s = np.where(ah > ah_max, ah_max / np.maximum(ah, 1e-9), 1.0)
        a_sp[:, :2] *= s[:, None]

        F = MASS * a_sp
        thrust = (F * R[:, :, 2]).sum(axis=1)

        # Desired attitude from thrust direction and yaw setpoint.
        zb = F / np.sqrt((F ** 2).sum(axis=1, keepdims=True))
        xc = np.stack([np.cos(self.yaw_sp), np.sin(self.yaw_sp), np.zeros(self.n)], axis=1)
        yb = cross(zb, xc)
        yb /= np.sqrt((yb ** 2).sum(axis=1, keepdims=True))
        xb = cross(yb, zb)
        R_des = np.stack([xb, yb, zb], axis=2)

        # Geometric attitude error e_R = 0.5 * vee(R_des^T R - R^T R_des).
        M = R_des.transpose(0, 2, 1) @ R
        E = M - M.transpose(0, 2, 1)
        e_R = 0.5 * np.stack([E[:, 2, 1], E[:, 0, 2], E[:, 1, 0]], axis=1)
        rate_sp = np.clip(-self.kp_att * e_R, -self.max_rate, self.max_rate)

        Iw = INERTIA * omega
        tau = INERTIA * self.kp_rate * (rate_sp - omega) + cross(omega, Iw)

        wrench = np.concatenate([thrust[:, None], tau], axis=1)
        f = wrench @ ALLOC_INV.T
        f = np.clip(f, 0.0, F_MAX)
        f[~self.armed] = 0.0
        fleet.motor_cmd = f
