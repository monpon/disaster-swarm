"""Smooth surfaces from the depth frames: GPU TSDF fusion + marching cubes on the central node.

The point cloud is a sparse sampling. This fuses every aligned frame into a truncated signed
distance volume (0.2 m voxels) on the GPU: each ray adds the signed distance to the surface
it hit within a band around the hit, and carves empty space in front of it. Many noisy views
average to one clean zero-crossing, so walls become flat, edges stay where two walls meet,
and a doorway is a real hole in the facade. Marching cubes then turns the volume into a
triangle mesh, 32^3-voxel chunk by chunk (only chunks that changed are re-meshed).

Needs PyTorch (CUDA on the GX10) and scikit-image. Without them `Surface.available` is
False and the viewer keeps showing the point cloud.
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np

VOXEL = 0.2  # m
MU = 0.5  # truncation distance in front of the surface (m)
BEHIND = 0.5  # band behind the surface that is still integrated (m): symmetric, so smoothing does not bias walls
BAND_STEP = 0.1
FREE_STEP = 0.2
MAX_DEPTH = 10.0  # the survey looks at walls from 8 m; far samples are down-weighted by 1/d^2
MIN_DEPTH = 0.3
FREE_WEIGHT = 0.3  # carving counts less than a surface hit
MIN_W = 0.08  # a voxel needs this much weight to count as observed: one frame is enough to show a wall
W_CAP = 64.0
CHUNK = 32
MESH_MIN_INTERVAL_S = 0.25  # a chunk is re-meshed at most this often
MESH_BUDGET_S = 0.2  # GPU time per worker cycle spent re-meshing dirty chunks
SNAP_TOL = 0.6  # m: vertices this close to a straight-wall plane are put exactly on it
SNAP_ALIGN = 0.8  # ... if their normal points along that plane's axis
FILTER_SIGMA = 1.2  # voxels: Gaussian smoothing of the distance field before meshing
FILTER_PAD = 3
BLUR_WEIGHT_SAT = 0.0  # >0: voxels with more evidence count more in the blur (saturating here)
POS_UNIT = 0.01  # streamed vertex positions are uint16 in 1 cm units
MAX_QUEUE = 48
BATCH = 24


class Surface:
    def __init__(self, site_shape: tuple[int, int, int]):
        self.available = False
        self.backend = "off"
        try:
            import torch
            from .gpumc import GpuMarchingCubes
        except ImportError:
            return
        self.torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.backend = "cuda" if self.device.type == "cuda" else "torch-cpu"
        self.dims = tuple(int(np.ceil(s / VOXEL)) for s in site_shape)
        nx, ny, nz = self.dims
        self.ncx, self.ncy, self.ncz = (-(-d // CHUNK) for d in self.dims)
        n = nx * ny * nz
        self.tsdf = torch.zeros(n, dtype=torch.float16, device=self.device)  # running average, +free / -inside
        self.w = torch.zeros(n, dtype=torch.float16, device=self.device)
        self.col = torch.zeros((n, 3), dtype=torch.uint8, device=self.device)
        self.wc = torch.zeros(n, dtype=torch.float16, device=self.device)
        self.offs = torch.arange(-MU, BEHIND + 1e-6, BAND_STEP, device=self.device)  # band offsets (m): front is negative
        self.dirty: dict[int, None] = {}  # chunks to re-mesh, oldest first (every chunk gets its turn)
        self.meshed_at: dict[int, float] = {}
        self.planes: list[list[float]] = [[], [], []]  # straight-wall assumption: x, y, z plane positions
        self.plane_stat: dict[tuple, list] = {}  # (axis, i) -> [sum, count] of aligned vertices near it
        self.plane_on = True
        self.chunks: dict[int, dict] = {}  # chunk id -> {"ver", "v", "n", "c", "f"}
        self.tris = 0
        self.last_ms = 0.0
        self.frames_done = 0
        self.mc = GpuMarchingCubes(torch, self.device)
        self.q: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="surface", daemon=True)
        self._thread.start()
        self.available = True

    # ------------------------------------------------------------------ input
    def add(self, pos: np.ndarray, dirs: np.ndarray, depth: np.ndarray, rgb: np.ndarray) -> None:
        """Queue one aligned frame: camera position, (N,3) world ray directions, (N,) depth, (N,3) rgb."""
        if not self.available:
            return
        d = depth.reshape(-1)
        ok = (d > MIN_DEPTH) & (d <= MAX_DEPTH)
        if ok.sum() < 20:
            return
        try:
            self.q.put_nowait((pos.astype(np.float32), dirs[ok].astype(np.float32), d[ok].astype(np.float32),
                               rgb.reshape(-1, 3)[ok].astype(np.uint8)))
        except queue.Full:
            pass  # the GPU is behind: drop this frame

    def close(self) -> None:
        if self.available:
            self._stop.set()

    # ----------------------------------------------------------------- worker
    def _run(self) -> None:
        while not self._stop.is_set():
            batch = []
            try:
                batch.append(self.q.get(timeout=0.25))
                while len(batch) < BATCH:
                    batch.append(self.q.get_nowait())
            except queue.Empty:
                pass
            t0 = time.perf_counter()
            try:
                if batch:
                    self._integrate(batch)
                self._mesh_dirty()
            except Exception as e:  # never take the sim down
                print(f"surface error: {e!r}", flush=True)
            if batch or self.dirty:
                self.last_ms = (time.perf_counter() - t0) * 1000

    def _integrate(self, batch: list) -> None:
        torch, dev = self.torch, self.device
        pos = torch.as_tensor(np.concatenate([np.repeat(b[0][None], len(b[2]), 0) for b in batch]), device=dev)
        dirs = torch.as_tensor(np.concatenate([b[1] for b in batch]), device=dev)
        depth = torch.as_tensor(np.concatenate([b[2] for b in batch]), device=dev)
        rgb = torch.as_tensor(np.concatenate([b[3] for b in batch]), device=dev).float()
        wf = 4.0 / depth.clamp_min(1.0) ** 2  # near views count more

        # Band around the hit: signed distance (positive in front of the surface).
        s_band = depth[:, None] + self.offs[None, :]
        sdf_band = (-self.offs / MU).clamp(-1.0, 1.0)[None, :].expand_as(s_band)
        w_band = wf[:, None].expand_as(s_band)
        c_band = (self.offs.abs() <= 0.2)[None, :].expand_as(s_band).float()  # colour only close to the surface
        # Free space in front of the band.
        k_free = torch.arange(0.3, MAX_DEPTH, FREE_STEP, device=dev)
        s_free = k_free[None, :].expand(len(depth), -1)
        free_ok = s_free < (depth[:, None] - MU)
        s_all = torch.cat([s_band, s_free], dim=1)
        sdf_all = torch.cat([sdf_band, torch.ones_like(s_free)], dim=1)
        w_all = torch.cat([w_band, wf[:, None].expand_as(s_free) * FREE_WEIGHT], dim=1)
        c_all = torch.cat([c_band, torch.zeros_like(s_free)], dim=1)
        valid = torch.cat([torch.ones_like(s_band, dtype=torch.bool), free_ok], dim=1)

        p = pos[:, None, :] + dirs[:, None, :] * s_all[..., None]
        ijk = torch.floor(p / VOXEL).long()
        nx, ny, nz = self.dims
        inside = (ijk[..., 0] >= 0) & (ijk[..., 0] < nx) & (ijk[..., 1] >= 0) & (ijk[..., 1] < ny) \
            & (ijk[..., 2] >= 0) & (ijk[..., 2] < nz) & valid
        flat = (ijk[..., 0] * ny + ijk[..., 1]) * nz + ijk[..., 2]
        idx = flat[inside]
        sdf, w, cw = sdf_all[inside], w_all[inside], c_all[inside]
        col = rgb[:, None, :].expand(-1, s_all.shape[1], -1)[inside]
        if len(idx) == 0:
            return
        uniq, inv = torch.unique(idx, return_inverse=True)
        u = len(uniq)
        sw = torch.zeros(u, device=dev).index_add_(0, inv, w)
        ss = torch.zeros(u, device=dev).index_add_(0, inv, w * sdf)
        scw = torch.zeros(u, device=dev).index_add_(0, inv, w * cw)
        sc = torch.zeros((u, 3), device=dev).index_add_(0, inv, (w * cw)[:, None] * col)
        w_old = self.w[uniq].float()
        t_old = self.tsdf[uniq].float()
        w_new = w_old + sw
        self.tsdf[uniq] = ((t_old * w_old + ss) / w_new).half()
        self.w[uniq] = w_new.clamp(max=W_CAP).half()
        wc_old = self.wc[uniq].float()
        wc_new = wc_old + scw
        c_old = self.col[uniq].float()
        mix = torch.where(wc_new[:, None] > 0, (c_old * wc_old[:, None] + sc) / wc_new.clamp_min(1e-6)[:, None], c_old)
        self.col[uniq] = mix.clamp(0, 255).byte()
        self.wc[uniq] = wc_new.clamp(max=W_CAP).half()
        # Chunks that changed need re-meshing.
        i = uniq // (ny * nz)
        j = (uniq // nz) % ny
        k = uniq % nz
        cid = ((i // CHUNK) * self.ncy + (j // CHUNK)) * self.ncz + (k // CHUNK)
        for c in torch.unique(cid).cpu().tolist():
            self.dirty.setdefault(c, None)  # keeps its place in line if already waiting
        self.frames_done += len(batch)

    # ---------------------------------------------------------------- meshing
    def _mesh_dirty(self) -> None:
        t0 = time.perf_counter()
        now = time.monotonic()
        for cid in list(self.dirty):
            if time.perf_counter() - t0 > MESH_BUDGET_S:
                break
            if now - self.meshed_at.get(cid, -1e9) < MESH_MIN_INTERVAL_S:
                continue  # meshed a moment ago: it keeps its place in line
            del self.dirty[cid]
            self.meshed_at[cid] = now
            self._mesh_chunk(cid)
        self.tris = sum(len(c["f"]) // 3 for c in self.chunks.values())

    def set_planes(self, xs: list[float], ys: list[float], zs: list[float]) -> None:
        """Assume the building's outer walls and roof are flat and axis-aligned: vertices near
        these planes snap onto them, so walls are flat and corners exactly angular. The plane
        positions are refined from the mesh itself (mean of the aligned vertices near each)."""
        new = [list(map(float, xs)), list(map(float, ys)), list(map(float, zs))]
        if new == self.planes:
            return
        self.planes = new
        self.plane_stat.clear()
        for cid in self.chunks:  # re-mesh everything with the new planes
            self.dirty.setdefault(cid, None)
            self.meshed_at.pop(cid, None)

    def _snap(self, world, nrm):
        """Snap vertices onto the straight-wall planes (in place); returns world, nrm."""
        torch = self.torch
        for a in range(3):
            for i, p in enumerate(self.planes[a]):
                st = self.plane_stat.setdefault((a, i), [0.0, 0])
                near = ((world[:, a] - p).abs() < SNAP_TOL) & (nrm[:, a].abs() > SNAP_ALIGN)
                if bool(near.any()):
                    if st[1] < 4000:  # refine the plane from what is actually there
                        st[0] += float(world[near, a].sum())
                        st[1] += int(near.sum())
                        if st[1] > 300:
                            self.planes[a][i] = st[0] / st[1]
                            p = self.planes[a][i]
                    world[near, a] = p
                    sgn = torch.sign(nrm[near, a])
                    nrm[near] = 0.0
                    nrm[near, a] = sgn
        return world, nrm

    def _smooth_field(self, vol, obs, wgt):
        """Gaussian smoothing of the signed-distance field using only observed voxels
        (normalised convolution), so noisy views average into one smooth, flat surface."""
        torch = self.torch
        if not hasattr(self, "_kern"):
            r = torch.arange(-FILTER_PAD, FILTER_PAD + 1, device=self.device, dtype=torch.float32)
            k = torch.exp(-r ** 2 / (2 * FILTER_SIGMA ** 2))
            self._kern = (k / k.sum()).view(1, 1, -1)
        k = self._kern
        def blur(x):
            x = x[None, None]
            for ax in range(3):
                shape = [1, 1, 1, 1, 1]
                shape[2 + ax] = -1
                x = torch.nn.functional.conv3d(x, k.view(shape), padding=[FILTER_PAD if a == ax else 0 for a in range(3)])
            return x[0, 0]
        m = obs.float()
        if BLUR_WEIGHT_SAT > 0:
            m = m * (wgt / BLUR_WEIGHT_SAT).clamp(max=1.0)
        num, den = blur(vol * m), blur(m)
        return torch.where((den > 0.25) & obs, num / den.clamp_min(1e-6), vol)

    def _mesh_chunk(self, cid: int) -> None:
        torch = self.torch
        nx, ny, nz = self.dims
        ck, r = cid % self.ncz, cid // self.ncz
        cj, ci = r % self.ncy, r // self.ncy
        i0, j0, k0 = ci * CHUNK, cj * CHUNK, ck * CHUNK
        n = (min(CHUNK + 1, nx - i0), min(CHUNK + 1, ny - j0), min(CHUNK + 1, nz - k0))  # +1: shared border
        prev = self.chunks.get(cid)
        ver = (prev["ver"] if prev else 0) + 1
        empty = {"ver": ver, "t": time.monotonic(), "v": np.zeros(0, np.uint16), "n": np.zeros(0, np.int8), "c": np.zeros(0, np.uint8),
                 "f": np.zeros(0, np.uint32)}

        def clear() -> None:
            if prev is not None:
                self.chunks[cid] = empty

        if min(n) < 2:
            return clear()
        pad = FILTER_PAD  # context around the chunk so smoothing is seamless across chunk borders
        lo = (max(i0 - pad, 0), max(j0 - pad, 0), max(k0 - pad, 0))
        hi = (min(i0 + n[0] + pad, nx), min(j0 + n[1] + pad, ny), min(k0 + n[2] + pad, nz))
        big = (slice(lo[0], hi[0]), slice(lo[1], hi[1]), slice(lo[2], hi[2]))
        wv = self.w.view(nx, ny, nz)[big].float()
        obs_t = wv >= MIN_W
        if not bool(obs_t.any()):
            return clear()
        vol_t = self._smooth_field(self.tsdf.view(nx, ny, nz)[big].float(), obs_t, wv)
        cut = (slice(i0 - lo[0], i0 - lo[0] + n[0]), slice(j0 - lo[1], j0 - lo[1] + n[1]),
               slice(k0 - lo[2], k0 - lo[2] + n[2]))
        vol = vol_t[cut]
        obs = obs_t[cut]
        # A cube is meshed only when all 8 of its corners were observed.
        cube = (obs[:-1, :-1, :-1] & obs[1:, :-1, :-1] & obs[:-1, 1:, :-1] & obs[1:, 1:, :-1]
                & obs[:-1, :-1, 1:] & obs[1:, :-1, 1:] & obs[:-1, 1:, 1:] & obs[1:, 1:, 1:])
        vol = torch.where(obs, vol, torch.ones_like(vol))
        verts, faces = self.mc(vol, cube)
        if len(faces) == 0:
            return clear()
        # Normals from the smoothed field's gradient (toward free space); colour from the nearest voxel.
        gx, gy, gz = torch.gradient(vol)
        vi = verts.round().long()
        vi = torch.stack([vi[:, 0].clamp(0, n[0] - 1), vi[:, 1].clamp(0, n[1] - 1), vi[:, 2].clamp(0, n[2] - 1)], dim=1)
        nrm = torch.stack([gx[vi[:, 0], vi[:, 1], vi[:, 2]], gy[vi[:, 0], vi[:, 1], vi[:, 2]],
                           gz[vi[:, 0], vi[:, 1], vi[:, 2]]], dim=1)
        nrm = nrm / nrm.norm(dim=1, keepdim=True).clamp_min(1e-6)
        col = self.col.view(nx, ny, nz, 3)[i0:i0 + n[0], j0:j0 + n[1], k0:k0 + n[2]][vi[:, 0], vi[:, 1], vi[:, 2]]
        origin = torch.tensor([i0, j0, k0], device=self.device, dtype=verts.dtype)
        world = (verts + origin + 0.5) * VOXEL
        if self.plane_on and any(self.planes):
            world, nrm = self._snap(world, nrm)
        # One transfer: positions, normals and colours packed together.
        packed = torch.cat([torch.round(world / POS_UNIT).clamp(0, 65535), torch.round(nrm * 127) + 128.0,
                            col.float()], dim=1).to(torch.int32).cpu().numpy()
        self.chunks[cid] = {
            "ver": ver,
            "t": time.monotonic(),
            "v": packed[:, 0:3].astype(np.uint16).reshape(-1),
            "n": (packed[:, 3:6] - 128).astype(np.int8).reshape(-1),
            "c": packed[:, 6:9].astype(np.uint8).reshape(-1),
            "f": faces.to(torch.int32).cpu().numpy().astype(np.uint32).reshape(-1),
        }

    # ----------------------------------------------------------------- output
    def updates(self, sent: dict[int, tuple], full: bool = False, limit: int = 12, budget: int = 110_000) -> list[tuple[int, dict]]:
        """Chunks whose mesh changed since `sent` (chunk id -> (version, send order) that the
        viewers have). The chunk that has waited longest since it was last sent goes first, so
        a busy area cannot starve the rest."""
        if not self.available:
            return []
        stale = []
        for cid, c in list(self.chunks.items()):
            have = sent.get(cid)
            if not full and have is not None and have[0] == c["ver"]:
                continue
            if not full and len(c["f"]) == 0 and have is None:
                continue
            stale.append((have[1] if have is not None else -1, cid, c))
        if full:
            return [(cid, c) for _, cid, c in sorted(stale, key=lambda x: x[0])]
        # Alternate between what changed most recently (so the view a drone is looking at
        # appears at once) and what has waited longest (so nothing starves).
        newest = sorted(stale, key=lambda x: -x[2]["t"])
        oldest = sorted(stale, key=lambda x: x[0])
        order, seen = [], set()
        for a, b in zip(newest, oldest):
            for it in (a, b):
                if it[1] not in seen:
                    seen.add(it[1])
                    order.append(it)
        out, used = [], 0
        for _, cid, c in order:
            size = len(c["v"]) * 2 + len(c["n"]) + len(c["c"]) + len(c["f"]) * 3
            if out and (used + size > budget or len(out) >= limit):
                break
            out.append((cid, c))
            used += size
        return out
