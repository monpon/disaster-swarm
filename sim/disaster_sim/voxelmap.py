"""The master's 3D reconstruction, built only from camera frames.

Each frame is back-projected with its pose: space along every ray is carved free, the
surface it hit is marked occupied and colored. Materials are classified from the
averaged color (the master's "segmentation"), and every surface voxel keeps its best
scan quality (closer = better) and the last time it was properly scanned.
"""
from __future__ import annotations

import numpy as np

from . import materials as M
from .camera import STEP, Frame, Intrinsics
from .config import SimConfig

HIT, MISS = 6, 2
LO_MIN, LO_MAX = -30, 40
OCC_T, FREE_T = 4, -3
POINT_CELL = 0.25  # point cloud: at most one point per 25 cm cell (voxel-grid filter)
POINT_UNIT = 0.05  # point positions are stored/sent in 5 cm units (uint16)
POINT_MAX_RANGE = 10.0  # depth beyond this is too noisy to keep as points

# Classify in a brightness-normalized space so shading changes matter less than hue.
_PAL = M.COLORS.astype(np.float32)
_CLASSIFIABLE = np.array([m for m in range(1, M.N_MATERIALS)])


def classify_colors(rgb: np.ndarray) -> np.ndarray:
    """Nearest palette material for (N,3) mean colors."""
    if len(rgb) == 0:
        return np.zeros(0, dtype=np.uint8)
    pal = _PAL[_CLASSIFIABLE]
    lum = rgb.sum(axis=1, keepdims=True) + 1.0
    plum = pal.sum(axis=1, keepdims=True) + 1.0
    chroma = rgb / lum
    pchroma = pal / plum
    d = (((chroma[:, None, :] - pchroma[None, :, :]) * 600) ** 2).sum(axis=2)
    d += ((np.log(lum) - np.log(plum.T)) * 60) ** 2
    return _CLASSIFIABLE[np.argmin(d, axis=1)].astype(np.uint8)


class ScanQuality:
    def __init__(self, near: float, far: float, proper: float):
        self.near, self.far = near, far
        self.threshold = float(self(np.array(proper)))

    def __call__(self, dist: np.ndarray) -> np.ndarray:
        return np.clip(1.0 - (dist - self.near) / (self.far - self.near), 0.0, 1.0)


class VoxelMap:
    def __init__(self, shape: tuple[int, int, int], cfg: SimConfig):
        self.shape = tuple(shape)
        n = int(np.prod(shape))
        self.n = n
        self.strides = np.array([shape[1] * shape[2], shape[2], 1])
        self.lo = np.zeros(n, dtype=np.int16)  # log-odds occupancy
        self.csum = np.zeros((n, 3), dtype=np.float32)
        self.cnt = np.zeros(n, dtype=np.uint16)
        self.mat = np.zeros(n, dtype=np.uint8)
        self.quality = np.zeros(n, dtype=np.float32)
        self.seen = np.full(n, -1.0, dtype=np.float32)  # last proper scan (surfaces)
        self.stamp = np.full(n, -1, dtype=np.int64)  # last change visible to the viewer
        self.k = Intrinsics(cfg)
        self.q = ScanQuality(cfg.scan_near, cfg.cam_range, cfg.proper_scan_range)
        self.frames = 0
        # Colored point cloud back-projected from depth pixels (what the viewer renders).
        self.pcell = np.array([int(np.ceil(d / POINT_CELL)) for d in shape])
        self.pfilled = np.zeros(int(np.prod(self.pcell)), dtype=bool)
        self.pts = np.zeros((65536, 3), dtype=np.uint16)
        self.pcol = np.zeros((65536, 3), dtype=np.uint8)
        self.npts = 0
        self.sparse2d: np.ndarray | None = None  # (sx, sy) columns where ground points are thinned

    def _add_points(self, p: np.ndarray, rgb: np.ndarray) -> None:
        if len(p) == 0:
            return
        c = np.floor(p / POINT_CELL).astype(np.int64)
        ok = ((c >= 0) & (c < self.pcell)).all(axis=1)
        c, p, rgb = c[ok], p[ok], rgb[ok]
        if self.sparse2d is not None:  # open ground outside the building: every other cell
            ground = (p[:, 2] < 1.15) & self.sparse2d[np.floor(p[:, 0]).astype(int), np.floor(p[:, 1]).astype(int)]
            keep = ~ground | ((c[:, 0] % 2 == 0) & (c[:, 1] % 2 == 0))
            c, p, rgb = c[keep], p[keep], rgb[keep]
        key = (c[:, 0] * self.pcell[1] + c[:, 1]) * self.pcell[2] + c[:, 2]
        key, first = np.unique(key, return_index=True)
        new = ~self.pfilled[key]
        key, first = key[new], first[new]
        if len(key) == 0:
            return
        self.pfilled[key] = True
        n = len(key)
        if self.npts + n > len(self.pts):
            cap = max(len(self.pts) * 2, self.npts + n)
            self.pts = np.resize(self.pts, (cap, 3))
            self.pcol = np.resize(self.pcol, (cap, 3))
        self.pts[self.npts:self.npts + n] = np.rint(p[first] / POINT_UNIT).astype(np.uint16)
        self.pcol[self.npts:self.npts + n] = np.clip(rgb[first], 0, 255).astype(np.uint8)
        self.npts += n

    # ------------------------------------------------------------------ queries
    @property
    def occupied(self) -> np.ndarray:
        return self.lo >= OCC_T

    @property
    def free(self) -> np.ndarray:
        return self.lo <= FREE_T

    @property
    def known(self) -> np.ndarray:
        return self.occupied | self.free

    def flat_of(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Flat indices for world points and a mask of which are inside the grid."""
        ix = np.floor(pts[:, 0]).astype(np.int64)
        iy = np.floor(pts[:, 1]).astype(np.int64)
        iz = np.floor(pts[:, 2]).astype(np.int64)
        sx, sy, sz = self.shape
        inside = (ix >= 0) & (ix < sx) & (iy >= 0) & (iy < sy) & (iz >= 0) & (iz < sz)
        flat = ix * self.strides[0] + iy * self.strides[1] + iz
        return np.where(inside, flat, 0), inside

    def grid(self, arr: np.ndarray) -> np.ndarray:
        return arr.reshape(self.shape)

    # -------------------------------------------------------------- integration
    def integrate(self, f: Frame, tick: int) -> dict:
        """Fuse one frame. Returns survivor-colored hit points (for detection)."""
        self.frames += 1
        k = self.k
        dirs = k.rays(f.rot)
        depth = f.depth.reshape(-1).astype(np.float64)
        rgb = f.rgb.reshape(-1, 3).astype(np.float32)
        hit = depth > 0
        reach = np.where(hit, depth - 0.6, k.range)  # carve up to just before the surface

        ri, si = np.nonzero(k.steps[None, :] < reach[:, None])  # only samples before each hit
        flat, inside = self.flat_of(f.pos[None, :] + dirs[ri] * k.steps[si][:, None])
        free_idx = flat[inside]

        hp = f.pos[None, :] + dirs[hit] * (depth[hit] + 0.15)[:, None]  # nudge into the surface
        flat, inside = self.flat_of(hp)
        hit_idx = flat[inside]
        hit_rgb = rgb[hit][inside]
        hit_d = depth[hit][inside]

        was_occ = self.lo[free_idx] >= OCC_T
        was_unknown = (self.lo[free_idx] > FREE_T) & ~was_occ
        self.lo[free_idx] = np.maximum(self.lo[free_idx] - MISS, LO_MIN)
        now_occ = self.lo[free_idx] >= OCC_T
        now_free = self.lo[free_idx] <= FREE_T
        changed_free = free_idx[(was_occ & ~now_occ) | (was_unknown & now_free)]

        uniq = np.unique(hit_idx)
        old_occ = self.lo[uniq] >= OCC_T
        old_qb = np.floor(self.quality[uniq] * 8)

        self.lo[hit_idx] = np.minimum(self.lo[hit_idx] + HIT, LO_MAX)
        self.csum[hit_idx] += hit_rgb
        self.cnt[hit_idx] = np.minimum(self.cnt[hit_idx].astype(np.int32) + 1, 65000).astype(np.uint16)
        q = self.q(hit_d)
        self.quality[hit_idx] = np.maximum(self.quality[hit_idx], q)
        proper = q >= self.q.threshold
        self.seen[hit_idx[proper]] = f.t

        # Re-classify touched surfaces from their running mean color.
        new_mat = classify_colors(self.csum[uniq] / np.maximum(self.cnt[uniq, None], 1))
        mat_changed = new_mat != self.mat[uniq]
        self.mat[uniq] = new_mat
        new_occ = self.lo[uniq] >= OCC_T
        new_qb = np.floor(self.quality[uniq] * 8)
        changed_hit = uniq[(new_occ != old_occ) | (new_occ & (mat_changed | (new_qb > old_qb)))]
        self.stamp[changed_free] = tick
        self.stamp[changed_hit] = tick

        surf = depth[hit] <= POINT_MAX_RANGE
        self._add_points(f.pos[None, :] + dirs[hit][surf] * depth[hit][surf][:, None], rgb[hit][surf])

        # Survivor detection: pixels whose color reads as a person's heat signature.
        surv = (hit_rgb[:, 0] > 190) & (hit_rgb[:, 1] < 90) & (hit_rgb[:, 2] < 110)
        return {"survivor_pts": hp[inside][surv], "survivor_dist": hit_d[surv]}

    # ---------------------------------------------------------------- streaming
    def deltas_since(self, tick: int):
        """(idx, occupied, material, rgb565, quality u8) for voxels changed after `tick`."""
        idx = np.flatnonzero(self.stamp > tick)
        occ = self.lo[idx] >= OCC_T
        mean = self.csum[idx] / np.maximum(self.cnt[idx, None], 1)
        r = (np.clip(mean[:, 0], 0, 255).astype(np.uint16) >> 3) << 11
        g = (np.clip(mean[:, 1], 0, 255).astype(np.uint16) >> 2) << 5
        b = np.clip(mean[:, 2], 0, 255).astype(np.uint16) >> 3
        q = np.rint(self.quality[idx] * 255).astype(np.uint8)
        return idx, occ, self.mat[idx], (r | g | b), q
