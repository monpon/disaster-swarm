"""JSON messages streamed to the browser viewer.

Bulk arrays (voxel deltas, camera frames) travel as base64 little-endian binary inside the
JSON so a single text WebSocket carries everything.
"""
from __future__ import annotations

import base64

import numpy as np

from . import materials as M
from .sim import Simulation

SEEN_UNITS_PER_S = 2  # proper-scan times are quantized to half seconds (uint16, 0 = never)
MAX_TARGETS = 600


def b64(a: np.ndarray, dtype: str) -> str:
    return base64.b64encode(np.ascontiguousarray(a, dtype=dtype).tobytes()).decode("ascii")


def world_message(sim: Simulation) -> dict:
    return {
        "type": "world",
        "building": sim.b.to_dict(),
        "materials": M.NAMES,
        "config": sim.cfg.to_dict(),
    }


class MapStream:
    """Cursor into the master's map for the shared broadcast: what viewers already have."""

    def __init__(self, sim: Simulation):
        self.sim = sim
        self.tick = -1
        self.pts_sent = 0
        self.seen_sent = sim.master.map.seen.copy()

    def deltas(self, full: bool = False) -> dict:
        """Map voxels changed since the last broadcast (or everything occupied, for a new client)."""
        m = self.sim.master.map
        idx, occ, mat, rgb, q = m.deltas_since(-1 if full else self.tick)
        if not full:
            self.tick = self.sim.master.tick
        o = np.flatnonzero(occ)
        free = idx[~occ] if not full else np.zeros(0, dtype=np.int64)  # a new client starts empty
        p0, p1 = (0 if full else self.pts_sent), m.npts
        if not full:
            self.pts_sent = p1
        return {"idx": b64(idx[o], "<i4"), "mat": b64(mat[o], "u1"), "rgb": b64(rgb[o], "<u2"),
                "q": b64(q[o], "u1"), "free": b64(free, "<i4"), "n": int(len(o)),
                "pts": b64(m.pts[p0:p1], "<u2"), "pcol": b64(m.pcol[p0:p1], "u1"), "np": int(p1 - p0),
                "ptotal": int(p1)}

    def seen(self, full: bool = False) -> dict:
        """Proper-scan times of surfaces re-scanned since the last broadcast (or all, if full)."""
        m = self.sim.master.map
        changed = (m.seen >= 0) if full else (m.seen != self.seen_sent)
        idx = np.flatnonzero(changed & (m.lo >= 4))
        if not full:
            self.seen_sent[:] = m.seen
        t = np.minimum(np.rint(m.seen[idx] * SEEN_UNITS_PER_S) + 1, 65535)
        return {"idx": b64(idx, "<i4"), "t": b64(t, "<u2")}


def state_message(sim: Simulation, stream: MapStream, since_event: int, extra: dict,
                  with_seen: bool, full: bool = False) -> dict:
    master = sim.master
    targets = master.targets[:MAX_TARGETS]
    msg = {
        "type": "snapshot" if full else "state",
        "drones": sim.drone_states(),
        "metrics": {**sim.metrics(), **extra},
        "map": stream.deltas(full),
        "entries": [e.to_dict() for e in master.entries],
        "candidates": [c.to_dict() for c in master.candidates],
        "found": sim.found_survivor_ids(),
        "mesh": sim.radio_mesh(),
        "targets": [[int(g["voxel"][0]), int(g["voxel"][1]), int(g["voxel"][2]),
                     0 if g["tile"][0] == "frontier" else 1] for g in targets],
        "events": master.events[since_event:],
        "history": sim.history[-1] if sim.history else None,
    }
    if with_seen or full:
        msg["seen"] = stream.seen(full)
    if full:
        step = max(1, len(sim.history) // 600)
        msg["history"] = sim.history[::step]
    return msg


def feed_message(sim: Simulation, drone: int) -> dict | None:
    """The latest camera frame the master received from `drone` (what the master sees)."""
    f = sim.last_frames[drone] if 0 <= drone < len(sim.last_frames) else None
    if f is None:
        return {"type": "feed", "drone": drone, "t": None}
    depth = np.where(f.depth > 0, np.clip(255 - f.depth / sim.cfg.cam_range * 255, 1, 255), 0)
    return {
        "type": "feed",
        "drone": drone,
        "t": round(float(f.t), 2),
        "age": round(float(sim.t - f.t), 2),
        "w": int(f.rgb.shape[1]),
        "h": int(f.rgb.shape[0]),
        "rgb": b64(f.rgb, "u1"),
        "depth": b64(depth, "u1"),
        "frames": [int(v) for v in sim.radio.frame_stats[drone]],
        "backlog": len(sim.backlog[drone]),
    }
