"""Rust A* vs the Python planner on the true building (run: python -m tests.test_rust_nav)."""
import time

import numpy as np

import gpucore
from disaster_sim import materials as M
from disaster_sim.config import SimConfig
from disaster_sim.planner3d import NavGrid
from disaster_sim.building import generate_building


def plen(cells):
    p = np.asarray(cells, float)
    return float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())


def main():
    b = generate_building(SimConfig())
    solid = b.vox != M.AIR
    pas = ~solid
    pas[:, :, 0] = False
    pas[:, :, -2:] = False
    py = NavGrid(pas.copy(), solid.copy())
    rs = gpucore.Nav(pas.astype(np.uint8), solid.astype(np.uint8))
    rng = np.random.default_rng(0)
    free = np.argwhere(pas)
    pairs = []
    for _ in range(60):
        i, j = rng.integers(len(free), size=2)
        a, c = free[i], free[j]
        if np.linalg.norm(a - c) > 15:
            pairs.append((a, c))
    ok = bad = 0
    tp = tr = 0.0
    ratios = []
    for a, c in pairs:
        t0 = time.perf_counter(); pp = py.astar(a.astype(float), c.astype(float), 60000); tp += time.perf_counter() - t0
        t0 = time.perf_counter(); pr = rs.astar(tuple(map(float, a)), tuple(map(float, c)), 60000, False); tr += time.perf_counter() - t0
        if (pp is None) != (pr is None):
            bad += 1
            continue
        if pp is not None:
            ok += 1
            ratios.append(plen(pr) / plen(pp))
            assert all(pas[tuple(q)] for q in pr), "rust path through a blocked cell"
    print("queries", len(pairs), "| both found", ok, "| disagree on reachability", bad)
    print("path length rust/python: mean %.3f  min %.3f  max %.3f" % (np.mean(ratios), np.min(ratios), np.max(ratios)))
    print("time per query: python %.1f ms | rust %.2f ms | speedup %.0fx" % (tp / len(pairs) * 1000, tr / len(pairs) * 1000, tp / max(tr, 1e-9)))
    d = gpucore.dilate(solid.astype(np.uint8), 2)
    from scipy import ndimage
    ref = ndimage.binary_dilation(solid, iterations=2)
    print("dilate(2) identical to scipy:", bool((d.astype(bool) == ref).all()))
    print("NAV", "OK" if bad <= 2 and 0.95 < np.mean(ratios) < 1.05 else "CHECK")


if __name__ == "__main__":
    main()
