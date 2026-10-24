"""Drone sensors. The RGB-D camera produces the only data a drone sends for mapping.

Frames are rendered by ray marching through the true voxel world. The drone does no
processing on them: it streams them (with its pose) to the master. Six short
time-of-flight rangers feed the onboard collision reflex.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import materials as M
from .building import Building
from .config import SimConfig

STEP = 0.5  # ray-march step (m); voxels are 1 m
RANGER_DIRS = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float)
RANGER_MAX = 4.0


@dataclass
class Frame:
    """One camera frame as transmitted: pose + depth (0 = no return) + RGB."""
    drone: int
    t: float
    pos: np.ndarray  # (3,)
    rot: np.ndarray  # (3, 3) body-to-world rotation at capture (the camera is body-fixed)
    depth: np.ndarray  # (H, W) float32
    rgb: np.ndarray  # (H, W, 3) uint8

    @property
    def nbytes(self) -> int:
        return self.depth.size * 2 + self.rgb.size + 48  # 16-bit depth + pose on the wire

    @property
    def yaw(self) -> float:
        return float(np.arctan2(self.rot[1, 0], self.rot[0, 0]))


class Intrinsics:
    """Pixel ray directions, shared by the camera and the master's back-projection.

    The camera is hard-mounted on the airframe looking along the nose (body +x), tilted
    down by a fixed mount angle. It has no gimbal: it pitches and rolls with the drone."""

    def __init__(self, cfg: SimConfig):
        self.w, self.h = cfg.cam_w, cfg.cam_h
        self.range = cfg.cam_range
        u = (np.arange(self.w) + 0.5) / self.w * 2 - 1
        v = 1 - (np.arange(self.h) + 0.5) / self.h * 2
        self.u = np.tan(np.deg2rad(cfg.cam_hfov_deg) / 2) * u  # right
        self.v = np.tan(np.deg2rad(cfg.cam_vfov_deg) / 2) * v  # up
        self.steps = np.arange(STEP / 2, self.range, STEP)
        tilt = np.deg2rad(cfg.cam_mount_tilt_deg)
        fwd = np.array([np.cos(tilt), 0.0, -np.sin(tilt)])
        right = np.array([0.0, -1.0, 0.0])
        up = np.cross(right, fwd)
        d = (fwd[None, None, :] + self.u[None, :, None] * right[None, None, :]
             + self.v[:, None, None] * up[None, None, :]).reshape(-1, 3)
        self.body_rays = d / np.linalg.norm(d, axis=1, keepdims=True)

    def rays(self, rot: np.ndarray) -> np.ndarray:
        """(H*W, 3) unit ray directions in world frame for body attitude `rot`, row-major
        from the top-left pixel."""
        return self.body_rays @ rot.T


class RGBDCamera:
    def __init__(self, building: Building, cfg: SimConfig, rng: np.random.Generator):
        self.b = building
        self.k = Intrinsics(cfg)
        self.rng = rng
        # Pad the world so rays never need bounds checks: below ground is solid asphalt,
        # everywhere else outside the site is air.
        pad = int(np.ceil(cfg.cam_range)) + 2
        sx, sy, sz = building.vox.shape
        padded = np.zeros((sx + 2 * pad, sy + 2 * pad, sz + 2 * pad), dtype=np.uint8)
        padded[:, :, :pad] = M.ASPHALT
        padded[pad:pad + sx, pad:pad + sy, pad:pad + sz] = building.vox
        self.pad = pad
        self.flat = padded.reshape(-1)
        self.strides = np.array([padded.shape[1] * padded.shape[2], padded.shape[2], 1], dtype=np.int64)

    def _lookup(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(materials, integer voxel coords) at world points (..., 3)."""
        vidx = np.floor(pts).astype(np.int64)
        return self.flat[(vidx + self.pad) @ self.strides], vidx

    def capture(self, drone: int, t: float, pos: np.ndarray, rot: np.ndarray, chunk: int = 6) -> Frame:
        k = self.k
        dirs = k.rays(rot)
        n = len(dirs)
        first = np.full(n, -1, dtype=np.int64)
        alive = np.arange(n)
        steps = k.steps
        # March in chunks and drop rays as soon as they hit (indoor rays are short).
        for c0 in range(0, len(steps), chunk):
            s = steps[c0:c0 + chunk]
            pts = pos[None, None, :] + dirs[alive, None, :] * s[None, :, None]
            mat, _ = self._lookup(pts)
            solid = mat != M.AIR
            got = solid.any(axis=1)
            first[alive[got]] = c0 + solid[got].argmax(axis=1)
            alive = alive[~got]
            if len(alive) == 0:
                break
        hit = first >= 0
        fi = np.maximum(first, 0)
        depth = steps[fi]
        hit_mat, cur = self._lookup(pos[None, :] + dirs * depth[:, None])

        # Refine: if the half-step before the hit is already solid, the surface is closer.
        back_mat, _ = self._lookup(pos[None, :] + dirs * (depth - STEP / 2)[:, None])
        closer = back_mat != M.AIR
        depth = np.where(closer, depth - STEP / 2, depth)

        # Surface normal from which voxel face the ray crossed (for shading).
        _, prev = self._lookup(pos[None, :] + dirs * np.maximum(steps[np.maximum(fi - 1, 0)], 0)[:, None])
        crossed = np.abs(cur - prev)
        r = np.arange(n)
        axis = np.where(crossed.any(axis=1), np.argmax(crossed * np.abs(dirs), axis=1), np.argmax(np.abs(dirs), axis=1))
        facing = np.abs(dirs[r, axis])
        shade = 0.8 + 0.2 * facing + np.where((axis == 2) & (dirs[:, 2] < 0), 0.05, 0.0)

        noise = self.rng.normal(0.0, 0.035, size=(n, 3))
        rgb = M.COLORS[hit_mat].astype(np.float32) * (shade[:, None] + noise)
        rgb = np.where(hit[:, None], rgb, np.array([18.0, 22.0, 30.0]))  # no return: dark
        depth = depth + self.rng.normal(0.0, 1.0, size=n) * (0.02 + 0.01 * depth)
        depth = np.where(hit, np.maximum(depth, 0.05), 0.0)
        return Frame(drone, t, pos.copy(), rot.copy(),
                     depth.reshape(k.h, k.w).astype(np.float32),
                     np.clip(rgb, 0, 255).astype(np.uint8).reshape(k.h, k.w, 3))

    def rangers(self, pos: np.ndarray) -> np.ndarray:
        """(N, 6) distances to the nearest surface along +-x, +-y, +-z (RANGER_MAX if none)."""
        s = np.arange(0.1, RANGER_MAX, 0.1)
        pts = pos[:, None, None, :] + RANGER_DIRS[None, :, None, :] * s[None, None, :, None]
        solid = self._lookup(pts)[0] != M.AIR
        first = solid.argmax(axis=2)
        anyhit = solid.any(axis=2)
        return np.where(anyhit, s[first], RANGER_MAX)
