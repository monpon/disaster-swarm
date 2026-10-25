"""Voxel materials: ids, names and base colors (the colors a camera sees)."""
import numpy as np

AIR = 0
ASPHALT = 1
CONCRETE = 2
BRICK = 3
FLOOR = 4
ROOF = 5
STEEL = 6
SHELF = 7
TANK = 8
DEBRIS = 9
DOORFRAME = 10
GLASS = 11
WOOD = 12
SURVIVOR = 13
CONTAINER = 14

NAMES = ["air", "asphalt", "concrete", "brick", "floor", "roof", "steel", "shelf", "tank",
         "debris", "doorframe", "glass", "wood", "survivor", "container"]

# Chosen to stay distinguishable after shading and noise, so the master can classify
# materials from camera color alone.
COLORS = np.array([
    [0, 0, 0],
    [46, 48, 54],
    [168, 166, 158],
    [158, 74, 52],
    [112, 122, 134],
    [78, 92, 116],
    [64, 108, 156],
    [226, 128, 32],
    [214, 220, 226],
    [128, 104, 78],
    [242, 204, 36],
    [140, 196, 226],
    [140, 96, 56],
    [255, 48, 64],
    [36, 150, 92],
], dtype=np.uint8)

N_MATERIALS = len(NAMES)


def palette() -> list[dict]:
    return [{"id": i, "name": NAMES[i], "rgb": COLORS[i].tolist()} for i in range(N_MATERIALS)]
