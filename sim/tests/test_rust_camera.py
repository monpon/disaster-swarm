"""Rust/CUDA camera vs the torch camera on identical poses (run: python -m tests.test_rust_camera)."""
import time

import numpy as np
import torch

import gpucore
from disaster_sim import materials as M
from disaster_sim.camera import RGBDCamera
from disaster_sim.config import SimConfig
from disaster_sim.estimation import rot_z
from disaster_sim.sim import Simulation


def world_padded(cam):
    b = cam.b
    pad = cam.pad
    sx, sy, sz = b.vox.shape
    padded = np.zeros((sx + 2 * pad, sy + 2 * pad, sz + 2 * pad), dtype=np.uint8)
    padded[:, :, :pad] = M.ASPHALT
    padded[pad:pad + sx, pad:pad + sy, pad:pad + sz] = b.vox
    return np.ascontiguousarray(padded)


def main():
    sim = Simulation(SimConfig(known_outline=True))
    cam, cfg = sim.camera, sim.cfg
    core = gpucore.Core(world_padded(cam), cam.pad, cam.k.body_rays.astype(np.float32), cfg.cam_w, cfg.cam_h,
                        cfg.cam_hfov_deg, cam.k.steps.astype(np.float32), 0.5, M.COLORS.astype(np.float32))
    rng = np.random.default_rng(0)
    M_ = 16
    poss = np.stack([[rng.uniform(55, 135), rng.uniform(38, 90), rng.uniform(2, 12)] for _ in range(M_)]).astype(np.float32)
    rots = np.stack([rot_z(rng.uniform(0, 6.28)) for _ in range(M_)]).astype(np.float32)
    om = np.zeros((M_, 3), np.float32)
    inside = sim.b.inside_building(poss).astype(np.uint8)
    # torch reference (no noise compare: depth only)
    dt, _ = cam._render(poss.astype(np.float64), rots.astype(np.float64))
    dt = dt.cpu().numpy()
    slots = core.render(poss, rots, om, inside, 1)
    bad = 0
    for j, s in enumerate(slots):
        d = core.truth_depth(s).reshape(-1)
        bad += int((np.abs(d - dt[j]) > 1e-4).sum())
    print("depth mismatches:", bad, "of", M_ * dt.shape[1])
    for s in slots: core.free_slot(s)

    def timeit(f, n=20):
        f(); torch.cuda.synchronize(); t = time.perf_counter()
        for _ in range(n): f()
        torch.cuda.synchronize(); return (time.perf_counter() - t) / n * 1000

    def rust():
        sl = core.render(poss, rots, om, inside, 2); core.sync()
        for s in sl: core.free_slot(s)
    print("torch render+degrade (16 frames): %.2f ms" % timeit(lambda: cam.capture_many(
        [(i, poss[i].astype(np.float64), rots[i].astype(np.float64), om[i].astype(np.float64)) for i in range(M_)], 0.0)))
    print("rust  render+degrade (16 frames): %.2f ms" % timeit(rust))
    # degraded rgb statistics against torch
    pk = cam.capture_many([(i, poss[i].astype(np.float64), rots[i].astype(np.float64), om[i].astype(np.float64)) for i in range(M_)], 0.0)
    a = torch.stack([p.rgb for p in pk]).float().cpu().numpy()
    sl = core.render(poss, rots, om, inside, 3)
    b = np.stack([core.rgb(s) for s in sl]).astype(np.float32)
    print("rgb mean torch/rust: %.2f / %.2f | std %.2f / %.2f | mean|diff| %.2f" % (a.mean(), b.mean(), a.std(), b.std(), np.abs(a - b).mean()))
    # depth-net statistics
    est = core.depthnet(sl, [0] * len(sl), 0.05, 0.06, 12.0, 4)
    tr = core.truth_depth(sl[0])
    v = (tr > 0) & (est > 0)
    print("depthnet: valid frac %.3f | rel error mean %.3f std %.3f (torch model: scale 5%%, region 6%%, noise 2%%)" %
          (float(v.mean()), float(np.mean(est[v] / tr[v] - 1)), float(np.std(est[v] / tr[v] - 1))))


if __name__ == "__main__":
    main()
