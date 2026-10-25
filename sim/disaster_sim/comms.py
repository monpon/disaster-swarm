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

import torch

from .gcomms import CoverageField, World, snr_pairs
from .gpu import DEV
from .voxelmap import FREE_T, OCC_T, VoxelMap

M_HOLD = 12.0  # below this a drone stops (1.5 Mbps tier)
M_RESUME = 16.0  # and may move again above this
M_MIN = 16.0  # planned positions must predict at least this much


class LinkModel:
    """Predicted SNR from the master's map (walls = occupied runs): pairwise queries in batches and a
    coverage field over the whole site for 'is this place covered'. Runs on the Rust core when in use
    (one kernel per query), else as torch ops on the GPU."""

    def __init__(self, vmap):
        self.map = vmap
        self.rust = getattr(vmap, "rust", False)
        self.world: World | None = None
        self.field = CoverageField(vmap.shape)
        self._interior_id = None
        self._interior_t = None

    def refresh(self, interior: np.ndarray) -> None:
        """Snapshot the map (call once per master tick)."""
        m = self.map
        if self.rust:
            if self._interior_id is not id(interior):
                m.core.set_interior(np.ascontiguousarray(interior, dtype=np.uint8))
                self._interior_id = id(interior)
            return
        if self._interior_id is not id(interior):
            self._interior_t = torch.as_tensor(interior.reshape(-1), device=DEV)
            self._interior_id = id(interior)
        unk = (m.g_lo > FREE_T) & (m.g_lo < OCC_T) & self._interior_t
        self.world = World(m.shape, m.g_lo >= OCC_T, m.g_mat, unk)

    def snr_many(self, a, b) -> np.ndarray:
        """SNR (dB) for P pairs of points (numpy (P,3) each)."""
        a32 = np.ascontiguousarray(np.asarray(a, dtype=np.float32).reshape(-1, 3))
        b32 = np.ascontiguousarray(np.asarray(b, dtype=np.float32).reshape(-1, 3))
        if self.rust:
            return np.asarray(self.map.core.link_snr(a32, b32, 1))
        return snr_pairs(self.world, torch.as_tensor(a32, device=DEV), torch.as_tensor(b32, device=DEV)).cpu().numpy()

    def snr(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(self.snr_many(np.asarray(a)[None, :], np.asarray(b)[None, :])[0])

    def update_coverage(self, nodes: list[np.ndarray], now: float) -> None:
        self.field.update(self.snr_many, nodes, now)

    def margin_at(self, p: np.ndarray, nodes=None) -> float:
        """Predicted signal at p from the backbone nodes of the last `update_coverage`."""
        return self.field.margin(np.asarray(p, dtype=float))


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
    dense = np.asarray(dense)
    relays, prev, i = [], np.asarray(start, dtype=float), 0
    while True:
        s = model.snr_many(np.repeat(prev[None, :], len(dense) - i, 0), dense[i:])  # reach from prev to every later point
        if s[-1] >= floor:
            return relays
        bad = np.flatnonzero(s[1:] < floor)  # the walk stops at the first point it cannot reach
        j = i + (int(bad[0]) if len(bad) else len(s) - 1)
        if j == i:
            return None  # cannot bridge from here
        relays.append(dense[j])
        prev, i = dense[j], j
        if len(relays) > 12:
            return None
