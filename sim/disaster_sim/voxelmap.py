"""The master's 3D reconstruction, built only from camera frames, resident on the GPU.

Frames are fused in batches: space along every ray is carved free, the surface it hit is
marked occupied and coloured, materials are classified from the averaged colour (the
master's "segmentation"), and every surface voxel keeps its best scan quality and the time it
was last properly scanned. A colored point cloud (one running-average point per 25 cm cell)
is accumulated alongside it for the viewer, the smoother and frame alignment.

All state is torch tensors on `gpu.DEV` (CUDA on the GX10, CPU elsewhere: same code). The
master makes its planning decisions from host (numpy) mirrors that are refreshed on demand.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import torch

from . import materials as M
from .camera import Intrinsics
from .config import SimConfig
from .gpu import DEV

HIT, MISS = 6, 2
LO_MIN, LO_MAX = -30, 40
OCC_T, FREE_T = 4, -3
POINT_CELL = 0.25  # point cloud: at most one point per 25 cm cell (voxel-grid filter)
POINT_UNIT = 0.05  # point positions are stored/sent in 5 cm units (uint16)
POINT_MAX_RANGE = 10.0  # depth beyond this is too noisy to keep as points
GHOST_MARGIN = 1.0  # a ray must pass this far in front of its hit to contradict a point
PASS_GAP_S = 15.0  # a surface seen again after this long counts as a new pass
PASS_RANGE = 8.0  # only close views count as a pass
HOST_MAX_AGE_S = 0.04  # host mirrors are at most this stale
NBR = np.array([(a, b, c) for a in range(-2, 3) for b in range(-2, 3) for c in range(-2, 3)])  # 5x5x5 cells
NBR_CENTER = 62

_PAL = torch.as_tensor(M.COLORS[1:].astype(np.float32), device=DEV)  # classifiable materials 1..N-1


def classify(rgb: torch.Tensor) -> torch.Tensor:
    """Nearest palette material for (U,3) mean colours (brightness-normalised, so shading
    matters less than hue)."""
    if len(rgb) == 0:
        return torch.zeros(0, dtype=torch.uint8, device=rgb.device)
    lum = rgb.sum(1, keepdim=True) + 1.0
    plum = _PAL.sum(1, keepdim=True) + 1.0
    d = (((rgb / lum)[:, None, :] - (_PAL / plum)[None, :, :]) * 600) ** 2
    d = d.sum(2) + ((torch.log(lum) - torch.log(plum.T)) * 60) ** 2
    return (d.argmin(1) + 1).to(torch.uint8)


class ScanQuality:
    def __init__(self, near: float, far: float, proper: float):
        self.near, self.far = near, far
        self.threshold = float(min(max(1.0 - (proper - near) / (far - near), 0.0), 1.0))

    def __call__(self, dist):
        if isinstance(dist, torch.Tensor):
            return torch.clamp(1.0 - (dist - self.near) / (self.far - self.near), 0.0, 1.0)
        return np.clip(1.0 - (dist - self.near) / (self.far - self.near), 0.0, 1.0)


# name -> (dtype, trailing dims) for the point store (indexed by point id)
_PFIELDS = {
    "psum": (torch.float32, 3), "pw": (torch.float32, 0), "pcsum": (torch.float32, 3),
    "praw": (torch.float32, 3), "spos": (torch.float32, 3), "pnorm": (torch.float32, 3),
    "presid": (torch.float32, 0), "pt0": (torch.float32, 0),
    "nview": (torch.int32, 0), "pdir": (torch.int32, 0), "pmiss": (torch.int32, 0), "phid": (torch.uint8, 0),
    "pdrone": (torch.int16, 0), "pcol": (torch.uint8, 3),
    "pver": (torch.int32, 0), "prv": (torch.int32, 0), "pdirty": (torch.bool, 0),
}


class VoxelMap:
    def __init__(self, shape: tuple[int, int, int], cfg: SimConfig):
        self.shape = tuple(shape)
        n = int(np.prod(shape))
        self.n = n
        self.strides = np.array([shape[1] * shape[2], shape[2], 1])
        d = DEV
        self.g_lo = torch.zeros(n, dtype=torch.int16, device=d)  # log-odds occupancy
        self.g_csum = torch.zeros((n, 3), dtype=torch.float32, device=d)
        self.g_cnt = torch.zeros(n, dtype=torch.int32, device=d)
        self.g_mat = torch.zeros(n, dtype=torch.uint8, device=d)
        self.g_quality = torch.zeros(n, dtype=torch.float32, device=d)
        self.g_seen = torch.full((n,), -1.0, dtype=torch.float32, device=d)  # last proper scan (surfaces)
        self.g_stamp = torch.full((n,), -1, dtype=torch.int32, device=d)  # last change visible to the viewer
        self.g_npass = torch.zeros(n, dtype=torch.int32, device=d)  # distinct close views
        self.g_vdir = torch.zeros(n, dtype=torch.int32, device=d)  # sides (+-x/y/z) the surface was seen from
        self.g_lastpass = torch.full((n,), -1e9, dtype=torch.float32, device=d)
        self.g_vres = torch.zeros(n, dtype=torch.float32, device=d)  # smoother's local roughness (m)
        self.g_pvox = torch.zeros(n, dtype=torch.int32, device=d)  # points per 1 m voxel
        self.k = Intrinsics(cfg)
        self.t_rays = torch.as_tensor(self.k.body_rays, dtype=torch.float32, device=d)
        self.t_steps = torch.as_tensor(self.k.steps, dtype=torch.float32, device=d)
        self.q = ScanQuality(cfg.scan_near, cfg.cam_range, cfg.proper_scan_range)
        self.carve_max = min(cfg.depth_max, cfg.cam_range)
        self.lock = threading.RLock()  # the fuse worker, the planner and the streamer all touch device state
        self.frames = 0
        self.align_ok = 0
        self.align_n = 0
        self._shape_t = torch.as_tensor(self.shape, device=d)
        # point store
        self.pcell = np.array([int(np.ceil(x / POINT_CELL)) for x in shape])
        self._pcell_t = torch.as_tensor(self.pcell, device=d)
        self.pidx = torch.full((int(np.prod(self.pcell)),), -1, dtype=torch.int32, device=d)  # cell -> point id
        self.npts = 0
        self._pcap = 0
        self._palloc(1 << 20)
        self.g_sparse2d: torch.Tensor | None = None  # (sx, sy) columns where ground points are thinned
        # host mirrors for planning
        self._gen = 0
        self._host_gen = -1
        self._host_time = 0.0
        self._h: dict[str, np.ndarray] = {}
        self._derived: dict[str, np.ndarray] = {}
        self._rng = torch.Generator(device=d)
        self._rng.manual_seed(3)

    # ------------------------------------------------------------------ point store
    def _palloc(self, cap: int) -> None:
        with self.lock:
            self._palloc_locked(cap)

    def _palloc_locked(self, cap: int) -> None:
        for name, (dt, dim) in _PFIELDS.items():
            new = torch.zeros((cap, dim) if dim else (cap,), dtype=dt, device=DEV)
            if self._pcap:
                new[:self._pcap] = getattr(self, name)[:self._pcap]
            setattr(self, name, new)
        self._pcap = cap

    @property
    def sparse2d(self):
        return self.g_sparse2d

    @sparse2d.setter
    def sparse2d(self, a: np.ndarray) -> None:
        self.g_sparse2d = torch.as_tensor(np.ascontiguousarray(a), device=DEV)

    def hidden(self, ids: torch.Tensor) -> torch.Tensor:
        """Points the smoother called outliers, or that rays have repeatedly passed through."""
        ghost = (self.pmiss[ids] >= 3) & (self.pmiss[ids] > self.nview[ids])
        return (self.phid[ids] > 0) | ghost

    # ------------------------------------------------------------------ host mirrors
    def _refresh(self) -> None:
        with self.lock:
            self._h = {
                "lo": self.g_lo.cpu().numpy(), "mat": self.g_mat.cpu().numpy(),
                "quality": self.g_quality.cpu().numpy(), "npass": self.g_npass.cpu().numpy(),
                "vres": self.g_vres.cpu().numpy(), "pvox": self.g_pvox.cpu().numpy(),
            }
            self._derived.clear()
            self._host_gen, self._host_time = self._gen, time.monotonic()

    def sync_host(self, force: bool = False) -> None:
        if force or self._host_gen != self._gen:
            self._refresh()

    def _host(self, name: str) -> np.ndarray:
        if not self._h or (self._host_gen != self._gen and time.monotonic() - self._host_time > HOST_MAX_AGE_S):
            self._refresh()
        return self._h[name]

    lo = property(lambda self: self._host("lo"))
    mat = property(lambda self: self._host("mat"))
    quality = property(lambda self: self._host("quality"))
    npass = property(lambda self: self._host("npass"))
    vres = property(lambda self: self._host("vres"))
    pvox = property(lambda self: self._host("pvox"))

    def _derive(self, key: str, fn) -> np.ndarray:
        lo = self.lo  # may refresh (and clear the cache)
        if key not in self._derived:
            self._derived[key] = fn(lo)
        return self._derived[key]

    @property
    def occupied(self) -> np.ndarray:
        return self._derive("occ", lambda lo: lo >= OCC_T)

    @property
    def free(self) -> np.ndarray:
        return self._derive("free", lambda lo: lo <= FREE_T)

    @property
    def known(self) -> np.ndarray:
        return self._derive("known", lambda lo: (lo >= OCC_T) | (lo <= FREE_T))

    def flat_of(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Flat indices for world points and a mask of which are inside the grid (host)."""
        ix = np.floor(pts[:, 0]).astype(np.int64)
        iy = np.floor(pts[:, 1]).astype(np.int64)
        iz = np.floor(pts[:, 2]).astype(np.int64)
        sx, sy, sz = self.shape
        inside = (ix >= 0) & (ix < sx) & (iy >= 0) & (iy < sy) & (iz >= 0) & (iz < sz)
        flat = ix * self.strides[0] + iy * self.strides[1] + iz
        return np.where(inside, flat, 0), inside

    def grid(self, arr: np.ndarray) -> np.ndarray:
        return arr.reshape(self.shape)

    # ------------------------------------------------------------------ device helpers
    def _flat(self, p: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        sx, sy, sz = self.shape
        ix = torch.floor(p[..., 0]).long()
        iy = torch.floor(p[..., 1]).long()
        iz = torch.floor(p[..., 2]).long()
        inside = (ix >= 0) & (ix < sx) & (iy >= 0) & (iy < sy) & (iz >= 0) & (iz < sz)
        flat = (ix * sy + iy) * sz + iz
        return torch.where(inside, flat, torch.zeros_like(flat)), inside

    def cell_key(self, p: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Point-grid key of world points (..., 3) and whether they are inside the grid."""
        c = torch.floor(p / POINT_CELL).long()
        ok = ((c >= 0) & (c < self._pcell_t)).all(-1)
        py, pz = int(self.pcell[1]), int(self.pcell[2])
        key = (c[..., 0] * py + c[..., 1]) * pz + c[..., 2]
        return torch.where(ok, key, torch.zeros_like(key)), ok

    # ------------------------------------------------------------------ integration
    @torch.no_grad()
    def integrate_batch(self, pos: torch.Tensor, rot: torch.Tensor, depth: torch.Tensor, rgb: torch.Tensor,
                        t: torch.Tensor, drone: torch.Tensor, tick: int) -> dict:
        """Fuse B frames at once. pos (B,3), rot (B,3,3) body-to-world, depth (B,N) metres (0 = no
        return), rgb (B,N,3), t (B,) capture times, drone (B,) ids. Returns survivor-coloured
        hit points per frame: {b: (points (K,3), distance (K,))}."""
        B, N = depth.shape
        n = self.n
        dev = depth.device
        self.frames += B
        self._gen += 1
        dirs = torch.einsum("nk,bjk->bnj", self.t_rays, rot)  # (B,N,3)
        hit = depth > 0
        reach = torch.where(hit, depth - 0.6, torch.full_like(depth, self.carve_max))
        S = self.t_steps
        smask = S[None, None, :] < reach[..., None]  # (B,N,S)
        samples = pos[:, None, None, :] + dirs[:, :, None, :] * S[None, None, :, None]  # (B,N,S,3)
        flat, inside = self._flat(samples)
        sel = smask & inside
        bb = torch.arange(B, device=dev)[:, None, None].expand_as(flat)

        # ---- ghost removal: rays that pass well in front of their hit contradict a point
        gm = hit[..., None] & (S[None, None, :] < (depth[..., None] - GHOST_MARGIN)) & smask
        if bool(gm.any()):
            self._ghost(samples[gm])

        # ---- carve free space: one decrement per (frame, voxel). Dense marking, no sort: mark
        # the voxels each frame's rays cross, count frames per voxel, update the whole grid.
        mark = torch.zeros((B, n), dtype=torch.bool, device=dev)
        mark[bb[sel], flat[sel]] = True
        cnt = mark.sum(0, dtype=torch.int32)
        old = self.g_lo
        was_occ = old >= OCC_T
        was_unknown = (old > FREE_T) & ~was_occ
        new = torch.where(cnt > 0, torch.clamp(old.int() - MISS * cnt, min=LO_MIN).to(torch.int16), old)
        self.g_lo = new
        now_occ = new >= OCC_T
        now_free = new <= FREE_T
        changed_free = (was_occ & ~now_occ) | (was_unknown & now_free)

        # ---- hits
        hp = pos[:, None, :] + dirs * (depth + 0.15)[..., None]  # nudge into the surface
        hflat, hin = self._flat(hp)
        hsel = hit & hin
        bidx = torch.arange(B, device=dev)[:, None].expand(B, N)[hsel]
        hidx = hflat[hsel]
        hrgb = rgb.float()[hsel]
        hd = depth[hsel]
        hpos = hp[hsel]
        hdir = dirs[hsel]
        ht = t[bidx]
        surv_out: dict = {}
        if len(hidx):
            hkey = bidx * n + hidx
            uk2, inv = torch.unique(hkey, return_inverse=True)
            U = len(uk2)
            uvox2 = uk2 % n
            ones = torch.ones(len(inv), device=dev)
            pix = torch.zeros(U, device=dev).index_add_(0, inv, ones)
            mean_rgb = torch.zeros((U, 3), device=dev).index_add_(0, inv, hrgb) / pix[:, None]
            qd = self.q(hd)
            qmax = torch.full((U,), -1.0, device=dev).scatter_reduce_(0, inv, qd, "amax", include_self=False)
            proper = qd >= self.q.threshold
            seen_t = torch.full((U,), -1.0, device=dev).scatter_reduce_(
                0, inv, torch.where(proper, ht, torch.full_like(ht, -1.0)), "amax", include_self=False)
            tvox = torch.unique(uvox2)
            old_lo = self.g_lo[tvox]
            old_occ = old_lo >= OCC_T
            old_mat = self.g_mat[tvox]
            old_qb = torch.floor(self.g_quality[tvox] * 8)

            vv, vc = torch.unique(uvox2, return_counts=True)  # increments per voxel (one per frame)
            self.g_lo[vv] = torch.clamp(self.g_lo[vv].int() + HIT * vc.int(), max=LO_MAX).to(torch.int16)
            self.g_csum.index_add_(0, uvox2, mean_rgb)
            self.g_cnt.index_add_(0, uvox2, torch.ones(U, dtype=torch.int32, device=dev))
            self.g_quality.scatter_reduce_(0, uvox2, qmax, "amax", include_self=True)
            self.g_seen.scatter_reduce_(0, uvox2, seen_t, "amax", include_self=True)

            # ---- passes: a fresh visit rather than the next frame of the same look
            close = hd <= PASS_RANGE
            if bool(close.any()):
                look = -hdir
                axis = look.abs().argmax(1)
                side = axis * 2 + (look.gather(1, axis[:, None])[:, 0] < 0).long()
                cinv, cside = inv[close], side[close]
                ub_side = torch.full((U,), -1, dtype=torch.long, device=dev)
                ub_side[cinv] = cside
                cu = torch.nonzero(ub_side >= 0).squeeze(1)
                cv = uvox2[cu]
                cbit = (1 << ub_side[cu]).int()
                ct = t[uk2[cu] // n]
                fresh = ((self.g_vdir[cv] & cbit) == 0) | (ct - self.g_lastpass[cv] > PASS_GAP_S)
                if bool(fresh.any()):
                    fv, fc = torch.unique(cv[fresh], return_counts=True)
                    self.g_npass[fv] += 1
                    self.g_lastpass.scatter_reduce_(0, cv[fresh], ct[fresh], "amax", include_self=True)
                for k in range(6):
                    m = ub_side[cu] == k
                    if bool(m.any()):
                        self.g_vdir[cv[m]] |= (1 << k)

            # ---- reclassify touched surfaces from their running mean colour
            mean = self.g_csum[tvox] / self.g_cnt[tvox].clamp_min(1)[:, None].float()
            new_mat = classify(mean)
            mat_changed = new_mat != old_mat
            self.g_mat[tvox] = new_mat
            new_occ = self.g_lo[tvox] >= OCC_T
            new_qb = torch.floor(self.g_quality[tvox] * 8)
            changed_hit = tvox[(new_occ != old_occ) | (new_occ & (mat_changed | (new_qb > old_qb)))]
            self.g_stamp[changed_hit] = tick

            # ---- survivor-coloured pixels (a person's heat signature), by colour ratio
            r_ = hrgb[:, 0]
            surv = (r_ > 150) & (hrgb[:, 1] < 0.33 * r_) & (hrgb[:, 2] < 0.45 * r_)
            if bool(surv.any()):
                si = torch.nonzero(surv).squeeze(1)
                sb = bidx[si].cpu().numpy()
                sp, sd = hpos[si].cpu().numpy(), hd[si].cpu().numpy()
                for b in np.unique(sb):
                    m = sb == b
                    surv_out[int(b)] = (sp[m], sd[m])
            surf = hd <= POINT_MAX_RANGE
            if bool(surf.any()):
                dh = hdir[surf]
                ax = dh.abs().argmax(1)
                side = ax * 2 + (dh.gather(1, ax[:, None])[:, 0] > 0).long()  # side of the surface facing the camera
                pb = bidx[surf]
                self._add_points(hpos[surf] - 0.15 * dh, hrgb[surf], hd[surf], side, t[pb], drone[pb])
        self.g_stamp = torch.where(changed_free, torch.full_like(self.g_stamp, tick), self.g_stamp)
        return surv_out

    def _add_points(self, p, rgb, d, side, t, drone) -> None:
        """Fold surface points into the cloud (one update per cell per batch)."""
        key, ok = self.cell_key(p)
        if self.g_sparse2d is not None:  # open ground outside the building: every other cell
            c = torch.floor(p / POINT_CELL).long()
            gx = torch.floor(p[:, 0]).long().clamp(0, self.shape[0] - 1)
            gy = torch.floor(p[:, 1]).long().clamp(0, self.shape[1] - 1)
            ground = (p[:, 2] < 1.15) & self.g_sparse2d[gx, gy]
            ok &= ~ground | ((c[:, 0] % 2 == 0) & (c[:, 1] % 2 == 0))
        if not bool(ok.any()):
            return
        key, p, rgb, d, side, t, drone = key[ok], p[ok], rgb[ok], d[ok], side[ok], t[ok], drone[ok]
        uk, inv = torch.unique(key, return_inverse=True)
        ng = len(uk)
        dev = p.device
        w = 1.0 / torch.clamp(d, min=1.0) ** 2
        sw = torch.zeros(ng, device=dev).index_add_(0, inv, w)
        sp = torch.zeros((ng, 3), device=dev).index_add_(0, inv, w[:, None] * p)
        sc = torch.zeros((ng, 3), device=dev).index_add_(0, inv, w[:, None] * rgb)
        bits = torch.zeros(ng, dtype=torch.int32, device=dev)
        for k in range(6):
            m = side == k
            if bool(m.any()):
                bits[inv[m]] |= (1 << k)
        first_t = torch.zeros(ng, device=dev)
        first_t[inv] = t
        first_d = torch.zeros(ng, dtype=torch.int16, device=dev)
        first_d[inv] = drone.to(torch.int16)

        idx = self.pidx[uk].long()
        new = idx < 0
        n_new = int(new.sum())
        if n_new:
            if self.npts + n_new > self._pcap:
                self._palloc(max(self._pcap * 2, self.npts + n_new))
            ids = torch.arange(self.npts, self.npts + n_new, device=dev)
            self.pidx[uk[new]] = ids.int()
            idx[new] = ids
            self.pt0[ids] = first_t[new]
            self.pdrone[ids] = first_d[new]
            self.npts += n_new
        old_raw = self.praw[idx].clone()
        self.psum[idx] += sp
        self.pw[idx] += sw
        self.pcsum[idx] += sc
        self.nview[idx] = torch.clamp(self.nview[idx] + 1, max=65000)
        self.pdir[idx] |= bits
        self.praw[idx] = self.psum[idx] / self.pw[idx, None]
        self.pcol[idx] = torch.clamp(self.pcsum[idx] / self.pw[idx, None], 0, 255).to(torch.uint8)
        if n_new:
            ni = idx[new]
            self.spos[ni] = self.praw[ni]
            fl, ins = self._flat(self.praw[ni])
            vv, vc = torch.unique(fl[ins], return_counts=True)
            self.g_pvox[vv] += vc.int()
        ex = idx[~new]
        self.spos[ex] += self.praw[ex] - old_raw[~new]  # keep the smoothing offset
        self.prv[idx] += 1
        self.pver[idx] += 1
        self.pdirty[idx] = True

    def _ghost(self, pos: torch.Tensor) -> None:
        key, ok = self.cell_key(pos)
        pid = self.pidx[key[ok]].long()
        pid = torch.unique(pid[pid >= 0])
        if len(pid):
            self.pmiss[pid] = torch.clamp(self.pmiss[pid] + 1, max=250)
            self.pver[pid] += 1

    # ------------------------------------------------------------------ smoothing
    @torch.no_grad()
    def smooth_job(self, max_n: int = 15000) -> dict | None:
        with self.lock:
            """Snapshot of the dirty points and their neighbourhoods for the smoothing worker."""
            ids = torch.nonzero(self.pdirty[:self.npts]).squeeze(1)
            if len(ids) == 0:
                return None
            if len(ids) > max_n:  # fair share of a backlog
                ids = ids[torch.randperm(len(ids), device=ids.device, generator=self._rng)[:max_n]].sort().values
            self.pdirty[ids] = False
            c = torch.floor(self.praw[ids] / POINT_CELL).long()
            nbr = torch.as_tensor(NBR, device=ids.device)
            nb = c[:, None, :] + nbr[None, :, :]
            ok = ((nb >= 0) & (nb < self._pcell_t)).all(-1)
            py, pz = int(self.pcell[1]), int(self.pcell[2])
            key = (nb[..., 0] * py + nb[..., 1]) * pz + nb[..., 2]
            pid = torch.where(ok, self.pidx[torch.where(ok, key, torch.zeros_like(key))].long(), torch.full_like(key, -1))
            valid = pid >= 0
            pid = torch.where(valid, pid, torch.zeros_like(pid))
            valid &= (self.phid[pid] == 0) | (torch.arange(125, device=ids.device)[None, :] == NBR_CENTER)
            return {"ids": ids, "rv": self.prv[ids].clone(), "pos": self.praw[pid], "valid": valid, "w": self.pw[pid]}

    @torch.no_grad()
    def apply_smoothing(self, job: dict, out: dict) -> int:
        with self.lock:
            """Merge a worker result. Points that changed since the snapshot stay dirty."""
            ids = job["ids"]
            cur = self.prv[ids] == job["rv"]
            self.pdirty[ids[~cur]] = True
            sel = torch.nonzero(cur).squeeze(1)
            ids = ids[sel]
            if len(ids) == 0:
                return 0
            dev = ids.device
            self.spos[ids] = out["spos"][sel].to(dev)
            self.pnorm[ids] = out["normal"][sel].to(dev)
            resid = out["resid"][sel].to(dev)
            self.presid[ids] = resid
            self.phid[ids] = out["outlier"][sel].to(dev).to(torch.uint8)
            self.pver[ids] += 1
            vox, ins = self._flat(self.praw[ids])
            tmp = torch.zeros(self.n, device=dev).scatter_reduce_(0, vox[ins], resid[ins], "amax", include_self=False)
            tv = torch.unique(vox[ins])
            self.g_vres[tv] = tmp[tv]
            return len(ids)

    def redirty_hidden(self) -> None:
        with self.lock:
            """Hidden points get another look as their neighbourhoods fill in."""
            self.pdirty[:self.npts] |= self.phid[:self.npts] > 0

        # ------------------------------------------------------------------ streaming
    @torch.no_grad()
    def deltas_since(self, tick: int):
        with self.lock:
            """(idx, occupied, material, rgb565, quality u8) for voxels changed after `tick`."""
            idx = torch.nonzero(self.g_stamp > tick).squeeze(1)
            occ = (self.g_lo[idx] >= OCC_T).cpu().numpy()
            mean = (self.g_csum[idx] / self.g_cnt[idx].clamp_min(1)[:, None].float()).clamp(0, 255)
            m16 = mean.to(torch.int32)
            rgb565 = (((m16[:, 0] >> 3) << 11) | ((m16[:, 1] >> 2) << 5) | (m16[:, 2] >> 3)).cpu().numpy().astype(np.uint16)
            q = torch.round(self.g_quality[idx] * 255).to(torch.uint8).cpu().numpy()
            return idx.cpu().numpy(), occ, self.g_mat[idx].cpu().numpy(), rgb565, q

    def gather_points(self, ids: np.ndarray) -> dict:
        with self.lock:
            """Host copy of a few points' fields (for scoring)."""
            t = torch.as_tensor(ids, device=DEV)
            return {"raw": self.praw[t].cpu().numpy(), "smooth": self.spos[t].cpu().numpy(),
                    "hidden": self.hidden(t).cpu().numpy()}
