"""Run the simulation without the GUI and print mission progress.

    python -m disaster_sim.headless --seconds 600 --seed 1
"""
from __future__ import annotations

import argparse
import time

from .config import SimConfig
from .sim import Simulation


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--drones", type=int, default=8)
    ap.add_argument("--report", type=float, default=30, help="report interval (sim s)")
    args = ap.parse_args()

    sim = Simulation(SimConfig(seed=args.seed, n_drones=args.drones))
    b = sim.b
    print(f"building: {len(b.rooms)} rooms on {sim.cfg.floors} floors, {len(b.entries)} true openings, "
          f"{len(b.survivors)} survivors, {args.drones} drones")
    wall0 = time.time()
    n_events = 0
    while sim.t < args.seconds:
        sim.advance(args.report)
        for e in sim.master.events[n_events:]:
            print(f"  [{e['t']:7.1f}] {e['text']}")
        n_events = len(sim.master.events)
        m = sim.metrics()
        modes = ",".join(d.mode[:4] for d in sim.master.drones)
        print(f"t={m['t']:6.1f}s {m['phase']:<8} explored={m['explored']:.1%} scanned={m['scanned']:.1%} "
              f"found={m['found']}/{m['survivors']} entries={m['entries_usable']}/{m['entries']} "
              f"relays={m['relays']} crashed={m['crashed']} frames={m['frames_ok']}/-{m['frames_dropped']} "
              f"soc={m['avg_soc']:.2f} [{time.time() - wall0:.0f}s] modes={modes}")
        if m["phase"] == "complete" and m["airborne"] == 0:
            break
    wall = time.time() - wall0
    print(f"done: {sim.t:.0f} sim s in {wall:.1f} wall s ({sim.t / wall:.2f}x realtime)")


if __name__ == "__main__":
    main()
