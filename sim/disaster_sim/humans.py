"""Survivors as people: a figure made of capsules (head, torso, pelvis, arms, legs, shoes), dressed and posed.

The same primitives are drawn by the camera kernel (so the drones' frames show people) and by the viewer. Each primitive is
a row [ax, ay, az, bx, by, bz, radius, r, g, b]: a capsule from A to B in world metres, with a colour.
"""
from __future__ import annotations

import numpy as np

SKIN = [(238, 196, 160), (224, 172, 130), (198, 146, 105), (160, 108, 72), (110, 74, 50)]
SHIRTS = [(200, 50, 45), (235, 140, 40), (50, 90, 170), (60, 140, 80), (210, 210, 205), (60, 60, 65), (230, 200, 60), (140, 70, 150)]
PANTS = [(55, 80, 130), (40, 40, 45), (150, 130, 95), (70, 90, 70)]
SHOES = (35, 30, 28)
POSES = ("standing", "sitting", "lying")


def _standing(shirt, pants, skin):
    P = []

    def cap(a, b, r, c):
        P.append((*a, *b, r, *c))
    cap((0, 0, 1.66), (0, 0, 1.69), 0.105, skin)                       # head
    cap((0, 0, 1.52), (0, 0, 1.56), 0.045, skin)                       # neck
    cap((0, 0, 1.04), (0, 0, 1.40), 0.17, shirt)                       # torso
    cap((0, 0, 0.92), (0, 0, 1.02), 0.16, pants)                       # pelvis
    for s in (-1, 1):
        cap((0, s * 0.09, 0.08), (0, s * 0.09, 0.90), 0.085, pants)    # leg
        cap((0.05, s * 0.09, 0.05), (0.13, s * 0.09, 0.05), 0.05, SHOES)  # shoe
        cap((0, s * 0.22, 1.38), (0, s * 0.25, 1.02), 0.062, shirt)    # arm
        cap((0, s * 0.25, 1.00), (0, s * 0.25, 0.88), 0.05, skin)      # hand
    return np.array(P, dtype=float)


def _sitting(shirt, pants, skin):
    P = []

    def cap(a, b, r, c):
        P.append((*a, *b, r, *c))
    cap((0, 0, 0.92), (0, 0, 0.95), 0.105, skin)
    cap((0, 0, 0.78), (0, 0, 0.82), 0.045, skin)
    cap((0, 0, 0.26), (0, 0, 0.66), 0.17, shirt)
    cap((0, 0, 0.14), (0, 0, 0.24), 0.16, pants)
    for s in (-1, 1):
        cap((0, s * 0.09, 0.11), (0.82, s * 0.10, 0.11), 0.085, pants)
        cap((0.86, s * 0.10, 0.07), (0.94, s * 0.10, 0.07), 0.05, SHOES)
        cap((0, s * 0.22, 0.62), (0.30, s * 0.20, 0.30), 0.062, shirt)
        cap((0.31, s * 0.20, 0.28), (0.36, s * 0.20, 0.20), 0.05, skin)
    return np.array(P, dtype=float)


def _lying(shirt, pants, skin):
    st = _standing(shirt, pants, skin)
    out = st.copy()
    for k in (0, 3):   # (x, y, z) -> (z, y, 0.17): head toward +x, flat on the floor
        out[:, k] = st[:, k + 2]
        out[:, k + 2] = 0.17 + 0.0 * st[:, k]
    out[:, 1] = st[:, 1] * 1.0
    out[:, 4] = st[:, 4] * 1.0
    return out


def human(x: float, y: float, z: float, pose: str, yaw: float, rng: np.random.Generator) -> np.ndarray:
    """Primitives (n, 10) of a person whose feet (or seat, or back) are at (x, y, z), facing `yaw`."""
    shirt = SHIRTS[int(rng.integers(len(SHIRTS)))]
    pants = PANTS[int(rng.integers(len(PANTS)))]
    skin = SKIN[int(rng.integers(len(SKIN)))]
    P = {"standing": _standing, "sitting": _sitting, "lying": _lying}[pose](shirt, pants, skin)
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s], [s, c]])
    for k in (0, 3):
        P[:, k:k + 2] = P[:, k:k + 2] @ R.T
    P[:, [0, 3]] += x
    P[:, [1, 4]] += y
    P[:, [2, 5]] += z
    return P
