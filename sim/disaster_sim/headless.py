"""Run the simulation without the GUI and print mission progress.

    python -m disaster_sim.headless --seconds 300 --seed 1
"""
from __future__ import annotations

import argparse
import time

from .config import SimConfig
from .sim import Simulation


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--drones", type=int, default=6)
    ap.add_argument("--report", type=float, default=20, help="report interval (sim s)")
    args = ap.parse_args()

    sim = Simulation(SimConfig(seed=args.seed, n_drones=args.drones))
    print(f"world: {len(sim.world.boxes)} structures, {len(sim.world.survivors)} survivors, "
          f"{args.drones} drones")
    wall0 = time.time()
    n_events = 0
    while sim.t < args.seconds:
        sim.advance(args.report)
        for e in sim.master.events[n_events:]:
            print(f"  [{e['t']:7.1f}] {e['text']}")
        n_events = len(sim.master.events)
        m = sim.metrics()
        modes = ",".join(d.mode[:4] for d in sim.master.drones)
        print(f"t={m['t']:6.1f}s cov={m['coverage']:.1%} found={m['found']}/{m['survivors']} "
              f"air={m['airborne']} crashed={m['crashed']} soc={m['avg_soc']:.2f} "
              f"loss={m['packet_loss']:.1%} modes={modes}")
        if m["mission_done"] and m["airborne"] == 0:
            break
    wall = time.time() - wall0
    print(f"done: {sim.t:.0f} sim s in {wall:.1f} wall s ({sim.t / wall:.1f}x realtime)")


if __name__ == "__main__":
    main()
