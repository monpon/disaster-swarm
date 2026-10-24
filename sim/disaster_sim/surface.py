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
BEHIND = 0.3  # band behind the surface that is still integrated (m)
BAND_STEP = 0.1
FREE_STEP = 0.2
MAX_DEPTH = 8.0  # deeper depth estimates are too noisy for surfaces
MIN_DEPTH = 0.3
FREE_WEIGHT = 0.3  # carving counts less than a surface hit
MIN_W = 0.2  # a voxel needs this much weight to count as observed
W_CAP = 64.0
CHUNK = 32
CHUNKS_PER_CYCLE = 8
POS_UNIT = 0.01  # streamed vertex positions are uint16 in 1 cm units
MAX_QUEUE = 48
BATCH = 24


class Surface:
    def __init__(self, site_shape: tuple[int, int, int]):
        self.available = False
        self.backend = "off"
        try:
            import torch
            from skimage import measure
        except ImportError:
            return
        self.torch, self.measure = torch, measure
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
        self.dirty: set[int] = set()
        self.chunks: dict[int, dict] = {}  # chunk id -> {"ver", "v", "n", "c", "f"}
        self.tris = 0
        self.last_ms = 0.0
        self.frames_done = 0
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
        self.dirty.update(torch.unique(cid).cpu().tolist())
        self.frames_done += len(batch)

    # ---------------------------------------------------------------- meshing
    def _mesh_dirty(self) -> None:
        for cid in sorted(self.dirty)[:CHUNKS_PER_CYCLE]:
            self.dirty.discard(cid)
            self._mesh_chunk(cid)
        self.tris = sum(len(c["f"]) // 3 for c in self.chunks.values())

    def _sub(self, arr, i0, j0, k0, n):
        nx, ny, nz = self.dims
        return arr.view(nx, ny, nz, *arr.shape[1:])[i0:i0 + n[0], j0:j0 + n[1], k0:k0 + n[2]]

    def _mesh_chunk(self, cid: int) -> None:
        nx, ny, nz = self.dims
        ck, r = cid % self.ncz, cid // self.ncz
        cj, ci = r % self.ncy, r // self.ncy
        i0, j0, k0 = ci * CHUNK, cj * CHUNK, ck * CHUNK
        n = (min(CHUNK + 1, nx - i0), min(CHUNK + 1, ny - j0), min(CHUNK + 1, nz - k0))  # +1: shared border
        vol = self._sub(self.tsdf, i0, j0, k0, n).float().cpu().numpy()
        w = self._sub(self.w, i0, j0, k0, n).float().cpu().numpy()
        obs = w >= MIN_W
        # A cube is meshed only when all 8 of its corners were observed.
        cube = (obs[:-1, :-1, :-1] & obs[1:, :-1, :-1] & obs[:-1, 1:, :-1] & obs[1:, 1:, :-1]
                & obs[:-1, :-1, 1:] & obs[1:, :-1, 1:] & obs[:-1, 1:, 1:] & obs[1:, 1:, 1:])
        prev = self.chunks.get(cid)
        ver = (prev["ver"] if prev else 0) + 1
        empty = {"ver": ver, "v": np.zeros(0, np.uint16), "n": np.zeros(0, np.int8), "c": np.zeros(0, np.uint8),
                 "f": np.zeros(0, np.uint32)}
        if min(n) < 2 or not cube.any():
            if prev is not None:
                self.chunks[cid] = empty
            return
        vol = np.where(obs, vol, 1.0)
        try:
            verts, faces, _, _ = self.measure.marching_cubes(vol, 0.0)
        except (ValueError, RuntimeError):
            if prev is not None:
                self.chunks[cid] = empty
            return
        # Keep only triangles whose vertices sit in cubes with all 8 corners observed: the
        # border between observed and unobserved voxels is not a surface.
        fl = np.clip(np.floor(verts).astype(int), 0, np.array(cube.shape) - 1)
        vok = cube[fl[:, 0], fl[:, 1], fl[:, 2]]
        faces = faces[vok[faces].all(axis=1)]
        if len(faces) == 0:
            if prev is not None:
                self.chunks[cid] = empty
            return
        used, faces = np.unique(faces, return_inverse=True)
        faces = faces.reshape(-1, 3)
        verts = verts[used]
        # Normals from the volume gradient (toward free space); colours from the nearest voxel.
        gx, gy, gz = np.gradient(vol)
        vi = np.clip(np.rint(verts).astype(int), 0, np.array(vol.shape) - 1)
        nrm = np.stack([gx[tuple(vi.T)], gy[tuple(vi.T)], gz[tuple(vi.T)]], axis=1)
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-6)
        col = self._sub(self.col, i0, j0, k0, n)[tuple(vi.T)].cpu().numpy()
        world = (verts + np.array([i0, j0, k0]) + 0.5) * VOXEL
        self.chunks[cid] = {
            "ver": ver,
            "v": np.rint(world / POS_UNIT).astype(np.uint16).reshape(-1),
            "n": np.rint(nrm * 127).astype(np.int8).reshape(-1),
            "c": col.astype(np.uint8).reshape(-1),
            "f": faces.astype(np.uint32).reshape(-1),
        }

    # ----------------------------------------------------------------- output
    def updates(self, sent: dict[int, int], full: bool = False, limit: int = 6) -> list[tuple[int, dict]]:
        """Chunks whose mesh changed since `sent` (chunk id -> version viewers have)."""
        if not self.available:
            return []
        out = []
        for cid, c in list(self.chunks.items()):
            if not full and sent.get(cid) == c["ver"]:
                continue
            if not full and len(c["f"]) == 0 and sent.get(cid, 0) == 0:
                continue
            out.append((cid, c))
            if not full and len(out) >= limit:
                break
        return out
