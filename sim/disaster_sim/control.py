"""The drone's stock flight controller: velocity -> attitude -> body rate -> motors.

Like the optical-flow toy drones it models, it flies velocity-style sticks: it tracks a
commanded velocity using its own downward optical-flow velocity estimate (which carries a
slowly wandering bias, so a "hovering" drone drifts a little) and its barometric climb rate,
and holds the heading set by integrating the yaw-rate stick. It has no notion of position.
"""
from __future__ import annotations

import numpy as np

from .physics import ALLOC_INV, F_MAX, G, INERTIA, MASS, cross

MAX_TILT = np.deg2rad(30)
MAX_YAW_STEP = 1.0  # rad


class FlightController:
    def __init__(self, n: int, max_speed: float = 8.0):
        self.n = n
        self.kp_vel = np.array([2.6, 2.6, 4.0])
        self.ki_vel = np.array([0.6, 0.6, 1.2])
        self.kp_att = np.array([8.0, 8.0, 3.0])
        self.kp_rate = np.array([22.0, 22.0, 10.0])
        self.max_speed_h = max_speed
        self.max_speed_up = 3.0
        self.max_speed_down = 2.0
        self.max_rate = np.array([4.0, 4.0, 1.5])
        self.vel_int = np.zeros((n, 3))

        self.vel_sp = np.zeros((n, 3))  # world-frame velocity setpoint (from the sticks)
        self.vel_meas = np.zeros((n, 3))  # the drone's own (flow + baro) velocity estimate
        self.yaw_sp = np.zeros(n)
        self.speed_limit = np.full(n, max_speed)
        self.armed = np.zeros(n, dtype=bool)

    def reset_integrators(self, mask: np.ndarray) -> None:
        self.vel_int[mask] = 0.0

    def update(self, fleet, dt: float) -> None:
        R, omega = fleet.rot, fleet.omega

        # Stick velocity setpoint with separate horizontal/vertical limits.
        v_sp = self.vel_sp.copy()
        vh = np.hypot(v_sp[:, 0], v_sp[:, 1])
        lim = np.minimum(self.speed_limit, self.max_speed_h)
        scale = np.where(vh > lim, lim / np.maximum(vh, 1e-9), 1.0)
        v_sp[:, :2] *= scale[:, None]
        v_sp[:, 2] = np.clip(v_sp[:, 2], -self.max_speed_down, self.max_speed_up)

        # Velocity loop -> desired acceleration (PI, anti-windup by clamping).
        err = v_sp - self.vel_meas
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
        # The yaw used here stays within MAX_YAW_STEP of the current heading: the geometric
        # error below vanishes for 180-degree errors, so a large yaw jump could otherwise
        # leave the vehicle stuck at a tilted false equilibrium.
        zb = F / np.sqrt((F ** 2).sum(axis=1, keepdims=True))
        yaw = np.arctan2(R[:, 1, 0], R[:, 0, 0])
        yaw_err = (self.yaw_sp - yaw + np.pi) % (2 * np.pi) - np.pi
        yaw_cmd = yaw + np.clip(yaw_err, -MAX_YAW_STEP, MAX_YAW_STEP)
        xc = np.stack([np.cos(yaw_cmd), np.sin(yaw_cmd), np.zeros(self.n)], axis=1)
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

        # Mixer with yaw de-prioritized (as in real flight stacks): thrust and roll/pitch
        # torques are allocated first; yaw only gets the motor headroom that is left, so a
        # big heading change can never starve attitude control and tip the vehicle.
        zeros = np.zeros_like(thrust)
        f_rp = np.stack([thrust, tau[:, 0], tau[:, 1], zeros], axis=1) @ ALLOC_INV.T
        f_yaw = np.stack([zeros, zeros, zeros, tau[:, 2]], axis=1) @ ALLOC_INV.T
        up = np.where(f_yaw > 1e-9, (F_MAX - f_rp) / np.maximum(f_yaw, 1e-9), np.inf)
        down = np.where(f_yaw < -1e-9, f_rp / np.maximum(-f_yaw, 1e-9), np.inf)
        s_yaw = np.clip(np.minimum(up, down).min(axis=1), 0.0, 1.0)
        f = np.clip(f_rp + s_yaw[:, None] * f_yaw, 0.0, F_MAX)
        f[~self.armed] = 0.0
        fleet.motor_cmd = f
