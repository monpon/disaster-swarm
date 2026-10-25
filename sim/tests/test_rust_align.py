"""Rust smoothing + alignment: build a map from true poses, smooth it, then fuse frames whose pose is
offset and check the alignment recovers it (run: python -m tests.test_rust_align)."""
import time

import numpy as np

from disaster_sim.config import SimConfig
from disaster_sim.estimation import rot_z
from disaster_sim.sim import Simulation
from tests.test_rust_map import make_core


def main():
    sim = Simulation(SimConfig(known_outline=True))
    core = make_core(sim)
    rng = np.random.default_rng(1)
    B = 16
    poss = np.stack([[rng.uniform(58, 130), rng.uniform(40, 88), rng.uniform(3, 11)] for _ in range(B)]).astype(np.float32)
    rots = np.stack([rot_z(rng.uniform(0, 6.28)) for _ in range(B)]).astype(np.float32)
    tick = 0
    for rep in range(4):   # each pose seen several times from the true pose
        slots = core.render(poss, rots, np.zeros((B, 3), np.float32), np.ones(B, np.uint8), 10 + rep)
        tick += 1
        core.fuse(slots, poss, rots, np.full(B, float(rep), np.float32), np.arange(B, dtype=np.int32), [0] * B, rep, 0.0, 0.0, 12.0, tick)
        for s in slots: core.free_slot(s)
    t0 = time.perf_counter(); total = 0
    while True:
        k = core.smooth_step(15000)
        total += k
        if k == 0: break
    print("smoothed", total, "points in", round((time.perf_counter() - t0) * 1000, 1), "ms | points", core.npoints())
    # frames from the same places but with a wrong pose estimate, by 'other' drones, much later
    off = np.array([0.35, -0.25, 0.1], np.float32)
    dyaw = 0.05
    slots = core.render(poss, rots, np.zeros((B, 3), np.float32), np.ones(B, np.uint8), 99)
    bad_pos = poss + off
    bad_rot = np.stack([rot_z(dyaw) @ rots[i] for i in range(B)]).astype(np.float32)
    res = core.fuse(slots, bad_pos, bad_rot, np.full(B, 100.0, np.float32), (np.arange(B) + 20).astype(np.int32), [0] * B, 99, 0.0, 0.0, 12.0, tick + 1)
    a = res["ares"]
    acc = a[:, 0] > 0.5
    print("accepted", int(acc.sum()), "/", B)
    if acc.any():
        dp = a[acc, 1:4]
        err_before = np.linalg.norm(off)
        err_after = np.linalg.norm(dp + off, axis=1)   # truth = bad + dp  -> true offset removed when dp = -off
        print("position error before %.3f m | after: mean %.3f  median %.3f  best %.3f" % (err_before, err_after.mean(), np.median(err_after), err_after.min()))
        print("depth scale mean %.3f (true frames have scale 1)" % a[acc, 13].mean())
        print("cross-drone fraction %.2f | inliers mean %d | obs_dp norm mean %.3f" % (a[acc, 18].mean(), a[acc, 19].mean(), np.linalg.norm(a[acc, 14:17], axis=1).mean()))
    print("ALIGN", "OK" if acc.sum() >= B // 2 and np.median(err_after) < 0.6 * np.linalg.norm(off) else "WEAK")


if __name__ == "__main__":
    main()
