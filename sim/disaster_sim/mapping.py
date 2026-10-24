"""2.5D occupancy grid with per-cell scan quality.

Each cell stores its best measurement so far: state (unknown/free/obstacle), measured
height, the height's uncertainty (sigma) and a quality in [0, 1] that falls with the
distance it was measured from. Closer scans replace farther ones, so the map sharpens
as drones get near. A cell is "properly scanned" once its quality reaches the threshold.
"""
from __future__ import annotations

import numpy as np

from .world import OBSTACLE_HEIGHT

UNKNOWN, FREE, OBSTACLE = 0, 1, 2


class ScanModel:
    """Measurement quality and height noise as a function of distance to the surface."""

    def __init__(self, near: float, far: float, proper_range: float):
        self.near = near
        self.far = far
        self.threshold = float(self.quality(np.array(proper_range)))

    def quality(self, dist: np.ndarray) -> np.ndarray:
        return np.clip(1.0 - (dist - self.near) / (self.far - self.near), 0.0, 1.0)

    @staticmethod
    def sigma(dist: np.ndarray) -> np.ndarray:
        return 0.1 + 0.05 * dist


def classify(h: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Obstacle only when the measurement is confidently above ground level."""
    return np.where(h > OBSTACLE_HEIGHT + 1.5 * sigma, OBSTACLE, FREE).astype(np.int8)


class OccupancyGrid:
    def __init__(self, n: int):
        self.n = n
        self.state = np.zeros((n, n), dtype=np.int8)
        self.height = np.zeros((n, n), dtype=np.float32)
        self.sigma = np.zeros((n, n), dtype=np.float32)
        self.quality = np.zeros((n, n), dtype=np.float32)
        self.stamp = np.full((n, n), -1, dtype=np.int64)  # tick the cell last changed
        self.seen = np.full((n, n), -1.0, dtype=np.float32)  # sim time of last proper scan
        self.seen_tick = np.full((n, n), -1, dtype=np.int64)

    def observe(self, idx: np.ndarray, dist: np.ndarray, true_heights: np.ndarray, tick: int,
                t: float, model: ScanModel, rng: np.random.Generator) -> int:
        """Record a camera view: flat cell indices and the distance each was seen from.

        Returns the number of cells whose measurement improved.
        """
        if len(idx) == 0:
            return 0
        q = model.quality(dist)
        proper = q >= model.threshold
        self.seen.flat[idx[proper]] = t
        self.seen_tick.flat[idx[proper]] = tick
        better = q > self.quality.flat[idx] + 1e-3
        if not better.any():
            return 0
        sel = idx[better]
        sg = model.sigma(dist[better])
        h = np.maximum(true_heights.flat[sel] + rng.normal(0.0, sg), 0.0)
        self.state.flat[sel] = classify(h, sg)
        self.height.flat[sel] = h
        self.sigma.flat[sel] = sg
        self.quality.flat[sel] = q[better]
        self.stamp.flat[sel] = tick
        return int(better.sum())

    def cells_since(self, tick: int):
        """(idx, state, height, sigma, quality) for cells that changed after `tick`."""
        idx = np.flatnonzero(self.stamp > tick)
        return (idx, self.state.flat[idx].copy(), self.height.flat[idx].copy(),
                self.sigma.flat[idx].copy(), self.quality.flat[idx].copy())

    def apply_cells(self, idx, states, heights, sigmas, qualities, tick: int) -> int:
        """Merge cells from another map, keeping whichever measurement has higher quality."""
        if len(idx) == 0:
            return 0
        idx = np.asarray(idx)
        qualities = np.asarray(qualities)
        better = qualities > self.quality.flat[idx] + 1e-3
        sel = idx[better]
        self.state.flat[sel] = np.asarray(states)[better]
        self.height.flat[sel] = np.asarray(heights)[better]
        self.sigma.flat[sel] = np.asarray(sigmas)[better]
        self.quality.flat[sel] = qualities[better]
        self.stamp.flat[sel] = tick
        return int(better.sum())

    def seen_since(self, tick: int):
        """Flat indices and times of cells properly scanned after `tick`."""
        idx = np.flatnonzero(self.seen_tick > tick)
        return idx, self.seen.flat[idx].copy()

    def apply_seen(self, idx: np.ndarray, times: np.ndarray) -> None:
        if len(idx):
            self.seen.flat[idx] = np.maximum(self.seen.flat[idx], times)

    def merge(self, other: "OccupancyGrid", tick: int) -> int:
        return self.apply_cells(*other.cells_since(-10), tick=tick)

    def safe_height(self) -> np.ndarray:
        """Conservative structure height for collision avoidance: obstacles padded by 2 sigma."""
        return np.where(self.state == OBSTACLE, self.height + 2.0 * self.sigma, 0.0)

    @property
    def known(self) -> np.ndarray:
        return self.state != UNKNOWN

    def coverage(self) -> float:
        """Fraction of cells seen at any quality."""
        return float(self.known.mean())

    def scanned(self, threshold: float) -> float:
        """Fraction of cells properly scanned."""
        return float((self.quality >= threshold).mean())


class FacadeMap:
    """Best measurement of every building wall patch: quality, a measured offset along the
    wall normal (noise; rough scans look bumpy) and the time of the last proper scan."""

    def __init__(self, n_patches: int):
        self.n = n_patches
        self.quality = np.zeros(n_patches, dtype=np.float32)
        self.offset = np.zeros(n_patches, dtype=np.float32)
        self.sigma = np.zeros(n_patches, dtype=np.float32)
        self.stamp = np.full(n_patches, -1, dtype=np.int64)
        self.seen = np.full(n_patches, -1.0, dtype=np.float32)
        self.seen_tick = np.full(n_patches, -1, dtype=np.int64)

    def observe(self, idx: np.ndarray, dist: np.ndarray, facing: np.ndarray, tick: int, t: float,
                model: ScanModel, rng: np.random.Generator) -> int:
        """`facing` is the cosine between the view ray and the wall normal (1 = head-on)."""
        if len(idx) == 0:
            return 0
        q = model.quality(dist) * (0.35 + 0.65 * np.clip(facing, 0.0, 1.0))
        proper = q >= model.threshold
        self.seen[idx[proper]] = t
        self.seen_tick[idx[proper]] = tick
        better = q > self.quality[idx] + 1e-3
        if not better.any():
            return 0
        sel = idx[better]
        sg = model.sigma(dist[better]) / np.maximum(facing[better], 0.3)
        self.quality[sel] = q[better]
        self.sigma[sel] = sg
        self.offset[sel] = rng.normal(0.0, sg)
        self.stamp[sel] = tick
        return int(better.sum())

    def since(self, tick: int):
        idx = np.flatnonzero(self.stamp > tick)
        return idx, self.quality[idx].copy(), self.offset[idx].copy(), self.sigma[idx].copy()

    def apply(self, idx, quality, offset, sigma, tick: int) -> int:
        if len(idx) == 0:
            return 0
        idx = np.asarray(idx)
        quality = np.asarray(quality)
        better = quality > self.quality[idx] + 1e-3
        sel = idx[better]
        self.quality[sel] = quality[better]
        self.offset[sel] = np.asarray(offset)[better]
        self.sigma[sel] = np.asarray(sigma)[better]
        self.stamp[sel] = tick
        return int(better.sum())

    def seen_since(self, tick: int):
        idx = np.flatnonzero(self.seen_tick > tick)
        return idx, self.seen[idx].copy()

    def apply_seen(self, idx, times) -> None:
        if len(idx):
            self.seen[idx] = np.maximum(self.seen[idx], times)

    def scanned(self, threshold: float) -> float:
        return float((self.quality >= threshold).mean()) if self.n else 1.0
