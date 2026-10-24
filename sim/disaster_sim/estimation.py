"""Central-node perception stand-ins: visual-inertial odometry and monocular depth.

On real hardware the master runs VIO on each drone's JPEG frames + IMU batches, and a
learned monocular depth network (scaled metrically by VIO) on each frame. Neither runs
here; instead these classes reproduce their characteristic errors from `sim_truth`, and
are the only code that reads it:

* VIO drifts with distance flown (position random walk plus a slowly wandering heading
  error that bends the estimated path), snaps back toward an earlier estimate when the
  drone revisits a place (loop closure), and re-anchors near the base station, where
  fiducials around the landing pads give absolute fixes.
* The depth network is smooth and roughly right: per-frame scale error, blocky per-region
  errors, a little pixel noise, smeared depth edges, and nothing trustworthy beyond
  `depth_max` metres.
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F

KEYFRAME_SPACING = 3.0
LOOP_RADIUS = 2.0
LOOP_MIN_AGE = 30.0
LOOP_GAIN = 0.15  # fraction of the discrepancy corrected per update while revisiting
BASE_FIX_RADIUS = 12.0
MAX_KEYFRAMES = 600


def rot_z(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class SimulatedVIO:
    def __init__(self, n: int, cfg, base, rng: np.random.Generator):
        self.n = n
        self.rng = rng
        self.base = np.asarray(base, dtype=float)
        self.sigma_p = cfg.vio_drift  # m per sqrt(m) flown
        self.sigma_yaw = cfg.vio_yaw_drift  # rad per sqrt(m) flown
        self.err_p = np.zeros((n, 3))
        self.err_yaw = np.zeros(n)
        self.baro_bias = np.zeros(n)  # the barometer's slow offset (m)
        self.last_t = np.full(n, -1.0)
        self.prev = [None] * n  # previous true position
        # Keyframes per drone: time, true position, estimate error then (ring buffer).
        self.kf_t = np.full((n, MAX_KEYFRAMES), -1e9)
        self.kf_p = np.full((n, MAX_KEYFRAMES, 3), 1e9)
        self.kf_err = np.zeros((n, MAX_KEYFRAMES, 4))
        self.kf_n = np.zeros(n, dtype=int)
        self.kf_last = np.full((n, 3), 1e9)

    def update(self, i: int, t: float, truth: dict) -> None:
        p = np.asarray(truth["pos"], dtype=float)
        prev = self.prev[i]
        self.prev[i] = p.copy()
        if truth.get("grounded") and np.linalg.norm(p[:2] - self.base[:2]) < BASE_FIX_RADIUS + 15:
            self.err_p[i] *= 0.0  # parked on a pad: known position
            self.err_yaw[i] = 0.0
            return
        if prev is None:
            return
        # The drone's barometer bounds the vertical drift: the estimate's height error relaxes
        # toward the barometer's own (small, slowly wandering) offset.
        dtk = 0.0 if self.last_t[i] < 0 else max(t - self.last_t[i], 0.0)
        self.last_t[i] = t
        self.baro_bias[i] = float(np.clip(self.baro_bias[i] + self.rng.normal(0.0, 0.03 * np.sqrt(dtk)), -0.4, 0.4))
        self.err_p[i, 2] += (self.baro_bias[i] - self.err_p[i, 2]) * min(1.0, dtk / 6.0)
        step = p - prev
        dist = float(np.linalg.norm(step))
        if dist > 1e-4:
            # Heading error bends the integrated path; noise grows with distance.
            bent = rot_z(self.err_yaw[i]) @ step - step
            self.err_p[i] += bent + self.rng.normal(0.0, self.sigma_p * np.sqrt(dist), 3) * [1.0, 1.0, 0.5]
            self.err_yaw[i] += self.rng.normal(0.0, self.sigma_yaw * np.sqrt(dist))
        # Absolute fixes near the base station (pad fiducials, known building corners).
        d_base = np.linalg.norm(p - self.base)
        if d_base < BASE_FIX_RADIUS:
            self.err_p[i] *= 0.9
            self.err_yaw[i] *= 0.9
        # Loop closure: revisiting a keyframe pulls the estimate back to agree with it.
        if np.linalg.norm(p - self.kf_last[i]) > KEYFRAME_SPACING:
            k = self.kf_n[i] % MAX_KEYFRAMES
            self.kf_t[i, k], self.kf_p[i, k] = t, p
            self.kf_err[i, k, :3], self.kf_err[i, k, 3] = self.err_p[i], self.err_yaw[i]
            self.kf_n[i] += 1
            self.kf_last[i] = p
        near = (np.einsum("ij,ij->i", self.kf_p[i] - p, self.kf_p[i] - p) < LOOP_RADIUS ** 2) \
            & (t - self.kf_t[i] > LOOP_MIN_AGE)
        if near.any():
            ke = self.kf_err[i, np.flatnonzero(near)[0]]
            self.err_p[i] += (ke[:3] - self.err_p[i]) * LOOP_GAIN
            self.err_yaw[i] += (ke[3] - self.err_yaw[i]) * LOOP_GAIN

    def correct(self, i: int, dp: np.ndarray, dyaw: float, gain: float = 0.3) -> None:
        """A map-relative fix from the master (frame-to-map alignment): shift the estimate."""
        self.err_p[i] += gain * np.asarray(dp)
        self.err_yaw[i] += gain * dyaw

    def pose(self, i: int, truth: dict) -> tuple[np.ndarray, np.ndarray]:
        """Estimated (position, body-to-world rotation) for a truth pose of drone i."""
        p = np.asarray(truth["pos"], dtype=float) + self.err_p[i]
        rot = rot_z(self.err_yaw[i]) @ np.asarray(truth["rot"], dtype=float)
        return p, rot

    def velocity(self, i: int, truth: dict) -> np.ndarray:
        return rot_z(self.err_yaw[i]) @ np.asarray(truth["vel"], dtype=float) + self.rng.normal(0.0, 0.05, 3)

    def drift(self, i: int) -> float:
        return float(np.linalg.norm(self.err_p[i]))


class SimulatedDepthNet:
    def __init__(self, cfg, rng: np.random.Generator):
        self.rng = rng
        from .gpu import DEV
        self.dev = DEV
        self.gen = torch.Generator(device=DEV)
        self.gen.manual_seed(int(rng.integers(1 << 31)))
        self.scale_sigma = cfg.depth_scale_sigma
        self.region_sigma = cfg.depth_region_sigma
        self.depth_max = cfg.depth_max

    def estimate(self, depth: np.ndarray, thumb: bool = False) -> np.ndarray:
        """Monocular depth estimate (H, W) for a frame whose true depth is `depth` (0 = no
        return / sky). Returns 0 where the estimate should not be trusted."""
        h, w = depth.shape
        valid = depth > 0
        d = np.where(valid, depth, 0.0)
        # Depth networks smooth across object boundaries: blend with a 3x3 box blur.
        pad = np.pad(np.where(valid, d, np.nan), 1, mode="edge")
        win = np.stack([pad[y:y + h, x:x + w] for y in range(3) for x in range(3)])
        ok = ~np.isnan(win)
        blur = np.where(ok, win, 0.0).sum(axis=0) / np.maximum(ok.sum(axis=0), 1)
        d = np.where(valid, 0.75 * d + 0.25 * np.nan_to_num(blur, nan=0.0), 0.0)
        # Per-frame scale error and blocky region errors (4x4 pixel blocks).
        q = 1.6 if thumb else 1.0  # a thumbnail gives the depth network less to go on
        scale = np.exp(self.rng.normal(0.0, self.scale_sigma * q))
        bh, bw = -(-h // 4), -(-w // 4)
        region = np.repeat(np.repeat(self.rng.normal(0.0, self.region_sigma * q, (bh, bw)), 4, 0), 4, 1)[:h, :w]
        noise = self.rng.normal(0.0, 0.02, (h, w))
        est = d * scale * (1.0 + region + noise)
        return np.where(valid & (est > 0.1) & (est < self.depth_max), est, 0.0).astype(np.float32)

    @torch.no_grad()
    def estimate_batch(self, depth: torch.Tensor, thumb: list[bool]) -> torch.Tensor:
        """Monocular depth estimates for B frames at once. depth (B,H,W) true depth (0 = no
        return / sky); returns (B,H,W) float32, 0 where the estimate should not be trusted."""
        B, H, W = depth.shape
        dev = depth.device
        valid = depth > 0
        d = torch.where(valid, depth, torch.zeros_like(depth))
        # Depth networks smooth across object boundaries: blend with a 3x3 box blur (valid pixels only).
        pad = F.pad(torch.where(valid, d, torch.full_like(d, float("nan")))[:, None], (1, 1, 1, 1), mode="replicate")[:, 0]
        win = torch.stack([pad[:, y:y + H, x:x + W] for y in range(3) for x in range(3)])
        ok = ~torch.isnan(win)
        blur = torch.where(ok, win, torch.zeros_like(win)).sum(0) / ok.sum(0).clamp_min(1)
        d = torch.where(valid, 0.75 * d + 0.25 * blur, torch.zeros_like(d))
        # Per-frame scale error and blocky region errors (4x4 pixel blocks); thumbnails are worse.
        q = torch.where(torch.as_tensor(thumb, device=dev), 1.6, 1.0).float()[:, None, None]
        scale = torch.exp(torch.randn((B, 1, 1), device=dev, generator=self.gen) * self.scale_sigma * q)
        bh, bw = -(-H // 4), -(-W // 4)
        region = torch.randn((B, bh, bw), device=dev, generator=self.gen) * self.region_sigma * q
        region = region.repeat_interleave(4, 1).repeat_interleave(4, 2)[:, :H, :W]
        noise = torch.randn((B, H, W), device=dev, generator=self.gen) * 0.02
        est = d * scale * (1.0 + region + noise)
        return torch.where(valid & (est > 0.1) & (est < self.depth_max), est, torch.zeros_like(est)).float()
