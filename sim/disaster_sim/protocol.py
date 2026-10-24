"""JSON messages streamed to the browser viewer."""
from __future__ import annotations

import base64

import numpy as np

from .sim import Simulation

SEEN_UNITS_PER_S = 2  # last-seen times are quantized to half seconds (uint16, 0 = never)


def encode_seen(sim: Simulation) -> str:
    """Master's last-seen time per cell as base64 little-endian uint16, numpy C-order [ix, iy]."""
    seen = sim.master.map.seen
    q = np.where(seen >= 0, np.minimum(np.rint(seen * SEEN_UNITS_PER_S) + 1, 65535), 0).astype("<u2")
    return base64.b64encode(q.tobytes()).decode("ascii")


def world_message(sim: Simulation) -> dict:
    return {
        "type": "world",
        "world": sim.world.to_dict(),
        "config": sim.cfg.to_dict(),
        "pads": sim.pads.round(2).tolist(),
    }


def map_cells(sim: Simulation, since_tick: int) -> dict:
    idx, s, h = sim.master.map.cells_since(since_tick)
    return {"idx": idx.tolist(), "s": s.tolist(), "h": [round(float(v), 1) for v in h]}


def state_message(sim: Simulation, since_tick: int, since_event: int, extra: dict,
                  include_seen: bool = False) -> dict:
    msg = {
        "type": "state",
        "drones": sim.drone_states(),
        "metrics": {**sim.metrics(), **extra},
        "map": map_cells(sim, since_tick),
        "candidates": [c.to_dict() for c in sim.master.candidates],
        "found": sim.found_survivor_ids(),
        "frontiers": [[round(float(c), 1) for c in sim.world.cell_center(f.ix, f.iy)] + [f.gain]
                      for f in sim.master.frontiers],
        "events": sim.master.events[since_event:],
        "history": sim.history[-1] if sim.history else None,
    }
    if include_seen:
        msg["seen"] = encode_seen(sim)
    return msg


def snapshot_message(sim: Simulation, extra: dict) -> dict:
    """Everything a newly connected client needs on top of the world message."""
    msg = state_message(sim, -1, 0, extra, include_seen=True)
    msg["type"] = "snapshot"
    step = max(1, len(sim.history) // 600)
    msg["history"] = sim.history[::step]
    return msg
