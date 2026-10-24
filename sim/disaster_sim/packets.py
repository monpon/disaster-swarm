"""Wire packets between the drones' ESP32 modules and the central node.

This is the hardware boundary. Each drone carries an ESP32 with a 6-axis IMU hat. The
ESP forwards the drone camera's JPEG frames and batches of IMU samples to the central node
over the ESP mesh, and passes the central node's stick commands to the drone's stock flight
controller. The master only ever sees these packets, so a real ESP bridge can replace the
simulated drones without touching the master.

`sim_truth` fields carry ground truth that real hardware cannot provide. They exist only so
the simulated stand-ins for visual-inertial odometry and the monocular depth network
(`estimation.py`) can model their errors; nothing else may read them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ImuPacket:
    """IMU batch + housekeeping, sent by the ESP at a fixed rate."""
    drone: int
    t: float  # time of the last sample
    dt: float  # sample period
    accel: np.ndarray  # (N, 3) specific force, body frame, m/s^2
    gyro: np.ndarray  # (N, 3) body rates, rad/s
    battery: float  # state of charge 0..1 (from the drone's battery voltage)
    grounded: bool  # landed (no thrust, IMU at rest)
    crashed: bool  # impact/tumble detected from the IMU
    failsafe: bool  # ESP lost the command link and is holding the sticks neutral
    link_bps: float = 0.0  # mesh route throughput the ESP currently gets to the root
    hops: int = 0
    parent: int = -2  # next hop toward the root (-1 = the root itself, -2 = none)
    neighbors: list = field(default_factory=list)  # (node, SNR dB) for the strongest links; node -1 = root
    holding: bool = False  # the link reflex is holding the sticks centred (edge of coverage)
    backlog: int = 0  # full-quality frames waiting in the ESP's buffer
    sim_truth: dict = field(default_factory=dict, repr=False)

    @property
    def nbytes(self) -> int:
        return 24 + len(self.accel) * 12


@dataclass
class FramePacket:
    """One JPEG camera frame as received from the drone (decoded here to RGB)."""
    drone: int
    t: float
    rgb: np.ndarray  # (H, W, 3) uint8, as decoded by the master
    nbytes: int  # JPEG size on the wire
    thumb: bool = False  # sent as a small thumbnail because the link could not carry the full frame
    sim_truth: dict = field(default_factory=dict, repr=False)


@dataclass
class StickCommand:
    """Central node -> ESP -> drone. Velocity-style sticks (optical-flow drones hold
    position when centered)."""
    drone: int
    seq: int
    mode: str = "fly"  # fly | land | disarm
    vx: float = 0.0  # forward, m/s (body frame)
    vy: float = 0.0  # left, m/s (body frame)
    vz: float = 0.0  # climb, m/s
    yaw_rate: float = 0.0  # rad/s, counter-clockwise
    nbytes: int = 16
    retreat: bool = False  # heading back toward coverage/base: the link reflex must not hold this
    cam: str = "full"  # camera policy: full (nav + bulk frames) | nav (small frames only) | off
