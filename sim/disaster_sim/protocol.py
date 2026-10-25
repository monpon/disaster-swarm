"""JSON messages streamed to the browser viewer.

Bulk arrays (voxel deltas, camera frames) travel as base64 little-endian binary inside the
JSON so a single text WebSocket carries everything.
"""
from __future__ import annotations

import base64

import numpy as np
import torch

from . import materials as M
from .floorplan import floorplan
from .config import PRESETS
from .gpu import DEV
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
        "presets": {k: {"label": v["label"], "desc": v["desc"], "n_survivors": v["n_survivors"], "floors": v["floors"]}
                    for k, v in PRESETS.items()},
    }


class MapStream:
    """Cursor into the master's map for the shared broadcast: what viewers already have. The
    bookkeeping (what was sent of every point) lives on the GPU next to the point store."""

    MAX_POINT_UPDATES = 4000  # per broadcast; the rest follows on later ones
    CANDIDATES = 40000
    MIN_MOVE = 0.04  # m

    def __init__(self, sim: Simulation):
        self.sim = sim
        self.tick = -1
        self.cap = 0
        self.sent_ver = torch.zeros(0, dtype=torch.int32, device=DEV)  # per point: version the viewers have (-1 = never)
        self.sent_raw = torch.zeros((0, 3), dtype=torch.float32, device=DEV)
        self.sent_sm = torch.zeros((0, 3), dtype=torch.float32, device=DEV)
        self.sent_hid = torch.zeros(0, dtype=torch.bool, device=DEV)
        self.sent_chunks: dict[int, tuple] = {}  # chunk id -> (version, order sent)
        self.sent_n = 0
        self.seen_sent = sim.master.map.g_seen.clone()

    def _grow(self, n: int) -> None:
        if n <= self.cap:
            return
        cap = max(n, 2 * self.cap, 1 << 16)
        pad = cap - self.cap
        self.sent_ver = torch.cat([self.sent_ver, torch.full((pad,), -1, dtype=torch.int32, device=DEV)])
        self.sent_raw = torch.cat([self.sent_raw, torch.zeros((pad, 3), device=DEV)])
        self.sent_sm = torch.cat([self.sent_sm, torch.zeros((pad, 3), device=DEV)])
        self.sent_hid = torch.cat([self.sent_hid, torch.zeros(pad, dtype=torch.bool, device=DEV)])
        self.cap = cap

    @torch.no_grad()
    def deltas(self, full: bool = False) -> dict:
        """Map voxels changed since the last broadcast (or everything occupied, for a new client)."""
        m = self.sim.master.map
        return self._deltas_locked(m, full)

    def _deltas_locked(self, m, full: bool) -> dict:
        idx, occ, mat, rgb, q = m.deltas_since(-1 if full else self.tick)
        if not full:
            self.tick = self.sim.master.tick
        o = np.flatnonzero(occ)
        free = idx[~occ] if not full else np.zeros(0, dtype=np.int64)  # a new client starts empty
        n = m.npts
        self._grow(n)
        if full:
            ids = torch.arange(n, device=DEV)
        else:
            cand = torch.nonzero(self.sent_ver[:n] != m.pver[:n]).squeeze(1)[:self.CANDIDATES]
            # Only changes a viewer could see: new points, moves over 4 cm, hidden/shown flips.
            hid = m.hidden(cand)
            moved = ((m.praw[cand] - self.sent_raw[cand]).abs().amax(1) > self.MIN_MOVE) \
                | ((m.spos[cand] - self.sent_sm[cand]).abs().amax(1) > self.MIN_MOVE) \
                | (hid != self.sent_hid[cand]) | (self.sent_ver[cand] < 0)
            quiet = cand[~moved]
            self.sent_ver[quiet] = m.pver[quiet]  # nothing to show: considered synced
            ids = cand[moved][:self.MAX_POINT_UPDATES]
        hidden = m.hidden(ids)
        self.sent_ver[ids] = m.pver[ids]
        self.sent_raw[ids], self.sent_sm[ids], self.sent_hid[ids] = m.praw[ids], m.spos[ids], hidden
        conf = torch.clamp(m.nview[ids] // 2, max=3)
        flag = (hidden.to(torch.int32) | (conf << 1)).to(torch.uint8).cpu().numpy()
        unit = 0.05
        vox, _ = m._flat(m.praw[ids])
        h = {
            "ids": ids.cpu().numpy(),
            "raw": torch.round(m.praw[ids] / unit).clamp(0, 65535).cpu().numpy(),
            "sm": torch.round(torch.clamp(m.spos[ids], 0, 3200) / unit).clamp(0, 65535).cpu().numpy(),
            "col": m.pcol[ids].cpu().numpy(),
            "resid": torch.clamp(torch.round(m.presid[ids] * 255), max=255).cpu().numpy(),
            "npass": m.g_npass[vox].clamp(max=255).cpu().numpy(),
        }
        return {"idx": b64(idx[o], "<i4"), "mat": b64(mat[o], "u1"), "rgb": b64(rgb[o], "<u2"),
                "q": b64(q[o], "u1"), "free": b64(free, "<i4"), "n": int(len(o)),
                "uidx": b64(h["ids"], "<u4"), "upos": b64(h["raw"], "<u2"), "uspos": b64(h["sm"], "<u2"),
                "ucol": b64(h["col"], "u1"), "uflag": b64(flag, "u1"), "uresid": b64(h["resid"], "u1"),
                "unpass": b64(h["npass"], "u1"),
                "nu": int(len(h["ids"])), "ptotal": int(n), "surf": self.surface(full)}

    def surface(self, full: bool) -> list:
        """Mesh chunks that changed (or all of them, for a new client). A chunk replaces the
        previous mesh with the same id; zero vertices clears it."""
        out = []
        if full:
            self.sent_chunks = {}
        for cid, c in self.sim.master.surface.updates(self.sent_chunks, full, limit=64 if not full else 10 ** 9, budget=450_000):
            self.sent_n += 1
            self.sent_chunks[cid] = (c["ver"], self.sent_n)
            nv = len(c["v"]) // 3
            wide = nv >= 65536
            out.append({"id": int(cid), "nv": nv, "v": b64(c["v"], "<u2"), "n": b64(c["n"], "i1"), "c": b64(c["c"], "u1"),
                        "f": b64(c["f"], "<u4" if wide else "<u2"), "w": bool(wide)})
        return out

    @torch.no_grad()
    def seen(self, full: bool = False) -> dict:
        """Proper-scan times of surfaces re-scanned since the last broadcast (or all, if full)."""
        m = self.sim.master.map
        return self._seen_locked(m, full)

    def _seen_locked(self, m, full: bool) -> dict:
        changed = (m.g_seen >= 0) if full else (m.g_seen != self.seen_sent)
        idx = torch.nonzero(changed & (m.g_lo >= 4)).squeeze(1)
        if not full:
            self.seen_sent.copy_(m.g_seen)
        t = torch.clamp(torch.round(m.g_seen[idx] * SEEN_UNITS_PER_S) + 1, max=65535)
        return {"idx": b64(idx.cpu().numpy(), "<i4"), "t": b64(t.cpu().numpy(), "<u2")}


class RustMapStream(MapStream):
    """The same stream as `MapStream`, with every compaction done on the Rust core."""

    def __init__(self, sim: Simulation):
        self.sim = sim
        self.tick = -1
        self.sent_chunks: dict[int, tuple] = {}
        self.sent_n = 0

    def deltas(self, full: bool = False) -> dict:
        m = self.sim.master.map
        v = m.core.vox_deltas(-1 if full else self.tick)
        if not full:
            self.tick = self.sim.master.tick
        idx, occ = np.asarray(v["idx"]), np.asarray(v["occ"]).astype(bool)
        mat, rgb, q = np.asarray(v["mat"]), np.asarray(v["rgb"]), np.asarray(v["q"])
        o = np.flatnonzero(occ)
        free = idx[~occ] if not full else np.zeros(0, dtype=np.int64)  # a new client starts empty
        p = m.core.point_updates(full, self.MAX_POINT_UPDATES, self.MIN_MOVE)
        return {"idx": b64(idx[o], "<i4"), "mat": b64(mat[o], "u1"), "rgb": b64(rgb[o], "<u2"), "q": b64(q[o], "u1"),
                "free": b64(free, "<i4"), "n": int(len(o)),
                "uidx": b64(p["ids"], "<u4"), "upos": b64(p["raw"], "<u2"), "uspos": b64(p["sm"], "<u2"),
                "ucol": b64(p["col"], "u1"), "uflag": b64(p["flag"], "u1"), "uresid": b64(p["resid"], "u1"),
                "unpass": b64(p["npass"], "u1"), "nu": int(len(p["ids"])), "ptotal": int(p["npts"]),
                "surf": self.surface(full)}

    def seen(self, full: bool = False) -> dict:
        s = self.sim.master.map.core.seen_updates(full)
        return {"idx": b64(np.asarray(s["idx"]), "<i4"), "t": b64(np.asarray(s["t"]), "<u2")}


def make_stream(sim: Simulation) -> MapStream:
    return RustMapStream(sim) if getattr(sim.master.map, "rust", False) else MapStream(sim)


def state_message(sim: Simulation, stream: MapStream, since_event: int, extra: dict,
                  with_seen: bool, full: bool = False, with_map: bool = True) -> dict:
    master = sim.master
    targets = master.targets[:MAX_TARGETS]
    msg = {
        "type": "snapshot" if full else "state",
        "drones": sim.drone_states(),
        "metrics": {**sim.metrics(), **extra},
        "map": stream.deltas(full) if with_map else {"n": 0, "nu": 0, "ptotal": int(sim.master.map.npts), "surf": []},
        "entries": [e.to_dict() for e in master.entries],
        "candidates": [c.to_dict() for c in master.candidates],
        "found": sim.found_survivor_ids(),
        "mesh": sim.radio_mesh(),
        "targets": [[int(g["voxel"][0]), int(g["voxel"][1]), int(g["voxel"][2]),
                     0 if g["tile"][0] == "frontier" else 1] for g in targets],
        "events": master.events[since_event:],
        "history": sim.history[-1] if sim.history else None,
    }
    if full or sim.t - getattr(stream, "_plan_t", -1e9) >= 1.0 or sim.t < getattr(stream, "_plan_t", 0.0):
        stream._plan_t = sim.t   # the floor plan: a small raster per floor, about once a second
        plan = floorplan(sim)
        if plan is not None:
            msg["plan"] = plan
    if (with_seen or full) and with_map:
        msg["seen"] = stream.seen(full)
    if full:
        step = max(1, len(sim.history) // 600)
        msg["history"] = sim.history[::step]
    return msg


def feed_arrays(sim: Simulation, drone: int) -> dict | None:
    """The latest frame the master received from `drone` and the depth it estimated for it, as arrays."""
    f = sim.last_frames[drone] if 0 <= drone < len(sim.last_frames) else None
    est = sim.master.last_depth[drone] if 0 <= drone < len(sim.master.last_depth) else None
    if f is None or est is None:
        return None
    h, w = sim.cfg.cam_h, sim.cfg.cam_w
    est = (est if isinstance(est, np.ndarray) else est.cpu().numpy()).reshape(h, w)
    rgb = sim.core.rgb(f.slot) if (f.slot >= 0 and sim.core is not None) else f.rgb.cpu().numpy()
    rgb = np.asarray(rgb)
    depth = np.where(est > 0, np.clip(255 - est / sim.cfg.depth_max * 255, 1, 255), 0)
    return {"t": round(float(f.t), 2), "age": round(float(sim.t - f.t), 2), "w": int(rgb.shape[1]), "h": int(rgb.shape[0]),
            "rgb": rgb, "depth": depth, "frames": [int(v) for v in sim.radio.frame_stats[drone]],
            "backlog": len(sim.backlog[drone]), "jpeg_kb": round(f.nbytes / 1000, 1)}


def feed_message(sim: Simulation, drone: int) -> dict | None:
    """The latest JPEG frame the master received from `drone`, and the depth its monocular
    depth network estimated for it (what the master actually works from)."""
    a = feed_arrays(sim, drone)
    if a is None:
        return {"type": "feed", "drone": drone, "t": None}
    return {"type": "feed", "drone": drone, **{**a, "rgb": b64(a["rgb"], "u1"), "depth": b64(a["depth"], "u1")}}
