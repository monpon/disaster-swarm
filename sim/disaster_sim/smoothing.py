"""Point-cloud smoothing on the central node (the GX10's GPU when PyTorch+CUDA is present).

The master's point cloud holds one running-average point per 25 cm cell, so it still carries
the depth network's per-frame scale error and blocky region errors. A background worker
cleans it up in batches:

1. Every point's 5x5x5-cell neighbourhood (about 0.6 m) is gathered by the master thread
   (`VoxelMap.smooth_job`), so the worker never touches live arrays.
2. A Gaussian-weighted PCA plane fit per point gives a normal and a roughness (RMS distance
   to the plane).
3. Points in planar regions are pulled onto their plane; corners, edges and clutter, where
   the fit is not planar, are left alone, so geometry is not rounded off.
4. Isolated points and points far from their neighbours are flagged as outliers (hidden in
   the viewer, never deleted, and re-checked later as neighbours arrive).

Results are merged back by `VoxelMap.apply_smoothing`. The sim loop never waits on the worker.
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np

SIGMA = 0.30  # spatial weight of neighbours (m)
ALPHA = 0.8  # fraction of the distance to the plane that a planar point is moved
PLANAR = 0.05  # smallest/total eigenvalue below which a neighbourhood counts as planar
MIN_PLANAR_NBRS = 8
MAX_MOVE = 0.30  # never move a point further than this (m)
MIN_NBRS = 3  # fewer neighbours than this: outlier
OUTLIER_SIGMAS = 3.0
CENTER = 62  # the point itself within the 5x5x5 neighbourhood


def smooth_numpy(pos: np.ndarray, valid: np.ndarray, w: np.ndarray) -> dict:
    """pos (K,125,3), valid (K,125) bool, w (K,125) confidence -> smoothed positions etc."""
    c0 = pos[:, CENTER]
    d2 = ((pos - c0[:, None]) ** 2).sum(-1)
    g = np.exp(-d2 / (2 * SIGMA ** 2)) * valid * np.clip(w, 0.02, 2.0)
    sg = g.sum(1) + 1e-9
    cen = (g[..., None] * pos).sum(1) / sg[:, None]
    diff = pos - cen[:, None]
    cov = np.einsum("kn,kni,knj->kij", g, diff, diff) / sg[:, None, None]
    lam, vec = np.linalg.eigh(cov)
    normal = vec[:, :, 0]
    nv = valid.sum(1)
    planar = (lam[:, 0] < PLANAR * (lam.sum(1) + 1e-12)) & (nv >= MIN_PLANAR_NBRS)
    off = ((c0 - cen) * normal).sum(1)
    move = np.where(planar, -ALPHA * off, 0.0)[:, None] * normal
    move *= np.minimum(1.0, MAX_MOVE / np.maximum(np.linalg.norm(move, axis=1, keepdims=True), 1e-9))
    cnt = nv - 1
    md = (np.sqrt(d2) * valid).sum(1) / np.maximum(cnt, 1)
    have = cnt > 0
    mu, sd = (md[have].mean(), md[have].std()) if have.any() else (0.0, 0.0)
    outlier = (cnt < MIN_NBRS) | (md > mu + OUTLIER_SIGMAS * sd)
    return {
        "spos": (c0 + move).astype(np.float32),
        "normal": np.where(planar[:, None], normal, 0.0).astype(np.float32),
        "resid": np.sqrt(np.maximum(lam[:, 0], 0.0)).astype(np.float32),
        "outlier": outlier,
    }


def smooth_torch(pos, valid, w, torch, device) -> dict:
    p = torch.as_tensor(pos, device=device)
    v = torch.as_tensor(valid, device=device)
    wt = torch.as_tensor(w, device=device)
    c0 = p[:, CENTER]
    d2 = ((p - c0[:, None]) ** 2).sum(-1)
    g = torch.exp(-d2 / (2 * SIGMA ** 2)) * v * wt.clamp(0.02, 2.0)
    sg = g.sum(1) + 1e-9
    cen = (g[..., None] * p).sum(1) / sg[:, None]
    diff = p - cen[:, None]
    cov = torch.einsum("kn,kni,knj->kij", g, diff, diff) / sg[:, None, None]
    lam, vec = torch.linalg.eigh(cov.double())  # fp64: planes are nearly degenerate
    lam, vec = lam.float(), vec.float()
    normal = vec[:, :, 0]
    nv = v.sum(1)
    planar = (lam[:, 0] < PLANAR * (lam.sum(1) + 1e-12)) & (nv >= MIN_PLANAR_NBRS)
    off = ((c0 - cen) * normal).sum(1)
    move = torch.where(planar, -ALPHA * off, torch.zeros_like(off))[:, None] * normal
    move = move * torch.clamp(MAX_MOVE / move.norm(dim=1, keepdim=True).clamp_min(1e-9), max=1.0)
    cnt = nv - 1
    md = (d2.sqrt() * v).sum(1) / cnt.clamp_min(1)
    have = cnt > 0
    if bool(have.any()):
        mu, sd = md[have].mean(), md[have].std(unbiased=False)
    else:
        mu = sd = torch.zeros((), device=device)
    outlier = (cnt < MIN_NBRS) | (md > mu + OUTLIER_SIGMAS * sd)
    return {
        "spos": c0 + move,
        "normal": torch.where(planar[:, None], normal, torch.zeros_like(normal)),
        "resid": lam[:, 0].clamp_min(0).sqrt(),
        "outlier": outlier,
    }


class Smoother:
    """Background worker. `submit` a job (from `VoxelMap.smooth_job`), `poll` for its result."""

    def __init__(self, backend: str = "auto"):
        import torch
        from .gpu import DEV
        self.torch, self.device = torch, DEV
        self.backend = "cuda" if DEV.type == "cuda" else "torch-cpu"
        self.stream = torch.cuda.Stream() if DEV.type == "cuda" else None
        self.jobs: queue.Queue = queue.Queue(maxsize=1)
        self.results: queue.Queue = queue.Queue()
        self.busy = False
        self.last_ms = 0.0
        self.points_done = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="smoother", daemon=True)
        self._thread.start()

    def submit(self, job: dict) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.jobs.put(job)
        return True

    def poll(self) -> tuple[dict, dict] | None:
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        try:
            self.jobs.put_nowait(None)
        except queue.Full:
            pass

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self.jobs.get()
            if job is None:
                return
            t0 = time.perf_counter()
            try:
                if self.stream is not None:
                    self.stream.wait_stream(self.torch.cuda.default_stream())  # the job was built on the main stream
                    with self.torch.cuda.stream(self.stream):
                        out = smooth_torch(job["pos"], job["valid"], job["w"], self.torch, self.device)
                    self.stream.synchronize()
                else:
                    out = smooth_torch(job["pos"], job["valid"], job["w"], self.torch, self.device)
                self.results.put((job, out))
                self.points_done += len(job["ids"])
            except Exception as e:  # never take the sim down; report and carry on
                print(f"smoother error: {e!r}", flush=True)
            self.last_ms = (time.perf_counter() - t0) * 1000
            self.busy = False
