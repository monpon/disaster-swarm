"""Frontier detection and grid path planning on the master's global map."""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from .mapping import OccupancyGrid

TILE = 8  # frontier cells are grouped into TILE x TILE cell regions
CLEARANCE = 5.0  # meters of vertical clearance required over known obstacles


@dataclass
class Frontier:
    ix: int
    iy: int
    gain: int  # number of frontier cells in the region


def find_frontiers(grid: OccupancyGrid, threshold: float, ignore: np.ndarray | None = None,
                   min_gain: int = 3) -> list[Frontier]:
    """Cells not yet properly scanned, grouped into tiles with one target each.

    `ignore` marks cells already judged unscannable (e.g. hidden by walls).
    """
    frontier = grid.quality < threshold
    if ignore is not None:
        frontier &= ~ignore
    ix, iy = np.nonzero(frontier)
    if len(ix) == 0:
        return []
    tiles = (ix // TILE) * (grid.n // TILE + 1) + (iy // TILE)
    order = np.argsort(tiles, kind="stable")
    tiles, ix, iy = tiles[order], ix[order], iy[order]
    bounds = np.flatnonzero(np.diff(tiles)) + 1
    out = []
    for gx, gy in zip(np.split(ix, bounds), np.split(iy, bounds)):
        if len(gx) < min_gain:
            continue
        cx, cy = gx.mean(), gy.mean()
        k = np.argmin((gx - cx) ** 2 + (gy - cy) ** 2)
        out.append(Frontier(int(gx[k]), int(gy[k]), len(gx)))
    return out


def blocked_mask(grid: OccupancyGrid, altitude: float) -> np.ndarray:
    """Cells a drone cruising at `altitude` must avoid, inflated by one cell."""
    blocked = grid.safe_height() > altitude - CLEARANCE
    return ndimage.binary_dilation(blocked, iterations=1)


def line_clear(blocked: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True if the straight segment a->b crosses no blocked cell (the start cell is exempt)."""
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) * 2 + 1
    xs = np.rint(np.linspace(a[0], b[0], n)).astype(int)
    ys = np.rint(np.linspace(a[1], b[1], n)).astype(int)
    away = (xs != a[0]) | (ys != a[1])
    return not blocked[xs[away], ys[away]].any()


def _nearest_free(blocked: np.ndarray, c: tuple[int, int]) -> tuple[int, int] | None:
    if not blocked[c]:
        return c
    free = np.argwhere(~blocked)
    if len(free) == 0:
        return None
    k = np.argmin(((free - np.array(c)) ** 2).sum(axis=1))
    return int(free[k, 0]), int(free[k, 1])


_NEIGHBORS = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
              (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]


def astar(blocked: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
          max_expansions: int = 40000) -> list[tuple[int, int]] | None:
    """8-connected A* returning a line-of-sight-pruned list of cells, or None."""
    start = _nearest_free(blocked, start)
    goal = _nearest_free(blocked, goal)
    if start is None or goal is None:
        return None
    if line_clear(blocked, start, goal):
        return [start, goal]
    n0, n1 = blocked.shape

    def h(c):
        dx, dy = abs(c[0] - goal[0]), abs(c[1] - goal[1])
        return max(dx, dy) + 0.4142 * min(dx, dy)

    open_heap = [(h(start), 0.0, start)]
    g = {start: 0.0}
    parent = {start: None}
    expansions = 0
    while open_heap:
        _, gc, cur = heapq.heappop(open_heap)
        if cur == goal:
            break
        if gc > g[cur]:
            continue
        expansions += 1
        if expansions > max_expansions:
            return None
        for dx, dy, w in _NEIGHBORS:
            nx, ny = cur[0] + dx, cur[1] + dy
            if not (0 <= nx < n0 and 0 <= ny < n1) or blocked[nx, ny]:
                continue
            if dx and dy and (blocked[cur[0] + dx, cur[1]] or blocked[cur[0], cur[1] + dy]):
                continue  # no cutting corners past structure
            ng = gc + w
            nb = (nx, ny)
            if ng < g.get(nb, np.inf):
                g[nb] = ng
                parent[nb] = cur
                heapq.heappush(open_heap, (ng + h(nb), ng, nb))
    if goal not in parent:
        return None
    path = [goal]
    while parent[path[-1]] is not None:
        path.append(parent[path[-1]])
    path.reverse()
    return _prune(blocked, path)


def _prune(blocked: np.ndarray, path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out = [path[0]]
    i = 0
    while i < len(path) - 1:
        j = len(path) - 1
        while j > i + 1 and not line_clear(blocked, path[i], path[j]):
            j -= 1
        out.append(path[j])
        i = j
    return out
