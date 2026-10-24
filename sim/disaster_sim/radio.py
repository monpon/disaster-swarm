"""Indoor radio: walls and slabs attenuate links; drones relay for each other.

Every node (the master's base station and each drone) can talk to every other node with a
capacity set by its signal-to-noise ratio. Each drone reaches the base over the widest
(maximum-bottleneck) route, and drones sharing a hop split its capacity. Camera frames
that don't fit the drone's share are dropped; messages wait one latency per hop plus
serialization time.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import materials as M
from .building import Building
from .config import SimConfig

TX_DBM = 20.0
NOISE_DBM = -92.0
WALL_DB = 8.0
SLAB_DB = 15.0
GLASS_DB = 2.0
THICK_DB_PER_M = 3.0
GROUND_DB = 60.0
# (min SNR dB, capacity bits/s)
TIERS = [(30.0, 20e6), (20.0, 8e6), (12.0, 2e6), (6.0, 5e5), (2.0, 1e5)]


def capacity_for(snr: np.ndarray) -> np.ndarray:
    cap = np.zeros_like(snr)
    for thr, c in reversed(TIERS):
        cap = np.where(snr >= thr, c, cap)
    return cap


def path_loss_db(d: np.ndarray) -> np.ndarray:
    """Free-space loss at 2.4 GHz with a 1 m reference."""
    return 40.0 + 20.0 * np.log10(np.maximum(d, 1.0))


def obstruction_db(materials_along: np.ndarray, step: float) -> float:
    """Loss from solid runs crossed by a straight segment (materials sampled every `step` m)."""
    solid = materials_along != M.AIR
    if not solid.any():
        return 0.0
    edges = np.flatnonzero(np.diff(np.concatenate([[0], solid.astype(np.int8), [0]])))
    loss = 0.0
    for a, b in zip(edges[::2], edges[1::2]):
        run = materials_along[a:b]
        length = (b - a) * step
        m = np.bincount(run, minlength=M.N_MATERIALS).argmax()
        if m == M.ASPHALT:
            loss += GROUND_DB
        elif m == M.GLASS:
            loss += GLASS_DB
        elif m in (M.FLOOR, M.ROOF):
            loss += SLAB_DB
        else:
            loss += WALL_DB
        loss += THICK_DB_PER_M * max(0.0, length - 1.5)
    return loss


@dataclass
class Route:
    capacity: float = 0.0  # bits/s available to this drone end-to-end
    hops: int = 0
    path: list[int] = field(default_factory=list)  # node ids from drone to base (base = -1)

    @property
    def connected(self) -> bool:
        return self.capacity > 0


class Radio:
    def __init__(self, building: Building, cfg: SimConfig, rng: np.random.Generator):
        self.b = building
        self.cfg = cfg
        self.rng = rng
        self.base = np.array(building.base)
        self.n = cfg.n_drones
        self.routes = [Route() for _ in range(self.n)]
        self.link_cap = np.zeros((self.n + 1, self.n + 1))  # node 0 = base, i+1 = drone i
        self.tokens = np.zeros(self.n)  # uplink byte budget per drone
        self.queue: list[tuple[float, int, str, int, Any]] = []  # (deliver_t, seq, dir, drone, payload)
        self._seq = 0
        self.stats = {"frames_sent": 0, "frames_dropped": 0, "bytes": 0}
        self.frame_stats = np.zeros((self.n, 2), dtype=np.int64)  # delivered, dropped per drone

    # --------------------------------------------------------------- topology
    def _materials_between(self, a: np.ndarray, b: np.ndarray, step: float = 0.5) -> np.ndarray:
        d = np.linalg.norm(b - a)
        n = max(int(d / step), 1)
        pts = a[None, :] + (b - a)[None, :] * (np.arange(n) + 0.5)[:, None] / n
        return self.b.material_at(pts)

    def update(self, pos: np.ndarray, alive: np.ndarray) -> None:
        nodes = np.vstack([self.base[None, :], pos])
        k = len(nodes)
        cap = np.zeros((k, k))
        for i in range(k):
            for j in range(i + 1, k):
                if (i and not alive[i - 1]) or not alive[j - 1]:
                    continue
                d = float(np.linalg.norm(nodes[i] - nodes[j]))
                loss = path_loss_db(np.array(d)) + obstruction_db(self._materials_between(nodes[i], nodes[j]), 0.5)
                cap[i, j] = cap[j, i] = float(capacity_for(TX_DBM - loss - NOISE_DBM))
        self.link_cap = cap

        # Widest path from the base to every node (max-bottleneck Dijkstra, ties -> fewer hops).
        width = np.zeros(k)
        hops = np.full(k, 99)
        parent = np.full(k, -1)
        width[0], hops[0] = np.inf, 0
        heap = [(-np.inf, 0, 0)]
        done = np.zeros(k, dtype=bool)
        while heap:
            w, h, u = heapq.heappop(heap)
            if done[u]:
                continue
            done[u] = True
            for v in range(k):
                if done[v] or cap[u, v] <= 0:
                    continue
                nw = min(-w, cap[u, v])
                if nw > width[v] or (nw == width[v] and h + 1 < hops[v]):
                    width[v], hops[v], parent[v] = nw, h + 1, u
                    heapq.heappush(heap, (-nw, h + 1, v))

        # Drones sharing a hop split its capacity.
        load = {}
        paths = []
        for i in range(1, k):
            p = []
            u = i
            while u > 0 and parent[u] >= 0:
                p.append((min(u, parent[u]), max(u, parent[u])))
                u = parent[u]
            ok = u == 0
            paths.append(p if ok else None)
            for e in (p if ok else []):
                load[e] = load.get(e, 0) + 1
        for i in range(self.n):
            p = paths[i]
            if p is None or not alive[i]:
                self.routes[i] = Route()
                continue
            share = min(cap[a, b] / load[(a, b)] for a, b in p)
            node_path = []
            u = i + 1
            while u > 0:
                node_path.append(u - 1)
                u = parent[u]
            node_path.append(-1)
            self.routes[i] = Route(share, len(p), node_path)

    # --------------------------------------------------------------- delivery
    def tick(self, dt: float) -> None:
        caps = np.array([r.capacity for r in self.routes]) / 8.0
        self.tokens = np.minimum(self.tokens + caps * dt, caps * 0.5)  # ~0.5 s burst

    def _push(self, t: float, direction: str, drone: int, payload, size: int) -> bool:
        r = self.routes[drone]
        if not r.connected or self.rng.random() < self.cfg.link_dropout:
            return False
        delay = r.hops * self.cfg.link_latency + size * 8.0 / r.capacity
        self._seq += 1
        heapq.heappush(self.queue, (t + delay, self._seq, direction, drone, payload))
        self.stats["bytes"] += size
        return True

    def send_frame(self, t: float, drone: int, frame, size: int) -> bool:
        """Camera frame uplink. False if the drone's share of the route can't carry it now."""
        if self.tokens[drone] < size or not self._push(t, "up", drone, frame, size):
            return False
        self.tokens[drone] -= size
        self.frame_stats[drone, 0] += 1
        return True

    def send_up(self, t: float, drone: int, msg, size: int = 96) -> bool:
        return self._push(t, "up", drone, msg, size)

    def send_down(self, t: float, drone: int, msg, size: int = 128) -> bool:
        return self._push(t, "down", drone, msg, size)

    def receive(self, t: float) -> list[tuple[str, int, Any]]:
        out = []
        while self.queue and self.queue[0][0] <= t:
            _, _, d, drone, payload = heapq.heappop(self.queue)
            out.append((d, drone, payload))
        return out
