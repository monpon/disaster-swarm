"""3D path planning on the master's voxel map.

Drones may only fly through space the master has observed to be free (indoors), or open
air outside the building outline. A small extra cost next to occupied voxels keeps paths
centered in doorways and corridors.
"""
from __future__ import annotations

import heapq

import numpy as np
from scipy import ndimage

# 8 horizontal neighbors + straight up/down (cost = length).
_MOVES = [(1, 0, 0, 1.0), (-1, 0, 0, 1.0), (0, 1, 0, 1.0), (0, -1, 0, 1.0),
          (1, 1, 0, 1.414), (1, -1, 0, 1.414), (-1, 1, 0, 1.414), (-1, -1, 0, 1.414),
          (0, 0, 1, 1.0), (0, 0, -1, 1.0)]
NEAR_WALL_COST = 1.5
HEURISTIC_WEIGHT = 1.5
BODY_CLEARANCE = 0.40  # half-width checked along straight legs (0.21 m frame + tracking error)


class NavGrid:
    """Snapshot of passability and costs, rebuilt when the map changes."""

    def __init__(self, passable: np.ndarray, occupied: np.ndarray):
        self.shape = passable.shape
        sx, sy, sz = self.shape
        self.sy, self.sz = sy, sz
        self.passable = passable
        near = ndimage.binary_dilation(occupied, iterations=1) & passable
        # Python bytes give much faster per-element access than numpy in the A* loop.
        self._pass = passable.reshape(-1).astype(np.uint8).tobytes()
        self._near = near.reshape(-1).astype(np.uint8).tobytes()
        self._offsets = [(dx * sy * sz + dy * sz + dz, dx, dy, dz, c) for dx, dy, dz, c in _MOVES]

    def flat(self, v) -> int:
        return (int(v[0]) * self.sy + int(v[1])) * self.sz + int(v[2])

    def unflat(self, f: int) -> tuple[int, int, int]:
        x, r = divmod(f, self.sy * self.sz)
        y, z = divmod(r, self.sz)
        return x, y, z

    def ok(self, v) -> bool:
        x, y, z = (int(c) for c in v)
        sx, sy, sz = self.shape
        return 0 <= x < sx and 0 <= y < sy and 0 <= z < sz and self._pass[self.flat((x, y, z))] == 1

    def nearest_ok(self, v, radius: int = 3):
        """Closest passable voxel to v within `radius` (Chebyshev), or None."""
        v = np.floor(np.asarray(v)).astype(int)
        if self.ok(v):
            return tuple(v)
        best, bd = None, 1e9
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    c = (v[0] + dx, v[1] + dy, v[2] + dz)
                    d = dx * dx + dy * dy + 2 * dz * dz
                    if d < bd and self.ok(c):
                        best, bd = c, d
        return best

    def line_clear(self, a, b, body: float = BODY_CLEARANCE, vertical_legs: bool = False) -> bool:
        """True if a drone (half-width `body`) can fly straight between voxel centers a and b.
        With `vertical_legs`, legs that change height must be vertical, so planned paths pass
        through floor openings straight up or down instead of on a slant."""
        a, b = np.asarray(a, float) + 0.5, np.asarray(b, float) + 0.5
        d = b - a
        if vertical_legs and abs(d[2]) >= 1.0 and np.hypot(d[0], d[1]) >= 1.0:
            return False
        n = int(np.ceil(np.linalg.norm(d) / 0.35)) + 1
        center = a[None, :] + d[None, :] * np.linspace(0, 1, n)[:, None]
        h = np.array([-d[1], d[0], 0.0])
        h = h / np.linalg.norm(h) * body if np.linalg.norm(h) > 1e-6 else np.array([body, 0.0, 0.0])
        lines = [center, center + h, center - h]
        if abs(d[2]) > 1e-6 or np.linalg.norm(d[:2]) < 1e-6:  # vertical travel: check the other side too
            h2 = np.cross(d, h)
            if np.linalg.norm(h2) > 1e-6:
                h2 = h2 / np.linalg.norm(h2) * body
                lines += [center + h2, center - h2]
        pts = np.floor(np.vstack(lines)).astype(int)
        sx, sy, sz = self.shape
        if (pts < 0).any() or (pts[:, 0] >= sx).any() or (pts[:, 1] >= sy).any() or (pts[:, 2] >= sz).any():
            return False
        return bool(self.passable[pts[:, 0], pts[:, 1], pts[:, 2]].all())

    def astar(self, start, goal, max_expansions: int = 25000, partial: bool = False):
        """Voxel path from start to goal (pruned to line-of-sight waypoints), or None. With
        `partial`, an unreachable goal gives the path to the reachable cell nearest to it (go as
        far as the known-clear space allows, look, then continue)."""
        s = self.nearest_ok(start)
        g = self.nearest_ok(goal)
        if s is None or g is None:
            return None
        if self.line_clear(s, g, vertical_legs=True):
            return [s, g]
        sf, gf = self.flat(s), self.flat(g)
        gx, gy, gz = g
        pas, near, offs = self._pass, self._near, self._offsets
        sx, sy, sz = self.shape
        syz = sy * sz

        def h(f):
            x, r = divmod(f, syz)
            y, z = divmod(r, sz)
            dx, dy = abs(x - gx), abs(y - gy)
            return HEURISTIC_WEIGHT * (max(dx, dy) + 0.414 * min(dx, dy) + abs(z - gz))

        openh = [(h(sf), 0.0, sf)]
        best = {sf: 0.0}
        parent = {sf: -1}
        exp = 0
        near_f, near_h = sf, h(sf)
        while openh:
            _, gc, cur = heapq.heappop(openh)
            if cur == gf:
                break
            if gc > best[cur]:
                continue
            hc = h(cur)
            if hc < near_h:
                near_f, near_h = cur, hc
            exp += 1
            if exp > max_expansions:
                break
            x, r = divmod(cur, syz)
            y, z = divmod(r, sz)
            for off, dx, dy, dz, c in offs:
                nx, ny, nz = x + dx, y + dy, z + dz
                if not (0 <= nx < sx and 0 <= ny < sy and 0 <= nz < sz):
                    continue
                nf = cur + off
                if not pas[nf]:
                    continue
                if dx and dy and not (pas[cur + dx * syz] and pas[cur + dy * sz]):
                    continue  # no corner cutting
                if dx and dy and (near[cur + dx * syz] or near[cur + dy * sz]):
                    continue  # pass openings and corners square-on, not diagonally
                ng = gc + c + (NEAR_WALL_COST if near[nf] else 0.0)
                if ng < best.get(nf, 1e18):
                    best[nf] = ng
                    parent[nf] = cur
                    heapq.heappush(openh, (ng + h(nf), ng, nf))
        if gf not in parent:
            if not partial or near_f == sf:
                return None
            gf = near_f  # as close as the cleared space gets
        path = [gf]
        while parent[path[-1]] != -1:
            path.append(parent[path[-1]])
        path.reverse()
        cells = [self.unflat(f) for f in path]
        return self._prune(cells)

    def _prune(self, cells):
        out = [cells[0]]
        i = 0
        while i < len(cells) - 1:
            j = min(len(cells) - 1, i + 12)  # bound look-ahead to keep pruning cheap
            while j > i + 1 and not self.line_clear(cells[i], cells[j], vertical_legs=True):
                j -= 1
            out.append(cells[j])
            i = j
        return out


def to_waypoints(cells) -> list[tuple[float, float, float]]:
    """Voxel indices -> voxel-center coordinates."""
    return [(c[0] + 0.5, c[1] + 0.5, c[2] + 0.5) for c in cells]
