"""Frame-to-map alignment on the central node, batched on the GPU.

Before frames are fused, each one's back-projected depth points are registered against the
smoothed point cloud (point-to-plane Gauss-Newton), solving for a small pose correction and
the depth network's scale error for that frame, so a re-pass over an area lands on top of the
earlier scan instead of beside it. All frames of a batch are solved together (batched 7x7
normal equations). The correction is also fed back to the VIO, but only the directions the
view actually constrains (one wall pins only the shift along its normal), and only when the
matched points were mapped by other drones (a drone must not chase its own drift).

The solve is a MAP estimate: priors keep it from moving along directions the surfaces in
view do not constrain.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from .voxelmap import NBR_CENTER, POINT_CELL, VoxelMap

SIGMA_R = 0.10  # residual noise (m)
SIGMA_T, SIGMA_ROT, SIGMA_S = 0.5, 0.05, 0.04  # priors: translation (m), rotation (rad), log scale
HUBER = 0.25
MAX_DIST = 0.6  # correspondence search is limited to the 3x3x3 cells around a point
MIN_INLIERS = 50
SUBSAMPLE = 3  # use every third pixel: enough constraints, a third of the lookups
OBSERVABLE = 4.0  # data information must be this many times the prior's for a direction to count as observed
TRUST_AGE_S = 8.0
MAX_T, MAX_ROT, MAX_S = 1.5, float(np.deg2rad(10)), 0.15
ITERS = 4
_OFF = np.array([(a, b, c) for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)])


@dataclass
class Alignment:
    dp: np.ndarray  # camera position correction (m)
    rot: np.ndarray  # world rotation correction (3x3)
    scale: float  # multiply depth by this
    inliers: int
    obs_dp: np.ndarray  # the part of the correction the view actually constrains
    obs_dyaw: float
    cross: float  # share of the matched points that another drone mapped
    rms_before: float
    rms_after: float

    @property
    def dyaw(self) -> float:
        return float(np.arctan2(self.rot[1, 0], self.rot[0, 0]))


def _skew(w: torch.Tensor) -> torch.Tensor:
    z = torch.zeros_like(w[..., 0])
    return torch.stack([torch.stack([z, -w[..., 2], w[..., 1]], -1),
                        torch.stack([w[..., 2], z, -w[..., 0]], -1),
                        torch.stack([-w[..., 1], w[..., 0], z], -1)], -2)


def _rodrigues(w: torch.Tensor) -> torch.Tensor:
    th = w.norm(dim=-1, keepdim=True).clamp_min(1e-9)
    K = _skew(w)
    a = (torch.sin(th) / th)[..., None]
    b = ((1 - torch.cos(th)) / th ** 2)[..., None]
    return torch.eye(3, device=w.device) + a * K + b * (K @ K)


def _log_so3(R: torch.Tensor) -> torch.Tensor:
    tr = R[..., 0, 0] + R[..., 1, 1] + R[..., 2, 2]
    th = torch.acos(torch.clamp((tr - 1) / 2, -1, 1))
    vec = torch.stack([R[..., 2, 1] - R[..., 1, 2], R[..., 0, 2] - R[..., 2, 0], R[..., 1, 0] - R[..., 0, 1]], -1)
    k = torch.where(th > 1e-6, th / (2 * torch.sin(th).clamp_min(1e-9)), torch.full_like(th, 0.5))
    return vec * k[..., None]


@torch.no_grad()
def align_batch(m: VoxelMap, cams: torch.Tensor, dirs: torch.Tensor, depth: torch.Tensor, t: torch.Tensor,
                drone: torch.Tensor) -> list[Alignment | None]:
    """Register B frames at once. cams (B,3) camera positions, dirs (B,N,3) world ray
    directions, depth (B,N) metres (0 = none), t (B,) capture times, drone (B,) ids."""
    B, N = depth.shape
    dev = depth.device
    out: list[Alignment | None] = [None] * B
    if m.npts < 200:
        return out
    idx = torch.arange(0, N, SUBSAMPLE, device=dev)
    d = depth[:, idx]
    dr = dirs[:, idx]
    hit = (d > 0) & (d <= 10.0)
    a0 = dr * d[..., None]  # camera-relative points
    pts = cams[:, None, :] + a0

    # ---- nearest trusted smoothed point (with a plane normal) in the 3x3x3 cells around each point
    off = torch.as_tensor(_OFF, device=dev)
    cells = torch.floor(pts / POINT_CELL).long()
    nb = cells[:, :, None, :] + off[None, None, :, :]
    ok = ((nb >= 0) & (nb < m._pcell_t)).all(-1)
    py, pz = int(m.pcell[1]), int(m.pcell[2])
    key = (nb[..., 0] * py + nb[..., 1]) * pz + nb[..., 2]
    pid = torch.where(ok, m.pidx[torch.where(ok, key, torch.zeros_like(key))].long(), torch.full_like(key, -1))
    have = pid >= 0
    pid0 = torch.where(have, pid, torch.zeros_like(pid))
    trusted = (t[:, None, None] - m.pt0[pid0] > TRUST_AGE_S) | (m.pdrone[pid0] != drone[:, None, None])
    have = have & trusted & (m.pnorm[pid0].abs().sum(-1) > 0) & ~m.hidden(pid0.reshape(-1)).reshape(pid0.shape)
    d2 = ((m.spos[pid0] - pts[:, :, None, :]) ** 2).sum(-1)
    d2 = torch.where(have, d2, torch.full_like(d2, float("inf")))
    mind, best = d2.min(2)
    sel = pid0.gather(2, best[..., None])[..., 0]
    good = hit & torch.isfinite(mind) & (mind < MAX_DIST ** 2)
    tgt, nrm = m.spos[sel], m.pnorm[sel]
    other = m.pdrone[sel] != drone[:, None].to(m.pdrone.dtype)
    ngood = good.sum(1)

    # ---- batched Gauss-Newton with priors
    prior = torch.diag(torch.as_tensor([1 / SIGMA_ROT ** 2] * 3 + [1 / SIGMA_T ** 2] * 3 + [1 / SIGMA_S ** 2],
                                       device=dev, dtype=torch.float32))
    a = a0.clone()
    R_tot = torch.eye(3, device=dev).expand(B, 3, 3).clone()
    t_tot = torch.zeros((B, 3), device=dev)
    s_tot = torch.zeros(B, device=dev)
    gf = good.float()
    rms0 = None
    Hd = None
    for _ in range(ITERS):
        r = (((cams[:, None, :] + a - tgt) * nrm).sum(-1)) * gf
        if rms0 is None:
            rms0 = torch.sqrt((r ** 2).sum(1) / ngood.clamp_min(1))
        w = torch.where(r.abs() < HUBER, torch.ones_like(r), HUBER / r.abs().clamp_min(1e-9)) * gf
        J = torch.cat([torch.cross(a, nrm, dim=-1), nrm, (nrm * a).sum(-1, keepdim=True)], dim=-1)  # (B,M,7)
        Hd = torch.einsum("bmi,bm,bmj->bij", J, w, J) / SIGMA_R ** 2
        x_acc = torch.cat([_log_so3(R_tot), t_tot, s_tot[:, None]], dim=-1)
        rhs = -torch.einsum("bmi,bm,bm->bi", J, w, r) / SIGMA_R ** 2 - x_acc @ prior.T
        dx = torch.linalg.solve(Hd + prior, rhs[..., None])[..., 0]
        dR = _rodrigues(dx[:, :3])
        a = torch.einsum("bij,bmj->bmi", dR, a * (1 + dx[:, 6])[:, None, None]) + dx[:, None, 3:6]
        R_tot = dR @ R_tot
        t_tot = torch.einsum("bij,bj->bi", dR, t_tot) + dx[:, 3:6]
        s_tot = (1 + s_tot) * (1 + dx[:, 6]) - 1
    r = (((cams[:, None, :] + a - tgt) * nrm).sum(-1)) * gf
    rms1 = torch.sqrt((r ** 2).sum(1) / ngood.clamp_min(1))
    inl = ((r.abs() < HUBER) & good).sum(1)
    ang = _log_so3(R_tot).norm(dim=-1)
    accept = ((ngood >= MIN_INLIERS) & (inl >= MIN_INLIERS) & (rms1 <= 0.9 * rms0)
              & (t_tot.norm(dim=-1) <= MAX_T) & (ang <= MAX_ROT) & (s_tot.abs() <= MAX_S))

    # ---- which directions did this view constrain? (depth scale eliminated first: a shift along
    # a wall's normal and a change of scale look alike)
    pw = torch.sqrt(torch.diagonal(prior))[:6]
    Hs = Hd[:, :6, :6] - Hd[:, :6, 6:7] * Hd[:, 6:7, :6] / (Hd[:, 6, 6] + prior[6, 6])[:, None, None]
    lam, V = torch.linalg.eigh(Hs / pw[:, None] / pw[None, :])
    keep = (lam >= OBSERVABLE).float()
    x = torch.cat([_log_so3(R_tot), t_tot], dim=-1) * pw
    xo = torch.einsum("bij,bj->bi", V, keep * torch.einsum("bji,bj->bi", V, x)) / pw
    cross = ((other & good).sum(1).float() / ngood.clamp_min(1))

    h = {k: v.cpu().numpy() for k, v in dict(accept=accept, t=t_tot, R=R_tot, s=1 + s_tot, xo=xo, cross=cross,
                                             inl=inl, rms0=rms0, rms1=rms1).items()}
    for b in range(B):
        if h["accept"][b]:
            out[b] = Alignment(h["t"][b], h["R"][b], float(h["s"][b]), int(h["inl"][b]), h["xo"][b, 3:6],
                               float(h["xo"][b, 2]), float(h["cross"][b]), float(h["rms0"][b]), float(h["rms1"][b]))
    return out
