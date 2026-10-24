"""Rigid-body quadrotor dynamics, vectorized over a fleet of N drones.

Frames: world is ENU-like with z up. Body frame has z along the thrust axis.
Quaternions are (w, x, y, z) and rotate body vectors into the world frame.
"""
from __future__ import annotations

import numpy as np

G = 9.81

# Vehicle parameters (roughly a 1.5 kg, 500 mm-class quadrotor).
MASS = 1.5
ARM = 0.25
INERTIA = np.array([0.029, 0.029, 0.055])
THRUST_TO_WEIGHT = 2.4
F_MAX = THRUST_TO_WEIGHT * MASS * G / 4  # per motor, N
YAW_COEF = 0.016  # reaction torque per newton of thrust, N*m/N
MOTOR_TAU = 0.03  # first-order motor response, s
DRAG = 0.35  # linear aerodynamic drag, N/(m/s)
PROP_RADIUS = 0.12
AIR_DENSITY = 1.225
PROP_EFFICIENCY = 0.6
AVIONICS_W = 10.0

# X configuration. Motor i at angle 45 + 90*i degrees, alternating spin.
_ang = np.deg2rad(45 + 90 * np.arange(4))
MOTOR_XY = ARM * np.stack([np.cos(_ang), np.sin(_ang)], axis=1)
MOTOR_SPIN = np.array([1.0, -1.0, 1.0, -1.0])

# [T, tau_x, tau_y, tau_z] = ALLOC @ f
ALLOC = np.stack([
    np.ones(4),
    MOTOR_XY[:, 1],
    -MOTOR_XY[:, 0],
    MOTOR_SPIN * YAW_COEF,
])
ALLOC_INV = np.linalg.inv(ALLOC)


def quat_to_rot(q: np.ndarray) -> np.ndarray:
    """(N,4) quaternions -> (N,3,3) rotation matrices."""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    R = np.empty((q.shape[0], 3, 3))
    R[:, 0, 0] = 1 - 2 * (y * y + z * z)
    R[:, 0, 1] = 2 * (x * y - w * z)
    R[:, 0, 2] = 2 * (x * z + w * y)
    R[:, 1, 0] = 2 * (x * y + w * z)
    R[:, 1, 1] = 1 - 2 * (x * x + z * z)
    R[:, 1, 2] = 2 * (y * z - w * x)
    R[:, 2, 0] = 2 * (x * z - w * y)
    R[:, 2, 1] = 2 * (y * z + w * x)
    R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise cross product of (N,3) arrays; much faster than np.cross for small N."""
    out = np.empty_like(a)
    out[:, 0] = a[:, 1] * b[:, 2] - a[:, 2] * b[:, 1]
    out[:, 1] = a[:, 2] * b[:, 0] - a[:, 0] * b[:, 2]
    out[:, 2] = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    return out


def quat_from_yaw(yaw: np.ndarray) -> np.ndarray:
    yaw = np.asarray(yaw, dtype=float)
    q = np.zeros((yaw.size, 4))
    q[:, 0] = np.cos(yaw / 2)
    q[:, 3] = np.sin(yaw / 2)
    return q


def rotor_power(f: np.ndarray) -> np.ndarray:
    """Electrical power (W) per drone from per-motor thrust via momentum theory."""
    area = np.pi * PROP_RADIUS ** 2
    p_ideal = np.power(np.maximum(f, 0.0), 1.5) / np.sqrt(2 * AIR_DENSITY * area)
    return p_ideal.sum(axis=1) / PROP_EFFICIENCY + AVIONICS_W


class QuadrotorFleet:
    def __init__(self, n: int, positions: np.ndarray, yaw: np.ndarray | None = None,
                 battery_wh: float = 15.0):
        self.n = n
        self.pos = np.array(positions, dtype=float).reshape(n, 3)
        self.vel = np.zeros((n, 3))
        self.quat = quat_from_yaw(np.zeros(n) if yaw is None else yaw)
        self.omega = np.zeros((n, 3))  # body rates
        self.motor = np.zeros((n, 4))  # actual motor thrusts, N
        self.motor_cmd = np.zeros((n, 4))
        self.battery_j = np.full(n, battery_wh * 3600.0)
        self.battery_cap_j = battery_wh * 3600.0
        self.crashed = np.zeros(n, dtype=bool)
        self.grounded = np.ones(n, dtype=bool)
        self.power = np.zeros(n)
        self.rot = quat_to_rot(self.quat)  # cached, refreshed whenever quat changes

    @property
    def soc(self) -> np.ndarray:
        return self.battery_j / self.battery_cap_j

    def step(self, dt: float, wind: np.ndarray, world=None) -> None:
        dead = self.crashed | (self.battery_j <= 0)
        cmd = np.where(dead[:, None], 0.0, np.clip(self.motor_cmd, 0.0, F_MAX))
        self.motor += (cmd - self.motor) * min(1.0, dt / MOTOR_TAU)

        wrench = self.motor @ ALLOC.T  # (N,4): T, tau
        thrust = wrench[:, 0]
        tau = wrench[:, 1:]

        R = self.rot
        f_world = R[:, :, 2] * thrust[:, None]
        f_world[:, 2] -= MASS * G
        f_world -= DRAG * (self.vel - wind)
        acc = f_world / MASS

        Iw = INERTIA * self.omega
        domega = (tau - cross(self.omega, Iw)) / INERTIA

        # Drones resting on the ground stay put until thrust exceeds weight.
        resting = self.grounded & (acc[:, 2] <= 0)
        acc[resting] = 0.0
        domega[resting] = 0.0

        self.vel += acc * dt
        self.pos += self.vel * dt
        self.omega += domega * dt
        self.omega[resting] = 0.0
        self.vel[resting] = 0.0
        self._integrate_quat(dt)

        self.power = np.where(dead, 0.0, rotor_power(self.motor))
        self.battery_j = np.maximum(self.battery_j - self.power * dt, 0.0)

        self._contacts(world)

    def _integrate_quat(self, dt: float) -> None:
        w, x, y, z = self.quat.T
        p, q, r = self.omega.T
        dq = 0.5 * np.stack([
            -x * p - y * q - z * r,
            w * p + y * r - z * q,
            w * q - x * r + z * p,
            w * r + x * q - y * p,
        ], axis=1)
        self.quat += dq * dt
        self.quat /= np.sqrt((self.quat ** 2).sum(axis=1, keepdims=True))
        self.rot = quat_to_rot(self.quat)

    def _contacts(self, world) -> None:
        ground = np.zeros(self.n)
        if world is not None:
            inb = world.in_bounds(self.pos[:, 0], self.pos[:, 1])
            ground = np.where(inb, world.height_at(self.pos[:, 0], self.pos[:, 1]), 0.0)
        below = self.pos[:, 2] <= ground
        if not below.any():
            self.grounded[:] = False
            return
        tilt_cos = self.rot[:, 2, 2]
        hard = below & ~self.grounded & (
            (self.vel[:, 2] < -3.0)
            | (np.linalg.norm(self.vel[:, :2], axis=1) > 2.5)
            | (tilt_cos < 0.8)
        )
        # Hitting a wall side-on (ground jumps up under us) is also a crash.
        if world is not None:
            hard |= below & (ground - self.pos[:, 2] > 0.5)
        self.crashed |= hard
        self.pos[below, 2] = ground[below]
        self.vel[below] = 0.0
        self.omega[below] = 0.0
        # Settle level on touchdown, keeping heading.
        if below.any():
            R = self.rot[below]
            yaw = np.arctan2(R[:, 1, 0], R[:, 0, 0])
            self.quat[below] = quat_from_yaw(yaw)
            self.rot = quat_to_rot(self.quat)
        self.grounded = below
