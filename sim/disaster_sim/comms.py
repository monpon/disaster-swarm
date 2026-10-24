"""Connectivity planning on the central node.

The master knows every drone's estimated position and (from the ESPs' neighbour reports)
the signal each one measures. This module is the part that *predicts*: what signal there
would be between two points, judged from the master's own map, so that drones are never
asked to go where they would lose contact, and relays can be placed ahead of them.

Thresholds are SNR in dB at the receiver. The radio's capacity tiers are 2 dB (0.1 Mbps),
6 (0.5), 12 (1.5), 20 (4) and 30 (8).
"""
from __future__ import annotations

import numpy as np

from . import materials as Mat
from .radio import GLASS_DB, GROUND_DB, NOISE_DBM, SLAB_DB, THICK_DB_PER_M, TX_DBM, WALL_DB, path_loss_db
from .voxelmap import FREE_T, OCC_T, VoxelMap

M_HOLD = 12.0  # below this a drone stops (1.5 Mbps tier)
M_RESUME = 16.0  # and may move again above this
M_MIN = 16.0  # planned positions must predict at least this much


class LinkModel:
    """Predicted SNR between two points from the master's map (walls = occupied runs)."""

    def __init__(self, vmap: VoxelMap, interior_flat=lambda: None):
        self.map = vmap
        self.occ = np.zeros(vmap.n, dtype=bool)
        self.unknown_in = np.zeros(vmap.n, dtype=bool)
        self._cache: dict = {}

    def refresh(self, interior: np.ndarray) -> None:
        """Snapshot the map (call once per master tick)."""
        lo = self.map.lo
        self.occ = lo >= OCC_T
        self.unknown_in = (lo > FREE_T) & (lo < OCC_T) & interior.reshape(-1)
        self._cache.clear()

    def snr(self, a: np.ndarray, b: np.ndarray) -> float:
        d = float(np.linalg.norm(b - a))
        n = max(int(d / 0.5), 1)
        pts = a[None, :] + (b - a)[None, :] * (np.arange(n) + 0.5)[:, None] / n
        flat, inside = self.map.flat_of(pts)
        occ = self.occ[flat] & inside
        unk = self.unknown_in[flat] & inside
        edges = np.flatnonzero(np.diff(np.concatenate([[0], occ.astype(np.int8), [0]])))
        loss = 0.0
        for s, e in zip(edges[::2], edges[1::2]):
            m = int(np.bincount(self.map.mat[flat[s:e]], minlength=Mat.N_MATERIALS).argmax())
            if m == Mat.ASPHALT:  # the ground
                per = GROUND_DB
            elif m == Mat.GLASS:
                per = GLASS_DB
            elif m in (Mat.FLOOR, Mat.ROOF):
                per = SLAB_DB
            else:
                per = WALL_DB
            loss += per + THICK_DB_PER_M * max(0.0, (e - s) * 0.5 - 1.5)
        loss += 0.2 * unk.sum()  # unexplored interior is assumed to have walls in it
        return float(TX_DBM - path_loss_db(np.array(d)) - loss - NOISE_DBM)

    def margin_at(self, p: np.ndarray, nodes: list[np.ndarray]) -> float:
        """Best predicted SNR from any backbone node to point p (cached per 2 m cell)."""
        key = tuple(np.floor(p / 2.0).astype(int))
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        best = max((self.snr(np.asarray(n, dtype=float), p) for n in nodes), default=-100.0)
        self._cache[key] = best
        return best


def plan_chain(model: LinkModel, path: list, start: np.ndarray, target: np.ndarray, floor: float = M_MIN) -> list | None:
    """Relay positions along a flyable path so every hop predicts >= `floor` dB: greedy
    farthest reach from `start` (minimum relays along that path). `path` is a list of
    points from near `start` to `target`. Returns [] if `target` is already covered, a list
    of positions otherwise, or None if no progress is possible (a hop cannot be bridged)."""
    pts = [np.asarray(p, dtype=float) for p in path] + [np.asarray(target, dtype=float)]
    # densify so the walk can stop at any 2 m
    dense = []
    for a, b in zip(pts[:-1], pts[1:]):
        k = max(int(np.linalg.norm(b - a) / 2.0), 1)
        dense += [a + (b - a) * s / k for s in range(k)]
    dense.append(pts[-1])
    relays, prev, i = [], np.asarray(start, dtype=float), 0
    while True:
        if model.snr(prev, dense[-1]) >= floor:
            return relays
        j = i
        while j + 1 < len(dense) and model.snr(prev, dense[j + 1]) >= floor:
            j += 1
        if j == i:
            return None  # cannot bridge from here
        relays.append(dense[j])
        prev, i = dense[j], j
        if len(relays) > 12:
            return None
