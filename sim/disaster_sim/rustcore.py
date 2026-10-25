"""Adapters between the Python simulator and the Rust/CUDA core (`gpucore`): the camera, the map the
master plans on, and the viewer stream. Selected with DISASTER_CORE=rust (default when `gpucore` is
installed); DISASTER_CORE=torch keeps the PyTorch implementation, which is also the reference."""
from __future__ import annotations

import os

import numpy as np

from . import materials as M
from .camera import Intrinsics
from .packets import FramePacket

try:
    import gpucore
except ImportError:  # no Rust core built here
    gpucore = None

AVAILABLE = gpucore is not None and os.environ.get("DISASTER_CORE", "rust").lower() != "torch"
HOST_MAX_AGE_S = 0.04


def make_core(building, cfg):
    from .camera import RGBDCamera
    from .voxelmap import ScanQuality
    k = Intrinsics(cfg)
    pad = 27   # out of the volume is air, so the padding only needs to cover where drones fly
    sx, sy, sz = building.vox.shape
    world = np.zeros((sx + 2 * pad, sy + 2 * pad, sz + 2 * pad), dtype=np.uint8)
    world[:, :, :pad] = M.ASPHALT
    world[pad:pad + sx, pad:pad + sy, pad:pad + sz] = building.vox
    q = ScanQuality(cfg.scan_near, cfg.scan_far, cfg.proper_scan_range)
    core = gpucore.Core(world, pad, k.body_rays.astype(np.float32), cfg.cam_w, cfg.cam_h, cfg.cam_hfov_deg,
                        k.steps.astype(np.float32), 0.5, M.COLORS.astype(np.float32), (int(sx), int(sy), int(sz)),
                        M.COLORS[1:].astype(np.float32), float(min(cfg.depth_max, cfg.cam_range)),
                        float(cfg.scan_near), float(cfg.scan_far), float(q.threshold),
                        int(min(8192, max(1024, cfg.n_drones * 170))))  # frame pool: a full onboard buffer per drone
    # the survivors, drawn by the camera kernel as people
    prims, spheres, first = [], [], 0
    for sv in building.survivors:
        P = sv.prims
        if P is None or not len(P):
            continue
        pts = np.vstack([P[:, 0:3], P[:, 3:6]])
        ctr = (pts.min(axis=0) + pts.max(axis=0)) / 2
        rad = float(max(np.linalg.norm(P[:, 0:3] - ctr, axis=1).max(), np.linalg.norm(P[:, 3:6] - ctr, axis=1).max()) + P[:, 6].max())
        spheres.append([*ctr, rad, first, len(P)])
        prims.append(P)
        first += len(P)
    core.set_humans(np.ascontiguousarray(np.vstack(prims) if prims else np.zeros((0, 10)), dtype=np.float32),
                    np.ascontiguousarray(np.array(spheres).reshape(-1, 6), dtype=np.float32))
    az = np.arctan2(k.body_rays[:, 1], k.body_rays[:, 0])
    el = np.arctan2(k.body_rays[:, 2], np.hypot(k.body_rays[:, 0], k.body_rays[:, 1]))
    from .radio import GLASS_DB, GROUND_DB, SLAB_DB, WALL_DB
    k = 0.35 if cfg.plan_assist else 1.0   # plan-assisted demo: a better indoor radio (walls and slabs cost a third as much)
    core.set_link_params([GROUND_DB if m == M.ASPHALT else k * (GLASS_DB if m == M.GLASS else SLAB_DB if m in (M.FLOOR, M.ROOF) else WALL_DB)
                          for m in range(M.N_MATERIALS)])
    core.set_cone(np.flatnonzero((np.abs(az) < 0.26) & (np.abs(el) < 0.2)).astype(np.int32))
    return core


class RustCamera:
    """Renders and degrades every drone's frame on the device; frames stay in the core's pool."""

    def __init__(self, core, building, cfg, rng: np.random.Generator):
        self.core, self.b, self.rng, self.jpeg_bytes, self.cfg = core, building, rng, cfg.jpeg_bytes, cfg

    def capture_many(self, items: list, t: float) -> list[FramePacket]:
        if not items:
            return []
        poss = np.stack([p for _, p, _, _ in items]).astype(np.float32)
        rots = np.stack([r for _, _, r, _ in items]).astype(np.float32)
        om = np.stack([w for _, _, _, w in items]).astype(np.float32)
        inside = self.b.inside_building(poss.astype(np.float64)).astype(np.uint8)
        slots = self.core.render(poss, rots, om, inside, int(self.rng.integers(1 << 62)))
        sizes = (self.jpeg_bytes * self.rng.uniform(0.8, 1.2, len(items))).astype(int)
        return [FramePacket(d, t, None, int(sizes[j]), slot=int(slots[j]),
                            sim_truth={"pos": pos.copy(), "rot": rot.copy()})
                for j, (d, pos, rot, _) in enumerate(items)]


class RustMap:
    """What the master sees of the map: host (numpy) mirrors for planning, refreshed on demand, and
    methods that run on the core. API-compatible with `voxelmap.VoxelMap` where the master uses it."""
    rust = True

    def __init__(self, core, shape, cfg):
        import time
        from .voxelmap import ScanQuality
        self._time = time
        self.core = core
        self.shape = tuple(shape)
        self.n = int(np.prod(shape))
        self.strides = np.array([shape[1] * shape[2], shape[2], 1])
        self.k = Intrinsics(cfg)
        self.q = ScanQuality(cfg.scan_near, cfg.scan_far, cfg.proper_scan_range)
        self.frames = 0
        self.align_ok = 0
        self.align_n = 0
        self.npts = 0
        self._gen = 0
        self._host_gen = -1
        self._host_time = 0.0
        self._h: dict = {}
        self._derived: dict = {}
        self._g: dict = {}

    # host mirrors --------------------------------------------------------------
    def _refresh(self) -> None:
        h = self.core.host_arrays()
        self._h = {k: np.asarray(v) for k, v in h.items()}
        self._derived.clear()
        self._g.clear()
        self._host_gen, self._host_time = self._gen, self._time.monotonic()

    def sync_host(self, force: bool = False) -> None:
        if force or self._host_gen != self._gen:
            self._refresh()

    def _host(self, name: str) -> np.ndarray:
        if not self._h or (self._host_gen != self._gen and self._time.monotonic() - self._host_time > HOST_MAX_AGE_S):
            self._refresh()
        return self._h[name]

    lo = property(lambda s: s._host("lo"))
    mat = property(lambda s: s._host("mat"))
    quality = property(lambda s: s._host("quality"))
    npass = property(lambda s: s._host("npass"))
    vres = property(lambda s: s._host("vres"))
    pvox = property(lambda s: s._host("pvox"))

    def _derive(self, key, fn):
        lo = self.lo
        if key not in self._derived:
            self._derived[key] = fn(lo)
        return self._derived[key]

    occupied = property(lambda s: s._derive("occ", lambda lo: lo >= 4))
    free = property(lambda s: s._derive("free", lambda lo: lo <= -3))
    known = property(lambda s: s._derive("known", lambda lo: (lo >= 4) | (lo <= -3)))

    def flat_of(self, pts: np.ndarray):
        ix = np.floor(pts[:, 0]).astype(np.int64)
        iy = np.floor(pts[:, 1]).astype(np.int64)
        iz = np.floor(pts[:, 2]).astype(np.int64)
        sx, sy, sz = self.shape
        inside = (ix >= 0) & (ix < sx) & (iy >= 0) & (iy < sy) & (iz >= 0) & (iz < sz)
        return np.where(inside, ix * self.strides[0] + iy * self.strides[1] + iz, 0), inside

    def grid(self, arr: np.ndarray) -> np.ndarray:
        return arr.reshape(self.shape)

    # torch views for the (torch) link model: built from the host mirror
    @property
    def g_lo(self):
        import torch
        from .gpu import DEV
        self.lo
        if "lo" not in self._g:
            self._g["lo"] = torch.as_tensor(self._h["lo"].astype(np.int16), device=DEV)
        return self._g["lo"]

    @property
    def g_mat(self):
        import torch
        from .gpu import DEV
        self.mat
        if "mat" not in self._g:
            self._g["mat"] = torch.as_tensor(self._h["mat"], device=DEV)
        return self._g["mat"]

    @property
    def sparse2d(self):
        return None

    @sparse2d.setter
    def sparse2d(self, a: np.ndarray) -> None:
        self.core.set_sparse2d(np.ascontiguousarray(a, dtype=np.uint8))

    # core operations ------------------------------------------------------------
    def smooth_step(self, max_n: int) -> int:
        return self.core.smooth_step(int(max_n))

    def redirty_hidden(self) -> None:
        self.core.redirty_hidden()

    def gather_points(self, ids: np.ndarray) -> dict:
        d = self.core.gather_points([int(i) for i in ids])
        return {"raw": np.asarray(d["raw"]), "smooth": np.asarray(d["smooth"]), "hidden": np.asarray(d["hidden"]).astype(bool)}


class _CountLen:
    def __init__(self, f):
        self._f = f

    def __len__(self):
        return self._f()


class RustSurface:
    """The surface mesh (TSDF fusion + marching cubes + wall snapping) as run by the Rust core. Frames are
    fused inside `fuse`; `step` meshes dirty chunks; `updates` hands the viewer changed chunks."""
    available = True
    backend = "cuda"

    def __init__(self, core):
        import time
        self._time = time
        self.core = core
        self.tris = 0
        self.last_ms = 0.0
        self.chunks = _CountLen(lambda: self._nchunks)
        self._nchunks = 0

    def add_batch(self, *a, **k) -> None:  # frames are fused by `core.fuse`
        pass

    def step(self, now: float, max_chunks: int = 400, min_interval: float = 0.0, budget_ms: int = 30) -> None:
        t0 = self._time.perf_counter()
        n = self.core.mesh_step(max_chunks, float(now), min_interval, int(budget_ms))
        if n:
            self.tris, self._nchunks = self.core.mesh_totals()
            self.last_ms = self.last_ms * 0.8 + (self._time.perf_counter() - t0) * 1000 * 0.2

    def set_openings(self, rows) -> None:
        self.core.set_openings(np.ascontiguousarray(rows, dtype=np.float32).reshape(-1, 8))

    def close(self) -> None:
        pass

    def updates(self, sent: dict, full: bool = False, limit: int = 12, budget: int = 110_000) -> list:
        """Chunks whose mesh changed since `sent` (id -> (version, order sent)). Alternates between the most
        recently changed (what a drone is looking at now) and the longest-waiting (so nothing starves)."""
        info = self.core.mesh_info()
        ids, ver, t = np.asarray(info["ids"]), np.asarray(info["ver"]), np.asarray(info["t"])
        nfaces, nbytes = np.asarray(info["nfaces"]), np.asarray(info["nbytes"])
        stale = []
        for k in range(len(ids)):
            cid = int(ids[k])
            have = sent.get(cid)
            if not full and have is not None and have[0] == int(ver[k]):
                continue
            if not full and nfaces[k] == 0 and have is None:
                continue
            stale.append((have[1] if have is not None else -1, cid, float(t[k]), int(nbytes[k])))
        if full:
            chosen = [s[1] for s in sorted(stale)]
        else:
            newest = sorted(stale, key=lambda s: -s[2])
            oldest = sorted(stale, key=lambda s: s[0])
            order, seen = [], set()
            for a, b in zip(newest, oldest):
                for it in (a, b):
                    if it[1] not in seen:
                        seen.add(it[1])
                        order.append(it)
            chosen, used = [], 0
            for _, cid, _, size in order:
                if chosen and (used + size > budget or len(chosen) >= limit):
                    break
                chosen.append(cid)
                used += size
        out = []
        for cid in chosen:
            d = self.core.mesh_chunk(int(cid))
            out.append((cid, {"ver": int(d["ver"]), "v": np.asarray(d["v"]), "n": np.asarray(d["n"]),
                              "c": np.asarray(d["c"]), "f": np.asarray(d["f"])}))
        return out
