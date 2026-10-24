"""Radio propagation on the GPU: signal between many pairs of points in one kernel.

Used for the true radio (`radio.py`: every drone pair, through the real building) and for the
master's predictions (`comms.py`: through its own map, plus a coverage field). A link's loss is
free-space loss plus, for every run of solid material the straight segment crosses, a loss set
by the run's dominant material and its thickness.
"""
from __future__ import annotations

import numpy as np
import torch

from . import materials as Mat
from .gpu import DEV
from .radio import GLASS_DB, GROUND_DB, NOISE_DBM, SLAB_DB, THICK_DB_PER_M, TX_DBM, WALL_DB

STEP = 0.5  # m between samples along a link
MAX_RUNS = 12  # solid runs per link that are charged (more is a dead link anyway)
UNKNOWN_DB_PER_SAMPLE = 0.2  # unexplored interior is assumed to have walls in it

_PER = torch.zeros(Mat.N_MATERIALS, device=DEV)
for _m in range(Mat.N_MATERIALS):
    _PER[_m] = (GROUND_DB if _m == Mat.ASPHALT else GLASS_DB if _m == Mat.GLASS
                else SLAB_DB if _m in (Mat.FLOOR, Mat.ROOF) else WALL_DB)


class World:
    """What a link sees: solid cells, their material, and (for predictions) unexplored interior."""

    def __init__(self, shape, occ: torch.Tensor, mat: torch.Tensor, unk: torch.Tensor | None = None,
                 below_ground_solid: bool = False):
        self.shape = tuple(shape)
        self.occ, self.mat, self.unk = occ, mat, unk
        self.below_ground_solid = below_ground_solid  # true world: z < 0 is asphalt

    def sample(self, pts: torch.Tensor):
        sx, sy, sz = self.shape
        ix, iy, iz = (torch.floor(pts[..., k]).long() for k in range(3))
        inside = (ix >= 0) & (ix < sx) & (iy >= 0) & (iy < sy) & (iz >= 0) & (iz < sz)
        flat = torch.where(inside, (ix * sy + iy) * sz + iz, torch.zeros_like(ix))
        occ = self.occ[flat] & inside
        mat = torch.where(inside, self.mat[flat].long(), torch.zeros_like(ix))
        if self.below_ground_solid:
            under = iz < 0
            occ = occ | under
            mat = torch.where(under, torch.full_like(mat, Mat.ASPHALT), mat)
        unk = (self.unk[flat] & inside) if self.unk is not None else None
        return occ, mat, unk


def snr_pairs(world: World, a: torch.Tensor, b: torch.Tensor, chunk: int = 6000) -> torch.Tensor:
    """SNR (dB) between points a[i] and b[i] for P pairs. a, b: (P,3) float32."""
    out = []
    for s in range(0, len(a), chunk):
        out.append(_snr_chunk(world, a[s:s + chunk], b[s:s + chunk]))
    return torch.cat(out) if out else a.new_zeros(0)


def _snr_chunk(world: World, a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
    P = len(a)
    d = (b - a).norm(dim=1)
    n = torch.clamp(torch.floor(d / STEP), min=1)  # samples per link (as in the CPU model)
    S = int(n.max().item())
    k = torch.arange(S, device=a.device)[None, :]
    valid = k < n[:, None]
    t = (k + 0.5) / n[:, None]
    pts = a[:, None, :] + (b - a)[:, None, :] * t[..., None]
    occ, mat, unk = world.sample(pts)
    solid = occ & valid
    prev = torch.zeros_like(solid)
    prev[:, 1:] = solid[:, :-1]
    starts = solid & ~prev
    rid = torch.clamp(torch.cumsum(starts.int(), 1), max=MAX_RUNS) * solid  # run id per solid sample, 0 elsewhere
    R, N = MAX_RUNS + 1, Mat.N_MATERIALS
    pi = torch.arange(P, device=a.device)[:, None].expand_as(rid)
    flat = ((pi * R + rid) * N + mat)[solid]
    counts = torch.bincount(flat, minlength=P * R * N).view(P, R, N)[:, 1:]  # drop the "no run" bin
    run_len = counts.sum(-1).float() * STEP
    major = counts.argmax(-1)
    loss = ((_PER[major] + THICK_DB_PER_M * torch.clamp(run_len - 1.5, min=0.0)) * (run_len > 0)).sum(1)
    if unk is not None:
        loss = loss + UNKNOWN_DB_PER_SAMPLE * (unk & valid).sum(1)
    pl = 40.0 + 20.0 * torch.log10(torch.clamp(d, min=1.0))
    return TX_DBM - pl - loss - NOISE_DBM


class CoverageField:
    """Predicted best signal from a set of backbone nodes to every vertex of a coarse lattice
    (4 m horizontally, 3 m vertically): `covered(p)` asks whether a point is inside coverage.
    Per-node fields are cached and only recomputed when a node moves or the map ages."""

    DX, DZ = 4.0, 3.0

    def __init__(self, shape):
        sx, sy, sz = shape
        self.xs = np.arange(0, sx + self.DX, self.DX)
        self.ys = np.arange(0, sy + self.DX, self.DX)
        self.zs = np.arange(0, sz + self.DZ, self.DZ)
        gx, gy, gz = np.meshgrid(self.xs, self.ys, self.zs, indexing="ij")
        self.verts = torch.as_tensor(np.stack([gx, gy, gz], -1).reshape(-1, 3), dtype=torch.float32, device=DEV)
        self.shape = (len(self.xs), len(self.ys), len(self.zs))
        self.cache: dict[tuple, tuple] = {}  # node key -> (position, time, field tensor)
        self.best = None  # (nx,ny,nz) numpy, max over nodes

    def update(self, world: World, nodes: list[np.ndarray], now: float, max_age: float = 3.0) -> None:
        keep, fields = {}, []
        for i, node in enumerate(nodes):
            node = np.asarray(node, dtype=float)
            hit = None
            for key, (pos, tm, fld) in self.cache.items():
                if np.linalg.norm(pos - node) < 2.0 and now - tm < max_age and key not in keep:
                    hit = (key, pos, tm, fld)
                    break
            if hit is None:
                src = torch.as_tensor(node, dtype=torch.float32, device=DEV)[None, :].expand(len(self.verts), 3)
                fld = snr_pairs(world, src, self.verts)
                key, pos, tm = (len(self.cache), now, i), node, now
                while key in self.cache or key in keep:
                    key = (key[0] + 1, now, i)
                hit = (key, pos, tm, fld)
            keep[hit[0]] = (hit[1], hit[2], hit[3])
            fields.append(hit[3])
        self.cache = keep
        if fields:
            self.best = torch.stack(fields).amax(0).view(self.shape).cpu().numpy()
        else:
            self.best = np.full(self.shape, -100.0)

    def margin(self, p: np.ndarray) -> float:
        """Worst predicted signal among the lattice vertices around p (conservative)."""
        if self.best is None:
            return -100.0
        fx = np.clip(p[0] / self.DX, 0, len(self.xs) - 1.001)
        fy = np.clip(p[1] / self.DX, 0, len(self.ys) - 1.001)
        fz = np.clip(p[2] / self.DZ, 0, len(self.zs) - 1.001)
        ix, iy, iz = int(fx), int(fy), int(fz)
        return float(self.best[ix:ix + 2, iy:iy + 2, iz:iz + 2].min())
