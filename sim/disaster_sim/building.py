"""Procedurally generated multi-story industrial building on a site, as a 1 m voxel grid.

Ground truth only: the drones never read this directly. Cameras ray-cast against it and
the radio model counts walls through it; the master only ever sees camera frames.
"""
from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass, field

import numpy as np

from . import materials as M
from .config import SimConfig

DOOR_W, DOOR_H = 3, 3
DOCK_W, DOCK_H = 5, 4
WINDOW_W, WINDOW_H = 3, 2
MIN_ROOM = 8


@dataclass
class Room:
    floor: int
    x0: int
    y0: int
    x1: int  # exclusive
    y1: int
    kind: str  # hall | storage | office

    @property
    def area(self) -> int:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    @property
    def center(self) -> tuple[float, float]:
        return (self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2


@dataclass
class Entry:
    kind: str  # dock | window | hatch | collapse
    center: tuple[float, float, float]
    normal: tuple[float, float, float]  # pointing into the building
    w: float
    h: float
    blocked: bool = False

    def to_dict(self) -> dict:
        return {"kind": self.kind, "center": [round(v, 2) for v in self.center],
                "normal": list(self.normal), "w": self.w, "h": self.h, "blocked": self.blocked}


@dataclass
class Survivor:
    id: int
    x: int
    y: int
    z: int

    def to_dict(self) -> dict:
        return {"id": self.id, "x": self.x, "y": self.y, "z": self.z}


@dataclass
class Building:
    cfg: SimConfig
    vox: np.ndarray  # (SX, SY, SZ) uint8 material ids
    x0: int
    y0: int
    x1: int
    y1: int
    top: int  # z of the roof slab
    rooms: list[Room] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)
    survivors: list[Survivor] = field(default_factory=list)
    base: tuple[float, float, float] = (0.0, 0.0, 0.0)  # master antenna position
    pads: np.ndarray = field(default=None)

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.vox.shape

    def floor_base(self, k: int) -> int:
        return k * self.cfg.story

    def floor_of(self, z) -> np.ndarray:
        return np.clip(np.asarray(z) // self.cfg.story, 0, self.cfg.floors - 1).astype(int)

    def material_at(self, pts: np.ndarray) -> np.ndarray:
        """Material at world points (N,3). Below ground is asphalt, outside the grid is air."""
        pts = np.atleast_2d(pts)
        idx = np.floor(pts).astype(int)
        sx, sy, sz = self.vox.shape
        inside = ((idx[:, 0] >= 0) & (idx[:, 0] < sx) & (idx[:, 1] >= 0) & (idx[:, 1] < sy)
                  & (idx[:, 2] >= 0) & (idx[:, 2] < sz))
        out = np.where(idx[:, 2] < 0, M.ASPHALT, M.AIR).astype(np.uint8)
        ii = idx[inside]
        out[inside] = self.vox[ii[:, 0], ii[:, 1], ii[:, 2]]
        return out

    def solid(self, pts: np.ndarray) -> np.ndarray:
        return self.material_at(pts) != M.AIR

    def inside_building(self, pts: np.ndarray) -> np.ndarray:
        pts = np.atleast_2d(pts)
        return ((pts[:, 0] >= self.x0) & (pts[:, 0] < self.x1) & (pts[:, 1] >= self.y0)
                & (pts[:, 1] < self.y1) & (pts[:, 2] < self.top + 1))

    def to_dict(self) -> dict:
        packed = zlib.compress(np.ascontiguousarray(self.vox).tobytes(), 6)
        return {
            "shape": list(self.vox.shape),
            "vox": base64.b64encode(packed).decode("ascii"),
            "bbox": [self.x0, self.y0, self.x1, self.y1, self.top],
            "story": self.cfg.story,
            "floors": self.cfg.floors,
            "palette": M.palette(),
            "entries": [e.to_dict() for e in self.entries],
            "survivors": [s.to_dict() for s in self.survivors],
            "base": [round(v, 2) for v in self.base],
            "pads": np.round(self.pads, 2).tolist(),
        }


# --------------------------------------------------------------------------- generation
def generate_building(cfg: SimConfig) -> Building:
    rng = np.random.default_rng(cfg.seed)
    SX, SY, SZ = cfg.site_x, cfg.site_y, cfg.site_z
    vox = np.zeros((SX, SY, SZ), dtype=np.uint8)
    vox[:, :, 0] = M.ASPHALT

    x0 = SX - cfg.building_x - 16  # leave a yard on the west side for the base station
    y0 = (SY - cfg.building_y) // 2
    x1, y1 = x0 + cfg.building_x, y0 + cfg.building_y
    top = cfg.floors * cfg.story
    b = Building(cfg, vox, x0, y0, x1, y1, top)

    # Slabs and envelope.
    vox[x0:x1, y0:y1, 0] = M.FLOOR
    for k in range(1, cfg.floors):
        vox[x0:x1, y0:y1, k * cfg.story] = M.FLOOR
    vox[x0:x1, y0:y1, top] = M.ROOF
    vox[[x0, x1 - 1], y0:y1, 1:top] = M.BRICK
    vox[x0:x1, [y0, y1 - 1], 1:top] = M.BRICK

    # Floor plans: binary space partition into rooms joined by doors.
    keepout = np.zeros((SX, SY, cfg.floors), dtype=bool)  # door/shaft clearance per floor
    hall_floor = int(rng.integers(cfg.floors))
    for k in range(cfg.floors):
        zl = k * cfg.story + 1
        walls, doors, rooms = [], [], []
        if cfg.open_plan:  # one big hall per floor
            rooms.append((x0 + 1, y0 + 1, x1 - 1, y1 - 1, "hall"))
        else:
            _bsp(rng, x0 + 1, y0 + 1, x1 - 1, y1 - 1, 0, walls, doors, rooms, hall=(k == hall_floor), min_room=cfg.min_room)
        for axis, c, a0, a1 in walls:
            if axis == "x":
                vox[c, a0:a1, zl:zl + cfg.story - 1] = M.CONCRETE
            else:
                vox[a0:a1, c, zl:zl + cfg.story - 1] = M.CONCRETE
        for axis, c, p in doors:
            _carve_door(vox, axis, c, p, zl, DOOR_W, DOOR_H)
            if axis == "x":
                keepout[c - 2:c + 3, p - 1:p + DOOR_W + 1, k] = True
            else:
                keepout[p - 1:p + DOOR_W + 1, c - 2:c + 3, k] = True
        for (rx0, ry0, rx1, ry1, kind) in rooms:
            b.rooms.append(Room(k, rx0, ry0, rx1, ry1, kind))

    _shafts(rng, b, keepout)
    _exterior_openings(rng, b, keepout)
    _clutter(rng, b, keepout)
    _yard(rng, b)
    _survivors(rng, b, keepout)

    b.base = (12.0, SY / 2, 12.0)
    cols = int(np.ceil(np.sqrt(cfg.n_drones)))
    b.pads = np.array([(18.0 + (i % cols) * 3.5, SY / 2 - (cols - 1) * 1.75 + (i // cols) * 3.5)
                       for i in range(cfg.n_drones)])
    return b


def _bsp(rng, x0, y0, x1, y1, depth, walls, doors, rooms, hall=False, min_room=MIN_ROOM):
    MIN_ROOM = min_room
    w, h = x1 - x0, y1 - y0
    can_x, can_y = w >= 2 * MIN_ROOM + 1, h >= 2 * MIN_ROOM + 1
    if hall and depth == 1:
        rooms.append((x0, y0, x1, y1, "hall"))
        return
    stop = (not can_x and not can_y) or (depth >= 2 and rng.random() < 0.2)
    if stop:
        area = w * h
        rooms.append((x0, y0, x1, y1, "hall" if area > 700 else "storage" if area > 180 else "office"))
        return
    split_x = can_x and (not can_y or w > h * 1.2 or (h <= w * 1.2 and rng.random() < 0.5))
    if split_x:
        c = int(rng.integers(x0 + MIN_ROOM, x1 - MIN_ROOM))
        walls.append(("x", c, y0, y1))
        for p in _door_spots(rng, y0, y1):
            doors.append(("x", c, p))
        _bsp(rng, x0, y0, c, y1, depth + 1, walls, doors, rooms, hall, min_room)
        _bsp(rng, c + 1, y0, x1, y1, depth + 1, walls, doors, rooms, False, min_room)
    else:
        c = int(rng.integers(y0 + MIN_ROOM, y1 - MIN_ROOM))
        walls.append(("y", c, x0, x1))
        for p in _door_spots(rng, x0, x1):
            doors.append(("y", c, p))
        _bsp(rng, x0, y0, x1, c, depth + 1, walls, doors, rooms, hall, min_room)
        _bsp(rng, x0, c + 1, x1, y1, depth + 1, walls, doors, rooms, False, min_room)


def _door_spots(rng, a0, a1) -> list[int]:
    lo, hi = a0 + 2, max(a1 - DOOR_W - 1, a0 + 3)  # short walls (small rooms) still get a door
    spots = [int(rng.integers(lo, hi))]
    if a1 - a0 > 24 and rng.random() < 0.5:  # extra door on long walls makes loops
        p = int(rng.integers(lo, hi))
        if abs(p - spots[0]) > DOOR_W + 3:
            spots.append(p)
    return spots


def _carve_door(vox, axis, c, p, zl, width, height):
    """Open a doorway through a 1-voxel wall and paint a hazard frame around it."""
    if axis == "x":
        sl = (c, slice(p - 1, p + width + 1), slice(zl, zl + height + 1))
        hole = (c, slice(p, p + width), slice(zl, zl + height))
    else:
        sl = (slice(p - 1, p + width + 1), c, slice(zl, zl + height + 1))
        hole = (slice(p, p + width), c, slice(zl, zl + height))
    frame = vox[sl]
    frame[np.isin(frame, (M.CONCRETE, M.BRICK))] = M.DOORFRAME
    vox[hole] = M.AIR


def _shafts(rng, b: Building, keepout):
    """Stair/elevator shafts through every slab, plus collapse holes with debris below."""
    v, cfg = b.vox, b.cfg
    for _ in range(2):
        sx = int(rng.integers(b.x0 + 4, b.x1 - 8))
        sy = int(rng.integers(b.y0 + 4, b.y1 - 7))
        col = (slice(sx, sx + 4), slice(sy, sy + 3))
        for z in range(1, b.top):
            layer = v[col[0], col[1], z]
            layer[layer != M.BRICK] = M.AIR
        ring = (slice(sx - 1, sx + 5), slice(sy - 1, sy + 4))
        for k in range(1, cfg.floors):
            z = k * cfg.story
            v[ring[0], ring[1], z] = M.DOORFRAME
            v[col[0], col[1], z] = M.AIR
        keepout[sx - 2:sx + 6, sy - 2:sy + 5, :] = True
    for _ in range((int(rng.integers(1, 3)) + 2 * (cfg.damage - 1)) if cfg.floors > 1 else 0):
        k = int(rng.integers(1, cfg.floors))
        z = k * cfg.story
        hx = int(rng.integers(b.x0 + 6, b.x1 - 10))
        hy = int(rng.integers(b.y0 + 6, b.y1 - 10))
        s = int(rng.integers(3, 6))
        v[hx:hx + s, hy:hy + s, z] = M.AIR
        v[hx - 1:hx + s + 1, hy - 1:hy + s + 1, z - 1] = np.where(
            v[hx - 1:hx + s + 1, hy - 1:hy + s + 1, z - 1] == M.AIR, M.DEBRIS,
            v[hx - 1:hx + s + 1, hy - 1:hy + s + 1, z - 1])
        _pile(rng, v, hx + s // 2, hy + s // 2, z - cfg.story + 1, 4, 2)
        keepout[hx - 1:hx + s + 1, hy - 1:hy + s + 1, k - 1:k + 1] = True


def _exterior_openings(rng, b: Building, keepout):
    v, cfg = b.vox, b.cfg
    x0, y0, x1, y1, top = b.x0, b.y0, b.x1, b.y1, b.top
    # Wall descriptors: (fixed axis, coordinate, along-start, along-end, inward normal)
    sides = [("x", x0, y0, y1, (1, 0, 0)), ("x", x1 - 1, y0, y1, (-1, 0, 0)),
             ("y", y0, x0, x1, (0, 1, 0)), ("y", y1 - 1, x0, x1, (0, -1, 0))]

    def center(axis, c, p, w, zc, n):
        return (c + 0.5, p + w / 2, zc) if axis == "x" else (p + w / 2, c + 0.5, zc)

    # Loading docks on the ground floor (one blocked by debris inside).
    n_docks = int(rng.integers(2, 4))
    dock_sides = rng.choice([1, 2, 3], size=n_docks, replace=False)
    blocked_set = set(rng.choice(n_docks, size=min(cfg.damage, n_docks), replace=False).tolist())
    for i, si in enumerate(dock_sides):
        axis, c, a0, a1, n = sides[si]
        p = int(rng.integers(a0 + 6, a1 - DOCK_W - 6))
        _carve_door(v, axis, c, p, 1, DOCK_W, DOCK_H)
        blocked = i in blocked_set
        if blocked:  # rubble fills the doorway from just inside
            step = n[0] if axis == "x" else n[1]
            for depth in (1, 2):
                cc = c + step * depth
                if axis == "x":
                    v[cc, p:p + DOCK_W, 1:1 + DOCK_H] = M.DEBRIS
                else:
                    v[p:p + DOCK_W, cc, 1:1 + DOCK_H] = M.DEBRIS
        b.entries.append(Entry("dock", center(axis, c, p, DOCK_W, 1 + DOCK_H / 2, n), n, DOCK_W, DOCK_H, blocked))
        if axis == "x":
            keepout[c - 3:c + 4, p - 1:p + DOCK_W + 1, 0] = True
        else:
            keepout[p - 1:p + DOCK_W + 1, c - 3:c + 4, 0] = True

    # Windows on upper floors: glass, some broken out (open).
    for k in range(1, cfg.floors):
        zl = k * cfg.story + 2
        for axis, c, a0, a1, n in sides:
            for p in range(a0 + 4, a1 - WINDOW_W - 3, 8):
                broken = rng.random() < cfg.broken_windows
                sl = (c, slice(p, p + WINDOW_W), slice(zl, zl + WINDOW_H)) if axis == "x" else \
                     (slice(p, p + WINDOW_W), c, slice(zl, zl + WINDOW_H))
                if v[sl].min() == M.AIR:
                    continue
                v[sl] = M.AIR if broken else M.GLASS
                if broken:
                    b.entries.append(Entry("window", center(axis, c, p, WINDOW_W, zl + WINDOW_H / 2, n), n,
                                           WINDOW_W, WINDOW_H))

    # Roof hatch.
    hx = int(rng.integers(x0 + 8, x1 - 11))
    hy = int(rng.integers(y0 + 8, y1 - 11))
    v[hx - 1:hx + 4, hy - 1:hy + 4, top] = M.DOORFRAME
    v[hx:hx + 3, hy:hy + 3, top] = M.AIR
    b.entries.append(Entry("hatch", (hx + 1.5, hy + 1.5, top + 0.5), (0, 0, -1), 3, 3))

    # Collapsed corner: top-floor walls and roof gone over a 7x7 area, debris below.
    corner = int(rng.integers(4))
    cx = x0 if corner in (0, 2) else x1 - 7
    cy = y0 if corner in (0, 1) else y1 - 7
    zl = (cfg.floors - 1) * cfg.story + 1
    v[cx:cx + 7, cy:cy + 7, zl:top + 1] = M.AIR
    _pile(rng, v, cx + 3, cy + 3, zl, 5, 2)
    nx = 1 if corner in (0, 2) else -1
    ny = 1 if corner in (0, 1) else -1
    b.entries.append(Entry("collapse", (cx + 3.5, cy + 3.5, top), (nx * 0.5, ny * 0.5, -0.7), 7, 5))


def _pile(rng, v, cx, cy, z, radius, height):
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            d = np.hypot(dx, dy)
            hh = int(round(height * (1 - d / (radius + 0.5)) + rng.uniform(-0.4, 0.4)))
            for dz in range(max(hh, 0)):
                x, y = cx + dx, cy + dy
                if 0 <= x < v.shape[0] and 0 <= y < v.shape[1] and v[x, y, z + dz] == M.AIR:
                    v[x, y, z + dz] = M.DEBRIS


def _free_box(v, keepout_k, x, y, z, sx, sy, sz) -> bool:
    if keepout_k[x - 1:x + sx + 1, y - 1:y + sy + 1].any():
        return False
    return bool((v[x - 1:x + sx + 1, y - 1:y + sy + 1, z:z + sz] == M.AIR).all())


def _clutter(rng, b: Building, keepout):
    v, cfg = b.vox, b.cfg
    for room in b.rooms:
        z = room.floor * cfg.story + 1
        ko = keepout[:, :, room.floor]
        rx0, ry0, rx1, ry1 = room.x0, room.y0, room.x1, room.y1
        if room.kind == "hall":
            for _ in range(max(1, int(round(int(rng.integers(4, 9)) * cfg.clutter)))):  # machinery
                sx, sy, sz = int(rng.integers(2, 6)), int(rng.integers(2, 6)), int(rng.integers(2, 4))
                x, y = int(rng.integers(rx0 + 1, rx1 - sx - 1)), int(rng.integers(ry0 + 1, ry1 - sy - 1))
                if _free_box(v, ko, x, y, z, sx, sy, sz):
                    v[x:x + sx, y:y + sy, z:z + sz] = M.STEEL
            for _ in range(int(round(int(rng.integers(1, 4)) * min(cfg.clutter, 1.5)))):  # tanks
                r = 1.6
                x, y = int(rng.integers(rx0 + 3, rx1 - 3)), int(rng.integers(ry0 + 3, ry1 - 3))
                if _free_box(v, ko, x - 2, y - 2, z, 4, 4, 3):
                    for dx in range(-2, 2):
                        for dy in range(-2, 2):
                            if np.hypot(dx + 0.5, dy + 0.5) <= r:
                                v[x + dx, y + dy, z:z + 3] = M.TANK
        elif room.kind == "storage":
            along_x = (rx1 - rx0) >= (ry1 - ry0)
            if along_x:
                for y in range(ry0 + 2, ry1 - 2, max(3, int(round(4 / cfg.clutter)))):
                    for x in range(rx0 + 2, rx1 - 2):
                        if not ko[x, y] and v[x, y, z] == M.AIR:
                            v[x, y, z:z + 3] = M.SHELF
            else:
                for x in range(rx0 + 2, rx1 - 2, max(3, int(round(4 / cfg.clutter)))):
                    for y in range(ry0 + 2, ry1 - 2):
                        if not ko[x, y] and v[x, y, z] == M.AIR:
                            v[x, y, z:z + 3] = M.SHELF
        else:
            for _ in range(max(1, int(round(int(rng.integers(1, 4)) * cfg.clutter)))):  # desks
                x, y = int(rng.integers(rx0 + 1, rx1 - 3)), int(rng.integers(ry0 + 1, ry1 - 2))
                if _free_box(v, ko, x, y, z, 2, 1, 1):
                    v[x:x + 2, y:y + 1, z] = M.WOOD
        if rng.random() < min(0.35 * cfg.clutter * (1 + 0.5 * (cfg.damage - 1)), 0.95):
            x, y = int(rng.integers(rx0 + 2, rx1 - 2)), int(rng.integers(ry0 + 2, ry1 - 2))
            if not ko[x - 2:x + 3, y - 2:y + 3].any():
                _pile(rng, v, x, y, z, 2, 2)


def _yard(rng, b: Building):
    """Shipping containers around the yard (kept clear of the base and entries)."""
    v = b.vox
    for _ in range(5):
        horiz = rng.random() < 0.5
        sx, sy = (6, 3) if horiz else (3, 6)
        x = int(rng.integers(4, v.shape[0] - sx - 4))
        y = int(rng.integers(4, v.shape[1] - sy - 4))
        near_building = (b.x0 - 12 < x < b.x1 + 12) and (b.y0 - 12 < y < b.y1 + 12)
        near_base = x < 36
        if near_building or near_base:
            continue
        v[x:x + sx, y:y + sy, 1:4] = M.CONTAINER


def _survivors(rng, b: Building, keepout):
    v, cfg = b.vox, b.cfg
    tries = 0
    while len(b.survivors) < cfg.n_survivors and tries < 5000:
        tries += 1
        room = b.rooms[int(rng.integers(len(b.rooms)))]
        z = room.floor * cfg.story + 1
        x = int(rng.integers(room.x0, room.x1))
        y = int(rng.integers(room.y0, room.y1))
        if keepout[x, y, room.floor] or v[x, y, z] != M.AIR or v[x, y, z - 1] == M.AIR:
            continue
        if any(abs(s.x - x) + abs(s.y - y) + abs(s.z - z) < 6 for s in b.survivors):
            continue
        v[x, y, z] = M.SURVIVOR
        b.survivors.append(Survivor(len(b.survivors), x, y, z))
