"""Metric model of an opening (door, dock, window) from one drone's own depth frame.

The master's map has 1 m voxels and metre-scale drift, so the shape of an opening in it is a ragged bounding box. A
drone standing a few metres in front of the wall sees the opening directly: the pixels whose depth runs well past the
wall are the opening. Back-projecting those pixels onto the wall plane gives an axis-aligned rectangle in metres, which
is what the mesh draws, the planner opens and the servo steers on.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

DRONE_SIZE = 0.3  # m: the airframe is 30 x 30 x 15 cm
SIDE_MARGIN = 0.35  # m kept clear on each side of the drone
MIN_W = DRONE_SIZE + 2 * SIDE_MARGIN  # 1.0 m
MIN_H = 0.8
MIN_FILL = 0.8
THROUGH = 1.0  # m past the wall plane for a pixel to count as looking through
MIN_PIXELS = 30
MAX_W, MAX_H = 9.0, 8.0  # larger than any door, dock or window: not something to fly through as one opening


def wall_scale(d: np.ndarray, t: np.ndarray, ok_ray: np.ndarray) -> float:
    """How much farther (or nearer) the wall really is than the pose estimate says: the lower third of depth / plane
    distance over the frame (the wall dominates; what is seen through an opening is farther, so it sits above)."""
    sel = ok_ray & (d > 0.0)
    if sel.sum() < 200:
        return 1.0
    return float(np.clip(np.percentile(d[sel] / t[sel], 30), 0.6, 1.6))


def plane_scale(depth: np.ndarray, rays: np.ndarray, pos: np.ndarray, yaw: float, axis: int, face: float) -> float:
    """`wall_scale` for a wall plane `axis = face` seen from a drone at `pos` / `yaw`."""
    c, s = np.cos(yaw), np.sin(yaw)
    da = c * rays[:, axis] - s * rays[:, 1] if axis == 0 else s * rays[:, 0] + c * rays[:, 1]
    t = (face - pos[axis]) / np.where(np.abs(da) < 1e-6, 1e-6, da)
    return wall_scale(depth.reshape(-1), t, (t > 0.5) & (t < 60.0))


def fit_opening(depth: np.ndarray, rays: np.ndarray, pos: np.ndarray, yaw: float, axis: int, face: float,
                center: np.ndarray, margin: float = 1.5) -> dict | None:
    """Fit the opening near `center` in the wall plane `axis = face` (axis 0/1 = x/y) from a depth frame.
    `depth` (H, W) metres (0 = no return), `rays` (H*W, 3) body-frame unit rays, `pos`/`yaw` the drone's pose estimate.
    Returns {u0, u1, v0, v1, w, h, center, fill, n, ok, d, az, el}: the rectangle in the plane's (axis+1, axis+2)
    coordinates and where its centre appears from the drone; `ok` says it is big and clean enough to fly through."""
    H, W = depth.shape
    c, s = np.cos(yaw), np.sin(yaw)
    dirs = np.stack([c * rays[:, 0] - s * rays[:, 1], s * rays[:, 0] + c * rays[:, 1], rays[:, 2]], axis=1)
    da = dirs[:, axis]
    t = (face - pos[axis]) / np.where(np.abs(da) < 1e-6, 1e-6, da)
    ok_ray = (t > 0.5) & (t < 60.0)
    d = depth.reshape(-1)
    t = t * wall_scale(d, t, ok_ray)   # the drone's position drifts: take the wall's distance from the frame itself
    P = pos[None, :] + dirs * t[:, None]
    ua, va = (axis + 1) % 3, (axis + 2) % 3
    u, v = P[:, ua], P[:, va]
    cu, cv = center[ua], center[va]
    through = ok_ray & ((d <= 0.0) | (d > t + THROUGH))
    roi = ok_ray & (np.abs(u - cu) < margin + 6.0) & (np.abs(v - cv) < margin + 4.0)
    m = (through & roi).reshape(H, W)
    lab, n = ndimage.label(m)
    if n == 0:
        return None
    best, best_cost = None, 1e9
    for k in range(1, n + 1):
        sel = lab == k
        cnt = int(sel.sum())
        if cnt < MIN_PIXELS:
            continue
        flat = sel.reshape(-1)
        cost = float(np.hypot(np.median(u[flat]) - cu, np.median(v[flat]) - cv)) - 0.0005 * cnt
        if cost < best_cost:
            best, best_cost = flat, cost
    if best is None:
        return None
    u0, u1 = np.percentile(u[best], [2, 98])
    v0, v1 = np.percentile(v[best], [2, 98])
    inside = ok_ray & roi & (u >= u0) & (u <= u1) & (v >= v0) & (v <= v1)
    fill = float(through[inside].mean()) if inside.any() else 0.0
    w, h = float(u1 - u0), float(v1 - v0)
    ctr = np.zeros(3)
    ctr[axis], ctr[ua], ctr[va] = face, (u0 + u1) / 2, (v0 + v1) / 2
    to = np.array([c * (ctr - pos)[0] + s * (ctr - pos)[1], -s * (ctr - pos)[0] + c * (ctr - pos)[1], (ctr - pos)[2]])
    return {"u0": float(u0), "u1": float(u1), "v0": float(v0), "v1": float(v1), "w": w, "h": h, "center": ctr,
            "fill": fill, "n": int(best.sum()), "ok": bool(MIN_W <= w <= MAX_W and MIN_H <= h <= MAX_H and fill >= MIN_FILL),
            "d": float(np.linalg.norm(to)), "az": float(np.arctan2(to[1], to[0])),
            "el": float(np.arctan2(to[2], np.hypot(to[0], to[1])))}
