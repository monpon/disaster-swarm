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

    MAX_POINT_UPDATES = 4000  # per broadcast; the rest follows on later ones
    CANDIDATES = 40000
    MIN_MOVE = 0.04  # m

    def __init__(self, sim: Simulation):
        self.sim = sim
        self.tick = -1
        self.sent_ver = np.zeros(0, dtype=np.int64)  # per point: version the viewers have (-1 = never sent)
        self.sent_raw = np.zeros((0, 3), np.float32)
        self.sent_sm = np.zeros((0, 3), np.float32)
        self.sent_hid = np.zeros(0, bool)
        self.sent_chunks: dict[int, int] = {}
        self.seen_sent = sim.master.map.seen.copy()

    def deltas(self, full: bool = False) -> dict:
        """Map voxels changed since the last broadcast (or everything occupied, for a new client)."""
        m = self.sim.master.map
        idx, occ, mat, rgb, q = m.deltas_since(-1 if full else self.tick)
        if not full:
            self.tick = self.sim.master.tick
        o = np.flatnonzero(occ)
        free = idx[~occ] if not full else np.zeros(0, dtype=np.int64)  # a new client starts empty
        n = m.npts
        if len(self.sent_ver) < n:
            grow = max(n, 2 * len(self.sent_ver)) - len(self.sent_ver)
            self.sent_ver = np.r_[self.sent_ver, np.full(grow, -1)]
            self.sent_raw = np.r_[self.sent_raw, np.zeros((grow, 3), np.float32)]
            self.sent_sm = np.r_[self.sent_sm, np.zeros((grow, 3), np.float32)]
            self.sent_hid = np.r_[self.sent_hid, np.zeros(grow, bool)]
        if full:
            ids = np.arange(n)
        else:
            cand = np.flatnonzero(self.sent_ver[:n] != m.pver[:n].astype(np.int64))[:self.CANDIDATES]
            # Only changes a viewer could see: new points, moves over 4 cm, hidden/shown flips.
            moved = (np.abs(m.praw[cand] - self.sent_raw[cand]).max(1) > self.MIN_MOVE) \
                | (np.abs(m.spos[cand] - self.sent_sm[cand]).max(1) > self.MIN_MOVE) \
                | (m.hidden(cand) != self.sent_hid[cand]) | (self.sent_ver[cand] < 0)
            self.sent_ver[cand[~moved]] = m.pver[cand[~moved]]  # nothing to show: considered synced
            ids = cand[moved][:self.MAX_POINT_UPDATES]
        self.sent_ver[ids] = m.pver[ids]
        self.sent_raw[ids], self.sent_sm[ids], self.sent_hid[ids] = m.praw[ids], m.spos[ids], m.hidden(ids)
        conf = np.minimum(m.nview[ids] // 2, 3).astype(np.uint8)  # confidence bucket 0..3 from views
        flag = m.hidden(ids).astype(np.uint8) | (conf << 1)
        unit = 0.05
        return {"idx": b64(idx[o], "<i4"), "mat": b64(mat[o], "u1"), "rgb": b64(rgb[o], "<u2"),
                "q": b64(q[o], "u1"), "free": b64(free, "<i4"), "n": int(len(o)),
                "uidx": b64(ids, "<u4"), "upos": b64(np.rint(m.praw[ids] / unit), "<u2"),
                "uspos": b64(np.rint(np.clip(m.spos[ids], 0, 3200) / unit), "<u2"),
                "ucol": b64(m.pcol[ids], "u1"), "uflag": b64(flag, "u1"),
                "uresid": b64(np.minimum(np.rint(m.presid[ids] * 255), 255), "u1"),
                "unpass": b64(m.npass[m.flat_of(m.praw[ids])[0]], "u1"),
                "nu": int(len(ids)), "ptotal": int(n), "surf": self.surface(full)}

    def surface(self, full: bool) -> list:
        """Mesh chunks that changed (or all of them, for a new client). A chunk replaces the
        previous mesh with the same id; zero vertices clears it."""
        out = []
        if full:
            self.sent_chunks = {}
        for cid, c in self.sim.master.surface.updates(self.sent_chunks, full, limit=3 if not full else 10 ** 9):
            self.sent_chunks[cid] = c["ver"]
            nv = len(c["v"]) // 3
            wide = nv >= 65536
            out.append({"id": int(cid), "nv": nv, "v": b64(c["v"], "<u2"), "n": b64(c["n"], "i1"), "c": b64(c["c"], "u1"),
                        "f": b64(c["f"], "<u4" if wide else "<u2"), "w": bool(wide)})
        return out

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
    """The latest JPEG frame the master received from `drone`, and the depth its monocular
    depth network estimated for it (what the master actually works from)."""
    f = sim.last_frames[drone] if 0 <= drone < len(sim.last_frames) else None
    est = sim.master.last_depth[drone] if 0 <= drone < len(sim.master.last_depth) else None
    if f is None or est is None:
        return {"type": "feed", "drone": drone, "t": None}
    depth = np.where(est > 0, np.clip(255 - est / sim.cfg.depth_max * 255, 1, 255), 0)
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
        "jpeg_kb": round(f.nbytes / 1000, 1),
    }
