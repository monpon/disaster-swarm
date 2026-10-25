"""Live 2D floor plan: what the master's map says about each floor, as a small raster per floor.

Per cell of the building's footprint: 0 unknown, 1 explored free space, 2 solid (walls, furniture, whatever the map holds as
occupied at that spot). A floor is the air between two slabs, so the slab itself is left out and walls show as lines.
"""
from __future__ import annotations

import base64
import zlib

import numpy as np
from scipy import ndimage


def floorplan(sim) -> dict | None:
    m, cfg = sim.master, sim.cfg
    if not m.env_known:
        return None
    pad = 2
    sx, sy, sz = m.shape
    X0, Y0 = max(m.x0 - pad, 0), max(m.y0 - pad, 0)
    X1, Y1 = min(m.x1 + pad, sx), min(m.y1 + pad, sy)
    free = m.map.grid(m.map.free)[X0:X1, Y0:Y1, :]
    occ = m.map.grid(m.map.occupied)[X0:X1, Y0:Y1, :]
    known = m.map.grid(m.map.known)[X0:X1, Y0:Y1, :]
    plan = None if m.plan_solid is None else (m.plan_solid[X0:X1, Y0:Y1, :], m.plan_air[X0:X1, Y0:Y1, :])
    story = cfg.story
    out = []
    for k in range(cfg.floors):
        zs = slice(k * story + 1, min((k + 1) * story, sz))
        nl = zs.stop - zs.start
        img = np.zeros(occ.shape[:2], dtype=np.uint8)
        if plan is None:
            # a wall is solid in (nearly) every layer of the floor; clutter and noise fill one or two
            wall = occ[:, :, zs].sum(axis=2) >= max(2, nl - 1)
            img[free[:, :, zs].any(axis=2) & ~wall] = 1
            img[wall] = 2
        else:
            # plan-assisted: the walls are the plan's, shown where the swarm has looked
            seen = ndimage.binary_dilation(known[:, :, zs].any(axis=2), iterations=1)
            wall = plan[0][:, :, zs].sum(axis=2) >= max(2, nl - 1)
            clear = plan[1][:, :, zs].all(axis=2)
            img[seen & clear] = 1
            img[seen & wall] = 2
        out.append(base64.b64encode(zlib.compress(img.tobytes(), 3)).decode("ascii"))
    return {"x0": int(X0), "y0": int(Y0), "w": int(X1 - X0), "h": int(Y1 - Y0), "story": int(story), "floors": out}
