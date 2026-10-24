"""The drone's camera: a cheap monocular RGB camera fixed to the nose.

Frames are rendered by ray marching through the true voxel world, then degraded the way a
toy-drone camera + JPEG stream degrades them: sensor gain noise (worse indoors, where auto
exposure cranks the gain), motion blur from body rotation, chroma subsampling and
quantization. The ESP forwards them as JPEG; the master gets RGB only. True depth rides
along in `sim_truth` purely so the simulated depth network can model its errors.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import materials as M
from .building import Building
from .config import SimConfig
from .packets import FramePacket

STEP = 0.5  # ray-march step (m); voxels are 1 m
EXPOSURE_S = 1 / 30
GAIN_NOISE_OUTDOOR, GAIN_NOISE_INDOOR = 0.04, 0.09
JPEG_STEP = 8.0


@dataclass
class Frame:
    """An observation as the master fuses it: estimated pose + estimated depth (0 = none)
    + RGB."""
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
        self.hfov_deg = cfg.cam_hfov_deg
        self.jpeg_bytes = cfg.jpeg_bytes
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
        self.torch = None
        try:  # render every drone's frame in one batch on the GPU when there is one
            import torch
            if torch.cuda.is_available():
                dev = torch.device("cuda")
                self.torch, self.dev = torch, dev
                self.t_flat = torch.as_tensor(self.flat, device=dev)
                self.t_steps = torch.as_tensor(self.k.steps, device=dev, dtype=torch.float32)
                self.t_rays = torch.as_tensor(self.k.body_rays, device=dev, dtype=torch.float32)
                self.t_colors = torch.as_tensor(M.COLORS, device=dev).float()
                self.t_strides = torch.as_tensor(self.strides, device=dev)
        except ImportError:
            pass

    def _lookup(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(materials, integer voxel coords) at world points (..., 3)."""
        vidx = np.floor(pts).astype(np.int64)
        return self.flat[(vidx + self.pad) @ self.strides], vidx

    def capture_many(self, items: list, t: float) -> list[FramePacket]:
        """Frames for several drones at once: items are (drone, pos, rot, omega)."""
        if not items:
            return []
        if self.torch is None:
            return [self.capture(d, t, p, r, w) for d, p, r, w in items]
        depth, rgb = self._render_gpu(np.stack([p for _, p, _, _ in items]), np.stack([r for _, _, r, _ in items]))
        k, out = self.k, []
        for j, (d, pos, rot, omega) in enumerate(items):
            img = self._degrade(rgb[j].reshape(k.h, k.w, 3), self.b.inside_building(pos[None, :])[0], omega)
            size = int(self.jpeg_bytes * self.rng.uniform(0.8, 1.2))
            out.append(FramePacket(d, t, img, size, sim_truth={"pos": pos.copy(), "rot": rot.copy(),
                                                              "depth": depth[j].reshape(k.h, k.w).astype(np.float32)}))
        return out

    def _render_gpu(self, poss: np.ndarray, rots: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Ray-march (M drones x N pixels x S steps) through the voxel world on the GPU. Same
        algorithm as `capture`: first solid sample, refine by half a step, shade by the face."""
        torch, dev = self.torch, self.dev
        pos = torch.as_tensor(poss, device=dev, dtype=torch.float32)
        rot = torch.as_tensor(rots, device=dev, dtype=torch.float32)
        dirs = torch.einsum("nk,mjk->mnj", self.t_rays, rot)  # (M, N, 3), world frame
        S = self.t_steps
        st = self.t_strides

        def look(points):
            v = torch.floor(points).long()
            return self.t_flat[((v + self.pad) * st).sum(-1)].long(), v

        pts = pos[:, None, None, :] + dirs[:, :, None, :] * S[None, None, :, None]  # (M, N, S, 3)
        mat, _ = look(pts)
        solid = mat != M.AIR
        hit = solid.any(2)
        first = solid.float().argmax(2)  # first solid sample (ties go to the first)
        depth = S[first]
        hit_mat, cur = look(pos[:, None, :] + dirs * depth[..., None])
        back_mat, _ = look(pos[:, None, :] + dirs * (depth - STEP / 2)[..., None])
        depth = torch.where(back_mat != M.AIR, depth - STEP / 2, depth)
        prev_d = S[(first - 1).clamp(min=0)].clamp(min=0)
        _, prev = look(pos[:, None, :] + dirs * prev_d[..., None])
        crossed = (cur - prev).abs().float()
        axis = torch.where(crossed.sum(-1) > 0, (crossed * dirs.abs()).argmax(-1), dirs.abs().argmax(-1))
        facing = dirs.abs().gather(-1, axis[..., None])[..., 0]
        shade = 0.8 + 0.2 * facing + torch.where((axis == 2) & (dirs[..., 2] < 0), 0.05, 0.0)
        rgb = self.t_colors[hit_mat] * shade[..., None]
        sky = torch.tensor([18.0, 22.0, 30.0], device=dev)
        rgb = torch.where(hit[..., None], rgb, sky)
        depth = torch.where(hit, depth.clamp(min=0.05), torch.zeros_like(depth))
        return depth.cpu().numpy(), rgb.cpu().numpy()

    def capture(self, drone: int, t: float, pos: np.ndarray, rot: np.ndarray, omega: np.ndarray | None = None,
                chunk: int = 6) -> FramePacket:
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

        rgb = M.COLORS[hit_mat].astype(np.float32) * shade[:, None]
        rgb = np.where(hit[:, None], rgb, np.array([18.0, 22.0, 30.0]))  # no return: dark
        depth = np.where(hit, np.maximum(depth, 0.05), 0.0)
        img = self._degrade(rgb.reshape(k.h, k.w, 3), self.b.inside_building(pos[None, :])[0], omega)
        size = int(self.jpeg_bytes * self.rng.uniform(0.8, 1.2))
        return FramePacket(drone, t, img, size,
                           sim_truth={"pos": pos.copy(), "rot": rot.copy(),
                                      "depth": depth.reshape(k.h, k.w).astype(np.float32)})

    def _degrade(self, img: np.ndarray, indoors: bool, omega) -> np.ndarray:
        """Toy-camera + JPEG artifacts on a float RGB image (H, W, 3)."""
        h, w, _ = img.shape
        # Motion blur: average with copies shifted by the image motion during exposure.
        if omega is not None:
            px_per_rad = w / np.deg2rad(self.hfov_deg)
            dx = int(round(abs(omega[2]) * EXPOSURE_S * px_per_rad))
            dy = int(round(abs(omega[1]) * EXPOSURE_S * px_per_rad))
            if dx or dy:
                img = (img + np.roll(img, (dy, dx), axis=(0, 1)) + np.roll(img, (dy // 2, dx // 2), axis=(0, 1))) / 3
        # Sensor gain noise (auto exposure indoors raises the gain).
        sigma = GAIN_NOISE_INDOOR if indoors else GAIN_NOISE_OUTDOOR
        img = img * (1.0 + self.rng.normal(0.0, sigma, (h, w, 1))) + self.rng.normal(0.0, sigma * 60, (h, w, 3))
        # JPEG: 2x2 chroma subsampling (blend toward block mean) and coarse quantization.
        hb, wb = h - h % 2, w - w % 2
        blk = img[:hb, :wb].reshape(hb // 2, 2, wb // 2, 2, 3).mean(axis=(1, 3))
        img[:hb, :wb] = 0.6 * img[:hb, :wb] + 0.4 * np.repeat(np.repeat(blk, 2, 0), 2, 1)
        img = np.round(img / JPEG_STEP) * JPEG_STEP
        return np.clip(img, 0, 255).astype(np.uint8)
