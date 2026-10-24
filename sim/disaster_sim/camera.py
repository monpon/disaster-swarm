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
import torch

from . import materials as M
from .building import Building
from .config import SimConfig
from .gpu import DEV
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
    """Renders every drone's frame in one batched GPU ray march, degrades it like a toy
    camera + JPEG stream, and hands the master GPU tensors (the decoded frame)."""

    def __init__(self, building: Building, cfg: SimConfig, rng: np.random.Generator):
        self.b = building
        self.k = Intrinsics(cfg)
        self.rng = rng
        self.hfov_deg = cfg.cam_hfov_deg
        self.jpeg_bytes = cfg.jpeg_bytes
        dev = DEV
        self.dev = dev
        # Pad the world so rays never need bounds checks: below ground is solid asphalt,
        # everywhere else outside the site is air.
        pad = int(np.ceil(cfg.cam_range)) + 2
        sx, sy, sz = building.vox.shape
        padded = np.zeros((sx + 2 * pad, sy + 2 * pad, sz + 2 * pad), dtype=np.uint8)
        padded[:, :, :pad] = M.ASPHALT
        padded[pad:pad + sx, pad:pad + sy, pad:pad + sz] = building.vox
        self.pad = pad
        self.t_flat = torch.as_tensor(padded.reshape(-1), device=dev)
        self.t_strides = torch.as_tensor([padded.shape[1] * padded.shape[2], padded.shape[2], 1], device=dev)
        self.t_steps = torch.as_tensor(self.k.steps, device=dev, dtype=torch.float32)
        self.t_rays = torch.as_tensor(self.k.body_rays, device=dev, dtype=torch.float32)
        self.t_colors = torch.as_tensor(M.COLORS, device=dev).float()
        self.gen = torch.Generator(device=dev)
        self.gen.manual_seed(int(rng.integers(1 << 31)))

    def capture_many(self, items: list, t: float) -> list[FramePacket]:
        """Frames for several drones at once: items are (drone, pos, rot, omega)."""
        if not items:
            return []
        dev = self.dev
        poss = np.stack([p for _, p, _, _ in items])
        rots = np.stack([r for _, _, r, _ in items])
        omega = torch.as_tensor(np.stack([w for _, _, _, w in items]), device=dev, dtype=torch.float32)
        depth, rgb = self._render(poss, rots)
        inside = torch.as_tensor(self.b.inside_building(poss), device=dev)
        img = self._degrade(rgb.view(len(items), self.k.h, self.k.w, 3), inside, omega)  # (B,H,W,3) uint8
        sizes = (self.jpeg_bytes * self.rng.uniform(0.8, 1.2, len(items))).astype(int)
        out = []
        for j, (d, pos, rot, _) in enumerate(items):
            out.append(FramePacket(d, t, img[j], int(sizes[j]),
                                   sim_truth={"pos": pos.copy(), "rot": rot.copy(),
                                              "depth": depth[j].view(self.k.h, self.k.w)}))
        return out

    def _render(self, poss: np.ndarray, rots: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
        """Ray-march (M drones x N pixels x S steps) through the voxel world: first solid
        sample, refined by half a step, shaded by the face the ray crossed. Returns depth
        (M,N) metres (0 = no return) and RGB (M,N,3) floats, both on the device."""
        dev = self.dev
        pos = torch.as_tensor(poss, device=dev, dtype=torch.float32)
        rot = torch.as_tensor(rots, device=dev, dtype=torch.float32)
        dirs = torch.einsum("nk,mjk->mnj", self.t_rays, rot)  # (M, N, 3), world frame
        S, st = self.t_steps, self.t_strides

        def look(points):
            v = torch.floor(points).long()
            return self.t_flat[((v + self.pad) * st).sum(-1)].long(), v

        pts = pos[:, None, None, :] + dirs[:, :, None, :] * S[None, None, :, None]  # (M, N, S, 3)
        mat, _ = look(pts)
        solid = mat != M.AIR
        hit = solid.any(2)
        first = solid.float().argmax(2)  # first solid sample
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
        return depth, rgb

    def _degrade(self, img: torch.Tensor, indoors: torch.Tensor, omega: torch.Tensor) -> torch.Tensor:
        """Toy-camera + JPEG artifacts on a batch of float RGB images (B, H, W, 3)."""
        B, H, W, _ = img.shape
        dev = img.device
        # Motion blur: average with copies shifted by the image motion during exposure.
        px_per_rad = W / np.deg2rad(self.hfov_deg)
        dx = torch.round(omega[:, 2].abs() * EXPOSURE_S * px_per_rad).long()
        dy = torch.round(omega[:, 1].abs() * EXPOSURE_S * px_per_rad).long()
        yy = torch.arange(H, device=dev)[None, :, None]
        xx = torch.arange(W, device=dev)[None, None, :]
        bi = torch.arange(B, device=dev)[:, None, None]

        def shifted(sy, sx):
            return img[bi, (yy - sy[:, None, None]) % H, (xx - sx[:, None, None]) % W]

        blur = (img + shifted(dy, dx) + shifted(dy // 2, dx // 2)) / 3
        img = torch.where(((dx > 0) | (dy > 0))[:, None, None, None], blur, img)
        # Sensor gain noise (auto exposure indoors raises the gain).
        sigma = torch.where(indoors, GAIN_NOISE_INDOOR, GAIN_NOISE_OUTDOOR).float()[:, None, None, None]
        img = img * (1.0 + sigma * torch.randn((B, H, W, 1), device=dev, generator=self.gen)) \
            + torch.randn((B, H, W, 3), device=dev, generator=self.gen) * sigma * 60
        # JPEG: 2x2 chroma subsampling (blend toward block mean) and coarse quantization.
        hb, wb = H - H % 2, W - W % 2
        blk = img[:, :hb, :wb].reshape(B, hb // 2, 2, wb // 2, 2, 3).mean(dim=(2, 4))
        img[:, :hb, :wb] = 0.6 * img[:, :hb, :wb] + 0.4 * blk.repeat_interleave(2, 1).repeat_interleave(2, 2)
        img = torch.round(img / JPEG_STEP) * JPEG_STEP
        return img.clamp(0, 255).to(torch.uint8)
