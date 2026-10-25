"""Survivors as people: a jointed figure made of capsules (head with hair and eyes, neck, shoulders, chest, abdomen, hips,
upper and lower limbs, hands, shoes), dressed and posed, with its own build, height and clothing.

The same primitives are drawn by the camera kernel (so the drones' frames show people) and by the viewer. Each primitive is
a row [ax, ay, az, bx, by, bz, radius, r, g, b]: a capsule from A to B in world metres, with a colour. A capsule is round, so a
body part that is wide but shallow (chest, hips) is two capsules side by side.

Figures are built standing (facing +x, y to the left, z up) from joints; sitting reuses the upper body lowered onto the floor,
lying turns the standing figure onto its back or side.
"""
from __future__ import annotations

import numpy as np

SKIN = [(238, 196, 160), (224, 172, 130), (198, 146, 105), (160, 108, 72), (110, 74, 50)]
SHIRTS = [(200, 50, 45), (235, 140, 40), (50, 90, 170), (60, 140, 80), (210, 210, 205), (60, 60, 65), (230, 200, 60), (140, 70, 150),
          (30, 60, 110), (120, 40, 40), (90, 120, 100), (170, 170, 175)]
PANTS = [(55, 80, 130), (40, 40, 45), (150, 130, 95), (70, 90, 70), (95, 95, 100), (35, 50, 90), (110, 85, 60)]
HAIR = [(25, 20, 18), (60, 40, 28), (110, 75, 40), (200, 170, 100), (140, 140, 140), (15, 12, 10)]
SHOES = [(35, 30, 28), (235, 235, 230), (90, 60, 40), (40, 55, 90)]
EYE = (25, 22, 22)
POSES = ("standing", "sitting", "lying")


class _Body:
    def __init__(self):
        self.P: list[tuple] = []

    def cap(self, a, b, r, c) -> None:
        self.P.append((*a, *b, r, *c))

    def pair(self, x, z0, z1, y, r, c) -> None:
        """A wide, shallow part: one capsule on each side of the midline."""
        for s in (-1, 1):
            self.cap((x, s * y, z0), (x, s * y, z1), r, c)


def _upper(B: _Body, shirt, skin, hair, sleeves: bool, dz: float, lean: float, arms, rng) -> None:
    """Head to hips of a standing person, lowered by `dz` and leaning forward by `lean` m at the head (sitting reuses it)."""
    def at(x, y, z):   # lowered, and sheared forward in proportion to the height above the hips
        return (x + lean * max(z - 0.90, 0.0) / 0.87, y, z - dz)

    B.cap(at(0.0, 0, 1.61), at(0.0, 0, 1.69), 0.08, skin)                          # head
    B.cap(at(-0.035, 0, 1.675), at(-0.035, 0, 1.715), 0.078, hair)                 # hair: crown and back of the head
    for s in (-1, 1):
        B.cap(at(0.074, s * 0.033, 1.672), at(0.074, s * 0.033, 1.674), 0.0125, EYE)   # eyes
        B.cap(at(0.0, s * 0.082, 1.64), at(0.0, s * 0.082, 1.66), 0.02, skin)      # ears
    B.cap(at(0.088, 0, 1.625), at(0.094, 0, 1.64), 0.016, skin)                     # nose
    B.cap(at(0, 0, 1.50), at(0, 0, 1.57), 0.05, skin)                               # neck
    B.cap(at(0, -0.185, 1.43), at(0, 0.185, 1.43), 0.052, shirt)                    # shoulder line
    for s in (-1, 1):
        B.cap(at(0, s * 0.07, 1.20), at(0, s * 0.07, 1.38), 0.115, shirt)           # chest
        B.cap(at(0, s * 0.065, 1.00), at(0, s * 0.065, 1.16), 0.105, shirt)         # abdomen
    for s, (e, w) in zip((-1, 1), arms):    # shoulder -> elbow -> wrist (relative offsets, x forward / y out / z down)
        S = at(0, s * 0.205, 1.40)
        E = (S[0] + e[0], S[1] + s * e[1], S[2] - e[2])
        W = (E[0] + w[0], E[1] + s * w[1], E[2] - w[2])
        B.cap(S, E, 0.048, shirt)                                                   # upper arm (sleeve)
        B.cap(E, W, 0.039, shirt if sleeves else skin)                              # forearm
        B.cap(W, (W[0] + 0.04, W[1], W[2] - 0.085), 0.034, skin)                    # hand


def _hips(B: _Body, pants, dz: float) -> None:
    B.pair(0, 0.90 - dz, 0.98 - dz, 0.075, 0.10, pants)


def _legs(B: _Body, pants, skin, shoes, shorts: bool, knee, ankle, hip_z: float) -> None:
    """Hip -> knee -> ankle for each leg; `knee` and `ankle` are (x, y offset, z) per side."""
    for s, k, a in zip((-1, 1), knee, ankle):
        H = (0.0, s * 0.09, hip_z)
        K = (k[0], s * (0.09 + k[1]), k[2])
        A = (a[0], s * (0.09 + a[1]), a[2])
        B.cap(H, K, 0.078, pants)                                                   # thigh
        B.cap(K, A, 0.055, skin if shorts else pants)                               # shin
        B.cap((A[0] - 0.04, A[1], 0.047), (A[0] + 0.14, A[1], 0.047), 0.047, shoes) # shoe


def _figure(pose: str, rng: np.random.Generator) -> np.ndarray:
    shirt = SHIRTS[int(rng.integers(len(SHIRTS)))]
    pants = PANTS[int(rng.integers(len(PANTS)))]
    skin = SKIN[int(rng.integers(len(SKIN)))]
    hair = HAIR[int(rng.integers(len(HAIR)))]
    shoes = SHOES[int(rng.integers(len(SHOES)))]
    sleeves = bool(rng.random() < 0.45)
    shorts = bool(rng.random() < 0.2)
    j = lambda a=0.02: float(rng.uniform(-a, a))   # a little individual variation in every joint
    B = _Body()
    if pose == "sitting":
        # on the floor, knees up, leaning a little forward, forearms resting on the knees
        arms = [((0.10 + j(), 0.03, 0.27), (0.15, 0.0, 0.10)) for _ in (0, 1)]
        _upper(B, shirt, skin, hair, sleeves, 0.78, 0.06 + j(0.03), arms, rng)
        _hips(B, pants, 0.78)
        _legs(B, pants, skin, shoes, shorts,
              [(0.38 + j(), 0.05 + j(), 0.31)] * 2, [(0.60 + j(), 0.03, 0.09)] * 2, 0.12)
    else:
        arms = [((0.03 + j(), 0.025, 0.28), (0.04 + j(), 0.01, 0.24)) for _ in (0, 1)]
        _upper(B, shirt, skin, hair, sleeves, 0.0, 0.0, arms, rng)
        _hips(B, pants, 0.0)
        fwd = float(rng.uniform(0.04, 0.12))   # a relaxed stance: one foot a little ahead of the other
        _legs(B, pants, skin, shoes, shorts,
              [(fwd * 0.5, 0.0, 0.50), (-fwd * 0.3, 0.0, 0.50)], [(fwd, 0.0, 0.09), (-fwd * 0.7, 0.0, 0.09)], 0.90)
    P = np.array(B.P, dtype=float)
    if pose == "standing":   # height and build
        hs, ws = float(rng.uniform(0.93, 1.04)), float(rng.uniform(0.9, 1.12))
        for k in (2, 5):
            P[:, k] *= hs
        for k in (1, 4):
            P[:, k] *= ws
        P[:, 6] *= np.sqrt(ws)
    return P


def _lie(P: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Turn a standing figure onto its back (head toward +x) or its side, resting on the floor."""
    out = P.copy()
    if rng.random() < 0.7:   # on the back, face up: (x, y, z) -> (z, y, x + body depth)
        for k in (0, 3):
            out[:, k] = P[:, k + 2]
            out[:, k + 2] = P[:, k] + 0.125
    else:                    # on the side: (x, y, z) -> (z, x, y + body width)
        for k in (0, 3):
            out[:, k] = P[:, k + 2]
            out[:, k + 1] = P[:, k]
            out[:, k + 2] = P[:, k + 1] + 0.29
    out[:, [2, 5]] = np.maximum(out[:, [2, 5]], out[:, [6]] * 0.9)   # nothing below the floor
    return out


def human(x: float, y: float, z: float, pose: str, yaw: float, rng: np.random.Generator) -> np.ndarray:
    """Primitives (n, 10) of a person whose feet (or seat, or back) are at (x, y, z), facing `yaw`."""
    P = _figure("standing" if pose == "lying" else pose, rng)
    if pose == "lying":
        P = _lie(P, rng)
    c, s = np.cos(yaw), np.sin(yaw)
    R = np.array([[c, -s], [s, c]])
    for k in (0, 3):
        P[:, k:k + 2] = P[:, k:k + 2] @ R.T
    P[:, [0, 3]] += x
    P[:, [1, 4]] += y
    P[:, [2, 5]] += z
    return P
