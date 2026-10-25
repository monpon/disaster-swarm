"""Frame-to-map alignment on the central node.

Before a frame is fused, its back-projected depth points are registered against the
smoothed point cloud (point-to-plane Gauss-Newton). That solves for a small pose correction
and the depth network's scale error for this frame, so a re-pass over an area lands on top
of the earlier scan instead of beside it. The correction is also fed back to the VIO.

Only reference points the drone did not just paint itself count: seen by another drone, or
first seen a while ago. The solve is a MAP estimate: priors keep it from moving along
directions the surfaces in view do not constrain (a single wall cannot tell translation
along the wall, or a scale change, from noise).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tests.ref_voxelmap import POINT_CELL, VoxelMap

SIGMA_R = 0.10  # residual noise (m)
SIGMA_T, SIGMA_ROT, SIGMA_S = 0.5, 0.05, 0.04  # priors: translation (m), rotation (rad), log scale
HUBER = 0.25
MAX_DIST = 0.6  # correspondence search is limited to the 3x3x3 cells around a point
MIN_INLIERS = 50
SUBSAMPLE = 3  # use every third pixel: enough constraints, a third of the lookups
OBSERVABLE = 4.0  # data information must be this many times the prior's for a direction to count as observed
TRUST_AGE_S = 8.0
MAX_T, MAX_ROT, MAX_S = 1.5, np.deg2rad(10), 0.15
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


def _rodrigues(w: np.ndarray) -> np.ndarray:
    th = np.linalg.norm(w)
    if th < 1e-9:
        return np.eye(3)
    k = w / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def correspondences(m: VoxelMap, pts: np.ndarray, t: float, drone: int):
    """Nearest trusted smoothed point (with a plane normal) to each point: (mask, target, normal)."""
    c = np.floor(pts / POINT_CELL).astype(np.int64)
    nb = c[:, None, :] + _OFF[None, :, :]
    ok = ((nb >= 0) & (nb < m.pcell)).all(axis=2)
    key = (nb[..., 0] * m.pcell[1] + nb[..., 1]) * m.pcell[2] + nb[..., 2]
    pid = np.where(ok, m.pidx[np.where(ok, key, 0)], -1).astype(np.int64)
    have = pid >= 0
    pid0 = np.where(have, pid, 0)
    trusted = (t - m.pt0[pid0] > TRUST_AGE_S) | (m.pdrone[pid0] != drone)
    have &= trusted & (np.abs(m.pnorm[pid0]).sum(-1) > 0) & ~m.hidden(pid0.reshape(-1)).reshape(pid0.shape)
    d2 = ((m.spos[pid0] - pts[:, None, :]) ** 2).sum(-1)
    d2 = np.where(have, d2, np.inf)
    best = np.argmin(d2, axis=1)
    rows = np.arange(len(pts))
    sel = pid0[rows, best]
    good = np.isfinite(d2[rows, best]) & (d2[rows, best] < MAX_DIST ** 2)
    return good, m.spos[sel], m.pnorm[sel], m.pdrone[sel] != drone


def align_frame(m: VoxelMap, cam: np.ndarray, dirs: np.ndarray, depth: np.ndarray, t: float,
                drone: int) -> Alignment | None:
    """Register one frame. `dirs` (N,3) world ray directions, `depth` (N,) metres (0 = none)."""
    hit = (depth > 0) & (depth <= 10.0)
    hit[np.arange(len(hit)) % SUBSAMPLE != 0] = False
    if hit.sum() < MIN_INLIERS or m.npts < 200:
        return None
    a0 = dirs[hit] * depth[hit][:, None]  # camera-relative points
    good, tgt, nrm, other = correspondences(m, cam + a0, t, drone)
    if good.sum() < MIN_INLIERS:
        return None
    a0, tgt, nrm, other = a0[good], tgt[good], nrm[good], other[good]
    # Residuals are measured against the matches found for the initial pose.
    R_tot, t_tot, s_tot = np.eye(3), np.zeros(3), 0.0
    a = a0.copy()
    prior = np.diag([1 / SIGMA_ROT ** 2] * 3 + [1 / SIGMA_T ** 2] * 3 + [1 / SIGMA_S ** 2])
    rms0 = None
    H = prior.copy()
    for _ in range(ITERS):
        r = ((cam + a - tgt) * nrm).sum(1)
        if rms0 is None:
            rms0 = float(np.sqrt(np.mean(r ** 2)))
        w = np.where(np.abs(r) < HUBER, 1.0, HUBER / np.maximum(np.abs(r), 1e-9))
        J = np.concatenate([np.cross(a, nrm), nrm, (nrm * a).sum(1, keepdims=True)], axis=1)
        H_data = (J * w[:, None]).T @ J / SIGMA_R ** 2
        A = H_data + prior
        # Priors act on the accumulated state, so include its pull in the gradient.
        x_acc = np.r_[_log_so3(R_tot), t_tot, s_tot]
        b = -(J * w[:, None]).T @ r / SIGMA_R ** 2 - prior @ x_acc
        dx = np.linalg.solve(A, b)
        dR = _rodrigues(dx[:3])
        a = dR @ (a * (1 + dx[6])).T
        a = a.T + dx[3:6]
        R_tot, t_tot, s_tot = dR @ R_tot, dR @ t_tot + dx[3:6], (1 + s_tot) * (1 + dx[6]) - 1
    r = ((cam + a - tgt) * nrm).sum(1)
    rms1 = float(np.sqrt(np.mean(r ** 2)))
    inl = int((np.abs(r) < HUBER).sum())
    ang = np.linalg.norm(_log_so3(R_tot))
    if (inl < MIN_INLIERS or rms1 > 0.9 * rms0 or np.linalg.norm(t_tot) > MAX_T or ang > MAX_ROT
            or abs(s_tot) > MAX_S):
        return None
    # Which directions did this view constrain? Whiten by the prior; directions where the data
    # information exceeds the prior's by OBSERVABLE are observed (one wall: only the shift along
    # its normal; a corner: all three axes). Only those parts may feed back into the VIO.
    # The depth scale is a nuisance: a shift along a wall's normal and a change of scale look
    # alike, so eliminate the scale first (Schur complement) before asking what is observed.
    pw = np.sqrt(np.diag(prior))[:6]
    Hs = H_data[:6, :6] - np.outer(H_data[:6, 6], H_data[6, :6]) / (H_data[6, 6] + prior[6, 6])
    lam, V = np.linalg.eigh(Hs / pw[:, None] / pw[None, :])
    keep = lam >= OBSERVABLE
    x = np.r_[_log_so3(R_tot), t_tot]
    xo = (V[:, keep] @ (V[:, keep].T @ (x * pw))) / pw if keep.any() else np.zeros(6)
    return Alignment(t_tot, R_tot, 1.0 + s_tot, inl, xo[3:6], float(xo[2]), float(other.mean()), rms0, rms1)


def _log_so3(R: np.ndarray) -> np.ndarray:
    c = np.clip((np.trace(R) - 1) / 2, -1, 1)
    th = np.arccos(c)
    if th < 1e-9:
        return np.zeros(3)
    return th / (2 * np.sin(th)) * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
