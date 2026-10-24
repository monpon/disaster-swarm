"""Closed-loop entry through an opening, steered from the live depth frame.

The master's map and pose estimate carry metre-scale drift that differs from drone to
drone, so the last few metres of an entry cannot be flown on map coordinates. Instead the
drone stops in front of the opening, the master finds the opening in the drone's own latest
depth frame, and steers on where it appears in that frame. Over the short final approach
the VIO's *relative* motion is accurate, so progress through the opening is dead-reckoned.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

OPEN_MARGIN = 1.5  # m behind the facade for a pixel to count as "open"
MIN_BLOB_PX = 10


def ray_angles(body_rays: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth (left positive) and elevation (up positive) of each body-frame pixel ray."""
    az = np.arctan2(body_rays[:, 1], body_rays[:, 0])
    el = np.arctan2(body_rays[:, 2], np.hypot(body_rays[:, 0], body_rays[:, 1]))
    return az, el


def opening_cue(depth: np.ndarray, az: np.ndarray, el: np.ndarray, expected: np.ndarray) -> dict | None:
    """Find the opening in a depth frame. `depth` (H, W) metres, 0 = no return; `expected` is
    the (az, el) where the master's map says the opening should be. Returns the opening's
    angular centre, the facade distance and how much of the frame it fills, or None."""
    h, w = depth.shape
    d = depth.reshape(-1)
    valid = d > 0
    if valid.sum() < 20:
        wall = None
        open_ = np.ones(h * w, dtype=bool)  # nothing in range ahead: everything is "open"
    else:
        wall = float(np.percentile(d[valid], 30))
        open_ = ~valid | (d > wall + OPEN_MARGIN)
    lab, n = ndimage.label(open_.reshape(h, w))
    if n == 0:
        return None
    lab = lab.reshape(-1)
    best, best_cost = None, 1e9
    for k in range(1, n + 1):
        m = lab == k
        cnt = int(m.sum())
        if cnt < MIN_BLOB_PX:
            continue
        a, e = float(az[m].mean()), float(el[m].mean())
        cost = np.hypot(a - expected[0], e - expected[1]) - 0.002 * cnt
        top = bool(m.reshape(h, w)[0].any())  # touching the top edge: more likely sky than a hole
        cost += 0.4 if top else 0.0
        if cost < best_cost:
            best, best_cost = (a, e, cnt), cost
    if best is None:
        return None
    return {"az": best[0], "el": best[1], "d": wall, "fill": best[2] / (h * w)}


def servo_sticks(cue: dict, d0: float, clearance: float) -> tuple[float, float, float, float]:
    """(vx, vy, vz, yaw_rate) that centre the opening in view and creep forward once it is
    centred. `clearance` is the nearest depth straight ahead (stop if a wall is close)."""
    d = max(cue["d"] if cue["d"] is not None else d0, 1.5)
    lat = d * np.tan(cue["az"])
    vert = d * np.tan(cue["el"])
    vy = float(np.clip(1.0 * lat, -0.5, 0.5))
    vz = float(np.clip(1.0 * vert, -0.4, 0.4))
    yaw = float(np.clip(1.5 * cue["az"], -0.8, 0.8))
    centred = abs(cue["az"]) < 0.15 and abs(lat) < 0.4 and abs(vert) < 0.4
    vx = 0.5 if centred and clearance > 0.8 else 0.0
    return vx, vy, vz, yaw
