"""The master's 3D reconstruction, built only from camera frames.

Each frame is back-projected with its pose: space along every ray is carved free, the
surface it hit is marked occupied and colored. Materials are classified from the
averaged color (the master's "segmentation"), and every surface voxel keeps its best
scan quality (closer = better) and the last time it was properly scanned.
"""
from __future__ import annotations

import numpy as np

from disaster_sim import materials as M
from disaster_sim.camera import STEP, Frame, Intrinsics
from disaster_sim.config import SimConfig

HIT, MISS = 6, 2
LO_MIN, LO_MAX = -30, 40
OCC_T, FREE_T = 4, -3
POINT_CELL = 0.25  # point cloud: at most one point per 25 cm cell (voxel-grid filter)
POINT_UNIT = 0.05  # point positions are stored/sent in 5 cm units (uint16)
POINT_MAX_RANGE = 10.0  # depth beyond this is too noisy to keep as points
GHOST_MARGIN = 1.0  # a ray must pass this far in front of its hit to contradict a point
PASS_GAP_S = 15.0  # a surface seen again after this long counts as a new pass
PASS_RANGE = 8.0  # only close views count as a pass
NBR = np.array([(a, b, c) for a in range(-2, 3) for b in range(-2, 3) for c in range(-2, 3)])  # 5x5x5 cells
NBR_CENTER = 62

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
        self.carve_max = min(cfg.depth_max, cfg.cam_range)
        self.frames = 0
        # Point cloud back-projected from depth pixels. One point per 25 cm cell, refined by
        # every view that lands in the cell (weighted by 1/range^2); the smoother then pulls
        # points onto the surfaces they sit on. Arrays are indexed by point id.
        self.pcell = np.array([int(np.ceil(d / POINT_CELL)) for d in shape])
        self.pidx = np.full(int(np.prod(self.pcell)), -1, dtype=np.int32)  # cell -> point id
        self.npts = 0
        self._pcap = 0
        self._palloc(1 << 16)
        self.sparse2d: np.ndarray | None = None  # (sx, sy) columns where ground points are thinned
        # Per-voxel pass tracking (for re-scan planning).
        self.npass = np.zeros(n, dtype=np.uint8)  # distinct close views
        self.vdir = np.zeros(n, dtype=np.uint8)  # sides (+-x/y/z) the surface was seen from
        self.lastpass = np.full(n, -1e9, dtype=np.float32)
        self.pvox = np.zeros(n, dtype=np.uint16)  # points per 1 m voxel (is there a surface here?)
        self.vres = np.zeros(n, dtype=np.float32)  # smoother's local roughness (m)
        self._rng = np.random.default_rng(3)
        self.align_ok = 0
        self.align_n = 0

    _PFIELDS = {
        "psum": (np.float32, 3), "pw": (np.float32, ()), "pcsum": (np.float32, 3),
        "praw": (np.float32, 3), "spos": (np.float32, 3), "pnorm": (np.float32, 3),
        "presid": (np.float32, ()), "pt0": (np.float32, ()),
        "nview": (np.uint16, ()), "pdir": (np.uint8, ()), "pmiss": (np.uint8, ()), "phid": (np.uint8, ()),
        "pdrone": (np.int16, ()), "pcol": (np.uint8, 3),
        "pver": (np.uint32, ()), "prv": (np.uint32, ()), "pdirty": (np.bool_, ()),
    }

    def _palloc(self, cap: int) -> None:
        for name, (dt, dim) in self._PFIELDS.items():
            new = np.zeros((cap,) + ((dim,) if dim else ()), dtype=dt)
            if self._pcap:
                new[:self._pcap] = getattr(self, name)[:self._pcap]
            setattr(self, name, new)
        self._pcap = cap

    @property
    def pts(self) -> np.ndarray:
        """Raw point positions in 5 cm units (uint16), as streamed."""
        return np.rint(self.praw[:self.npts] / POINT_UNIT).astype(np.uint16)

    def hidden(self, ids: np.ndarray) -> np.ndarray:
        """Points that the smoother called outliers, or that rays have repeatedly passed through."""
        ghost = (self.pmiss[ids] >= 3) & (self.pmiss[ids].astype(np.int32) > self.nview[ids])
        return (self.phid[ids] > 0) | ghost

    def _add_points(self, p: np.ndarray, rgb: np.ndarray, d: np.ndarray, side: np.ndarray, t: float, drone: int) -> None:
        """Fold one frame's surface points into the cloud (one update per cell per frame)."""
        if len(p) == 0:
            return
        c = np.floor(p / POINT_CELL).astype(np.int64)
        ok = ((c >= 0) & (c < self.pcell)).all(axis=1)
        c, p, rgb, d, side = c[ok], p[ok], rgb[ok], d[ok], side[ok]
        if self.sparse2d is not None:  # open ground outside the building: every other cell
            ground = (p[:, 2] < 1.15) & self.sparse2d[np.floor(p[:, 0]).astype(int), np.floor(p[:, 1]).astype(int)]
            keep = ~ground | ((c[:, 0] % 2 == 0) & (c[:, 1] % 2 == 0))
            c, p, rgb, d, side = c[keep], p[keep], rgb[keep], d[keep], side[keep]
        if len(c) == 0:
            return
        key = (c[:, 0] * self.pcell[1] + c[:, 1]) * self.pcell[2] + c[:, 2]
        uk, inv = np.unique(key, return_inverse=True)
        ng = len(uk)
        w = 1.0 / np.maximum(d, 1.0) ** 2
        sw = np.bincount(inv, w, ng)
        sp = np.stack([np.bincount(inv, w * p[:, a], ng) for a in range(3)], axis=1)
        sc = np.stack([np.bincount(inv, w * rgb[:, a], ng) for a in range(3)], axis=1)
        bits = np.zeros(ng, dtype=np.uint8)
        np.bitwise_or.at(bits, inv, (1 << side).astype(np.uint8))

        idx = self.pidx[uk].astype(np.int64)
        new = idx < 0
        n_new = int(new.sum())
        if n_new:
            if self.npts + n_new > self._pcap:
                self._palloc(max(self._pcap * 2, self.npts + n_new))
            ids = np.arange(self.npts, self.npts + n_new)
            self.pidx[uk[new]] = ids
            idx[new] = ids
            self.pt0[ids] = t
            self.pdrone[ids] = drone
            self.npts += n_new
        old_raw = self.praw[idx].copy()
        self.psum[idx] += sp
        self.pw[idx] += sw
        self.pcsum[idx] += sc
        self.nview[idx] = np.minimum(self.nview[idx].astype(np.int32) + 1, 65000)
        self.pdir[idx] |= bits
        self.praw[idx] = self.psum[idx] / self.pw[idx, None]
        self.pcol[idx] = np.clip(self.pcsum[idx] / self.pw[idx, None], 0, 255)
        if n_new:
            self.spos[idx[new]] = self.praw[idx[new]]
            fl, ins = self.flat_of(self.praw[idx[new]])
            np.add.at(self.pvox, fl[ins], 1)
        self.spos[idx[~new]] += self.praw[idx[~new]] - old_raw[~new]  # keep the smoothing offset
        self.prv[idx] += 1
        self.pver[idx] += 1
        self.pdirty[idx] = True

    def _ghost(self, pos: np.ndarray) -> None:
        """Rays that pass well in front of their hit contradict any point they cross."""
        c = np.floor(pos / POINT_CELL).astype(np.int64)
        ok = ((c >= 0) & (c < self.pcell)).all(axis=1)
        c = c[ok]
        pid = self.pidx[(c[:, 0] * self.pcell[1] + c[:, 1]) * self.pcell[2] + c[:, 2]]
        pid = np.unique(pid[pid >= 0])
        if len(pid):
            self.pmiss[pid] = np.minimum(self.pmiss[pid].astype(np.int32) + 1, 250)
            self.pver[pid] += 1

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
    def integrate(self, f: Frame, tick: int, drone: int = 0) -> dict:
        """Fuse one frame. Returns survivor-colored hit points (for detection)."""
        self.frames += 1
        k = self.k
        dirs = k.rays(f.rot)
        depth = f.depth.reshape(-1).astype(np.float64)
        rgb = f.rgb.reshape(-1, 3).astype(np.float32)
        hit = depth > 0
        # Carve up to just before the surface; pixels without a trusted depth only out to
        # the depth network's reliable range.
        reach = np.where(hit, depth - 0.6, self.carve_max)

        ri, si = np.nonzero(k.steps[None, :] < reach[:, None])  # only samples before each hit
        samples = f.pos[None, :] + dirs[ri] * k.steps[si][:, None]
        flat, inside = self.flat_of(samples)
        free_idx = flat[inside]
        ghost = hit[ri] & (k.steps[si] < depth[ri] - GHOST_MARGIN)
        if ghost.any():
            self._ghost(samples[ghost])

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

        # Passes: a surface counts as re-scanned when it is seen from close, from a new side
        # or after a pause (a fresh visit rather than the next frame of the same look).
        close = hit_d <= PASS_RANGE
        if close.any():
            ci = hit_idx[close]
            look = -dirs[hit][inside][close]
            axis = np.argmax(np.abs(look), axis=1)
            side = axis * 2 + (look[np.arange(len(axis)), axis] < 0)
            u, first = np.unique(ci, return_index=True)
            bit = (1 << side[first]).astype(np.uint8)
            fresh = ((self.vdir[u] & bit) == 0) | (f.t - self.lastpass[u] > PASS_GAP_S)
            self.npass[u[fresh]] = np.minimum(self.npass[u[fresh]] + 1, 250)
            self.lastpass[u[fresh]] = f.t
            self.vdir[u] |= bit

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
        dh = dirs[hit][surf]
        ax = np.argmax(np.abs(dh), axis=1)
        side = ax * 2 + (dh[np.arange(len(ax)), ax] > 0)  # side of the surface facing the camera
        self._add_points(f.pos[None, :] + dh * depth[hit][surf][:, None], rgb[hit][surf], depth[hit][surf], side,
                         f.t, drone)

        # Survivor detection: pixels whose color reads as a person's heat signature.
        # (ratios, not absolute levels: robust to the camera's gain noise and exposure)
        r_ = hit_rgb[:, 0]
        surv = (r_ > 150) & (hit_rgb[:, 1] < 0.33 * r_) & (hit_rgb[:, 2] < 0.45 * r_)
        return {"survivor_pts": hp[inside][surv], "survivor_dist": hit_d[surv]}


    # ---------------------------------------------------------------- smoothing
    def smooth_job(self, max_n: int = 15000) -> dict | None:
        """Snapshot of the dirty points and their neighbourhoods for the smoothing worker."""
        ids = np.flatnonzero(self.pdirty[:self.npts])
        if len(ids) == 0:
            return None
        if len(ids) > max_n:  # fair share of a backlog
            ids = np.sort(self._rng.choice(ids, max_n, replace=False))
        self.pdirty[ids] = False
        c = np.floor(self.praw[ids] / POINT_CELL).astype(np.int64)
        nb = c[:, None, :] + NBR[None, :, :]
        ok = ((nb >= 0) & (nb < self.pcell)).all(axis=2)
        key = (nb[..., 0] * self.pcell[1] + nb[..., 1]) * self.pcell[2] + nb[..., 2]
        pid = np.where(ok, self.pidx[np.where(ok, key, 0)], -1)
        valid = pid >= 0
        pid = np.where(valid, pid, 0)
        valid &= (self.phid[pid] == 0) | (np.arange(125)[None, :] == NBR_CENTER)
        return {"ids": ids, "rv": self.prv[ids].copy(), "pos": self.praw[pid], "valid": valid, "w": self.pw[pid]}

    def apply_smoothing(self, job: dict, out: dict) -> int:
        """Merge a worker result. Points that changed since the snapshot stay dirty."""
        ids = job["ids"]
        cur = self.prv[ids] == job["rv"]
        self.pdirty[ids[~cur]] = True
        ids, sel = ids[cur], np.flatnonzero(cur)
        if len(ids) == 0:
            return 0
        self.spos[ids] = out["spos"][sel]
        self.pnorm[ids] = out["normal"][sel]
        self.presid[ids] = out["resid"][sel]
        self.phid[ids] = out["outlier"][sel]
        self.pver[ids] += 1
        # Roughness per 1 m voxel (worst point wins within the batch).
        vox, _ = self.flat_of(self.praw[ids])
        order = np.argsort(vox, kind="stable")
        v, r = vox[order], out["resid"][sel][order]
        starts = np.r_[0, np.flatnonzero(np.diff(v)) + 1]
        self.vres[v[starts]] = np.maximum.reduceat(r, starts)
        return len(ids)

    def redirty_hidden(self) -> None:
        """Hidden points get another look as their neighbourhoods fill in."""
        n = self.npts
        self.pdirty[:n] |= self.phid[:n] > 0

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
