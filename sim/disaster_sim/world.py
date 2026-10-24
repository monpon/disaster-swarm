"""Procedurally generated disaster zone: city blocks, collapsed buildings, rubble, survivors."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import SimConfig

OBSTACLE_HEIGHT = 1.0  # cells taller than this count as obstacles in maps
PATCH_SIZE = 4.0  # building facades are split into ~4 m x 4 m surface patches
SIDE_NORMALS = np.array([[1, 0], [-1, 0], [0, 1], [0, -1]], dtype=float)  # +x, -x, +y, -y


@dataclass
class Facades:
    """Wall surface patches of every building (ground truth geometry).

    Arrays are indexed by patch. `wall` groups patches of one wall (building, side);
    `col`/`row` locate a patch within its wall.
    """
    center: np.ndarray  # (P, 3)
    side: np.ndarray  # (P,) index into SIDE_NORMALS
    width: np.ndarray  # (P,)
    height: np.ndarray  # (P,)
    building: np.ndarray  # (P,)
    wall: np.ndarray  # (P,)
    col: np.ndarray  # (P,)
    row: np.ndarray  # (P,)
    wall_info: list  # per wall: dict(building, side, cx, cy, length, top, n_cols, n_rows)

    @property
    def normal(self) -> np.ndarray:
        n = np.zeros((len(self.side), 3))
        n[:, :2] = SIDE_NORMALS[self.side]
        return n

    def __len__(self) -> int:
        return len(self.side)

    def to_dict(self) -> dict:
        r = lambda a, d=2: np.round(a, d).tolist()
        return {"c": r(self.center), "side": self.side.tolist(), "w": r(self.width), "h": r(self.height),
                "b": self.building.tolist()}


@dataclass
class Box:
    cx: float
    cy: float
    sx: float
    sy: float
    h: float
    yaw: float = 0.0
    tilt: float = 0.0  # visual only: collapsed buildings lean
    kind: str = "building"  # building | collapsed | rubble

    def to_dict(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v for k, v in self.__dict__.items()}


@dataclass
class Survivor:
    id: int
    x: float
    y: float
    z: float

    def to_dict(self) -> dict:
        return {"id": self.id, "x": round(self.x, 2), "y": round(self.y, 2), "z": round(self.z, 2)}


@dataclass
class World:
    cfg: SimConfig
    boxes: list[Box] = field(default_factory=list)
    survivors: list[Survivor] = field(default_factory=list)
    base: tuple[float, float] = (0.0, 0.0)
    heightmap: np.ndarray = field(default=None)  # (n, n), index [ix, iy]
    facades: Facades = field(default=None)

    @property
    def n(self) -> int:
        return int(round(self.cfg.world_size / self.cfg.cell_size))

    @property
    def origin(self) -> float:
        return -self.cfg.world_size / 2

    def cell_of(self, x, y):
        """Grid indices for world coordinates (vectorized), clipped to bounds."""
        c = self.cfg.cell_size
        ix = np.clip(((np.asarray(x) - self.origin) / c).astype(int), 0, self.n - 1)
        iy = np.clip(((np.asarray(y) - self.origin) / c).astype(int), 0, self.n - 1)
        return ix, iy

    def cell_center(self, ix, iy):
        c = self.cfg.cell_size
        return self.origin + (np.asarray(ix) + 0.5) * c, self.origin + (np.asarray(iy) + 0.5) * c

    def height_at(self, x, y):
        ix, iy = self.cell_of(x, y)
        return self.heightmap[ix, iy]

    def in_bounds(self, x, y):
        half = self.cfg.world_size / 2
        return (np.abs(x) < half) & (np.abs(y) < half)

    def collides(self, pos) -> np.ndarray:
        """True where a point (or (N,3) points) is inside terrain or a structure."""
        pos = np.atleast_2d(pos)
        h = self.height_at(pos[:, 0], pos[:, 1])
        h = np.where(self.in_bounds(pos[:, 0], pos[:, 1]), h, 0.0)
        return pos[:, 2] < h

    def pad_positions(self, n_drones: int) -> np.ndarray:
        """Landing pads in a grid around the base station."""
        cols = int(np.ceil(np.sqrt(n_drones)))
        spacing = 4.0
        pads = []
        for i in range(n_drones):
            r, c = divmod(i, cols)
            pads.append((self.base[0] + (c - (cols - 1) / 2) * spacing,
                         self.base[1] + (r - (cols - 1) / 2) * spacing))
        return np.array(pads)

    def to_dict(self) -> dict:
        return {
            "size": self.cfg.world_size,
            "cell": self.cfg.cell_size,
            "n": self.n,
            "base": [round(self.base[0], 2), round(self.base[1], 2)],
            "boxes": [b.to_dict() for b in self.boxes],
            "survivors": [s.to_dict() for s in self.survivors],
            "facades": self.facades.to_dict(),
        }


def generate_world(cfg: SimConfig) -> World:
    rng = np.random.default_rng(cfg.seed)
    world = World(cfg=cfg)
    half = cfg.world_size / 2
    street = 10.0
    pitch = 40.0
    block = pitch - street
    n_blocks = int(cfg.world_size // pitch)
    first = -half + street / 2

    base_block = (0, 0)
    world.base = (first + block / 2, first + block / 2)

    collapsed_sites = []
    for bi in range(n_blocks):
        for bj in range(n_blocks):
            if (bi, bj) == base_block:
                continue
            x0 = first + bi * pitch
            y0 = first + bj * pitch
            split = rng.choice([1, 2, 4], p=[0.3, 0.35, 0.35])
            if split == 1:
                lots = [(x0, y0, block, block)]
            elif split == 2:
                if rng.random() < 0.5:
                    lots = [(x0, y0, block / 2, block), (x0 + block / 2, y0, block / 2, block)]
                else:
                    lots = [(x0, y0, block, block / 2), (x0, y0 + block / 2, block, block / 2)]
            else:
                lots = [(x0 + dx, y0 + dy, block / 2, block / 2)
                        for dx in (0, block / 2) for dy in (0, block / 2)]
            for lx, ly, lw, lh in lots:
                if rng.random() < 0.1:
                    continue  # empty lot
                inset = rng.uniform(1.0, 3.0)
                sx, sy = lw - 2 * inset, lh - 2 * inset
                cx, cy = lx + lw / 2, ly + lh / 2
                if rng.random() < 0.08:
                    h = rng.uniform(1.15, 1.35) * cfg.max_building_height
                else:
                    h = rng.uniform(6.0, cfg.max_building_height)
                if rng.random() < 0.3:
                    h *= rng.uniform(0.2, 0.5)
                    world.boxes.append(Box(cx, cy, sx, sy, h, tilt=rng.uniform(-0.15, 0.15),
                                           yaw=rng.uniform(-0.1, 0.1), kind="collapsed"))
                    collapsed_sites.append((cx, cy, max(sx, sy)))
                    for _ in range(rng.integers(3, 8)):
                        ang = rng.uniform(0, 2 * np.pi)
                        r = max(sx, sy) / 2 + rng.uniform(0, 6)
                        world.boxes.append(_rubble(rng, cx + r * np.cos(ang), cy + r * np.sin(ang)))
                else:
                    world.boxes.append(Box(cx, cy, sx, sy, h))

    for _ in range(int(n_blocks * n_blocks * 1.5)):
        x, y = rng.uniform(-half + 3, half - 3, size=2)
        if np.hypot(x - world.base[0], y - world.base[1]) > 25:
            world.boxes.append(_rubble(rng, x, y))

    world.heightmap = _rasterize(world)
    world.facades = _build_facades(world)
    world.survivors = _place_survivors(world, rng, collapsed_sites)
    return world


def _build_facades(world: World) -> Facades:
    cols = {k: [] for k in ("center", "side", "width", "height", "building", "wall", "col", "row")}
    walls = []
    for bi, b in enumerate(world.boxes):
        if b.kind == "rubble" or b.h < 3.0:
            continue
        for side, (nx, ny) in enumerate(SIDE_NORMALS):
            length = b.sy if nx else b.sx
            cx = b.cx + nx * b.sx / 2
            cy = b.cy + ny * b.sy / 2
            n_cols = max(1, int(round(length / PATCH_SIZE)))
            n_rows = max(1, int(round(b.h / PATCH_SIZE)))
            pw, ph = length / n_cols, b.h / n_rows
            tx, ty = -ny, nx  # tangent along the wall
            wi = len(walls)
            walls.append({"building": bi, "side": side, "cx": cx, "cy": cy, "length": length,
                          "top": b.h, "n_cols": n_cols, "n_rows": n_rows})
            for c in range(n_cols):
                off = -length / 2 + (c + 0.5) * pw
                for r in range(n_rows):
                    cols["center"].append((cx + tx * off, cy + ty * off, (r + 0.5) * ph))
                    cols["side"].append(side)
                    cols["width"].append(pw)
                    cols["height"].append(ph)
                    cols["building"].append(bi)
                    cols["wall"].append(wi)
                    cols["col"].append(c)
                    cols["row"].append(r)
    arr = {k: np.array(v) for k, v in cols.items()}
    return Facades(center=arr["center"].astype(float).reshape(-1, 3), side=arr["side"].astype(int),
                   width=arr["width"].astype(float), height=arr["height"].astype(float),
                   building=arr["building"].astype(int), wall=arr["wall"].astype(int),
                   col=arr["col"].astype(int), row=arr["row"].astype(int), wall_info=walls)


def _rubble(rng, x, y) -> Box:
    return Box(x, y, rng.uniform(1.5, 4.0), rng.uniform(1.5, 4.0), rng.uniform(0.5, 2.5),
               yaw=rng.uniform(0, np.pi), kind="rubble")


def _rasterize(world: World) -> np.ndarray:
    n = world.n
    xs, ys = world.cell_center(np.arange(n), np.arange(n))
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    hm = np.zeros((n, n), dtype=np.float32)
    for b in world.boxes:
        # Rubble yaw is ignored for collision; use the bounding square.
        ex = max(b.sx, b.sy) / 2 if b.kind == "rubble" else b.sx / 2
        ey = max(b.sx, b.sy) / 2 if b.kind == "rubble" else b.sy / 2
        mask = (np.abs(X - b.cx) <= ex) & (np.abs(Y - b.cy) <= ey)
        np.maximum(hm, np.where(mask, b.h, 0.0), out=hm)
    return hm


def _place_survivors(world: World, rng, collapsed_sites) -> list[Survivor]:
    half = world.cfg.world_size / 2
    out: list[Survivor] = []
    attempts = 0
    while len(out) < world.cfg.n_survivors and attempts < 10000:
        attempts += 1
        if collapsed_sites and rng.random() < 0.6:
            cx, cy, s = collapsed_sites[rng.integers(len(collapsed_sites))]
            ang = rng.uniform(0, 2 * np.pi)
            r = s / 2 + rng.uniform(1, 8)
            x, y = cx + r * np.cos(ang), cy + r * np.sin(ang)
        else:
            x, y = rng.uniform(-half + 4, half - 4, size=2)
        if not world.in_bounds(x, y):
            continue
        h = float(world.height_at(x, y))
        if h > 3.0 or np.hypot(x - world.base[0], y - world.base[1]) < 30:
            continue
        if any(np.hypot(x - s.x, y - s.y) < 6 for s in out):
            continue
        out.append(Survivor(len(out), float(x), float(y), h))
    return out
