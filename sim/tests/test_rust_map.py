"""Rust/CUDA map fusion vs the torch map, fed identical frames (run: python -m tests.test_rust_map)."""
import time

import numpy as np
import torch

import gpucore
from disaster_sim import materials as M
from disaster_sim.config import SimConfig
from disaster_sim.estimation import rot_z
from disaster_sim.gpu import DEV
from disaster_sim.sim import Simulation
import disaster_sim.voxelmap as G
from tests.test_rust_camera import world_padded


def make_core(sim):
    cam, cfg = sim.camera, sim.cfg
    shape = sim.b.vox.shape
    q = G.ScanQuality(cfg.scan_near, cfg.cam_range, cfg.proper_scan_range)
    core = gpucore.Core(world_padded(cam), cam.pad, cam.k.body_rays.astype(np.float32), cfg.cam_w, cfg.cam_h,
                        cfg.cam_hfov_deg, cam.k.steps.astype(np.float32), 0.5, M.COLORS.astype(np.float32),
                        tuple(int(x) for x in shape), M.COLORS[1:].astype(np.float32),
                        float(min(cfg.depth_max, cfg.cam_range)), float(cfg.scan_near), float(cfg.cam_range), float(q.threshold))
    cone = np.flatnonzero((np.abs(np.arctan2(cam.k.body_rays[:, 1], cam.k.body_rays[:, 0])) < 0.26) &
                          (np.abs(np.arctan2(cam.k.body_rays[:, 2], np.hypot(cam.k.body_rays[:, 0], cam.k.body_rays[:, 1]))) < 0.2))
    core.set_cone(cone.astype(np.int32))
    core.set_sparse2d(np.ones(shape[:2], dtype=np.uint8))
    return core


def main():
    sim = Simulation(SimConfig(known_outline=True))
    cfg, shape = sim.cfg, sim.b.vox.shape
    core = make_core(sim)
    ref = G.VoxelMap(shape, cfg)
    ref.sparse2d = np.ones(shape[:2], dtype=bool)
    rng = np.random.default_rng(0)
    tick = 0
    t_fuse = []
    for batch in range(8):
        B = 12
        poss = np.stack([[rng.uniform(55, 135), rng.uniform(38, 90), rng.uniform(2, 12)] for _ in range(B)]).astype(np.float32)
        rots = np.stack([rot_z(rng.uniform(0, 6.28)) for _ in range(B)]).astype(np.float32)
        slots = core.render(poss, rots, np.zeros((B, 3), np.float32), np.ones(B, np.uint8), 100 + batch)
        tcap = np.full(B, float(batch), np.float32)
        drone = (np.arange(B) % 16).astype(np.int32)
        tick += 1
        t0 = time.perf_counter()
        res = core.fuse(slots, poss, rots, tcap, drone, [0] * B, 7 + batch, 0.05, 0.06, 12.0, tick)
        t_fuse.append((time.perf_counter() - t0) * 1000)
        est = torch.as_tensor(np.stack([core.estimate(j).reshape(-1) for j in range(B)]), device=DEV)
        rgb = torch.as_tensor(np.stack([core.rgb(s).reshape(-1, 3) for s in slots]), device=DEV)
        pos_c = torch.as_tensor(res["pos"], device=DEV)
        rot_c = torch.as_tensor(res["rot"], device=DEV)
        ref.integrate_batch(pos_c, rot_c, est, rgb, torch.as_tensor(tcap, device=DEV), torch.as_tensor(drone, device=DEV), tick)
        for s in slots: core.free_slot(s)
        acc = int((res["ares"][:, 0] > 0.5).sum())
        print(f"batch {batch}: fuse {t_fuse[-1]:.1f} ms | aligned {acc}/{B} | npts rust {res['npts']} torch {ref.npts} | clear min {res['clear'].min():.1f}")
    ref.sync_host(True)
    h = core.host_arrays()
    lo_r = h["lo"]
    occ_a, occ_b = lo_r >= 4, ref.lo >= 4
    free_a, free_b = lo_r <= -3, ref.lo <= -3
    jac = lambda a, b: float((a & b).sum() / max((a | b).sum(), 1))
    print("occupied: rust", int(occ_a.sum()), "torch", int(occ_b.sum()), "jaccard", round(jac(occ_a, occ_b), 4))
    print("free:     rust", int(free_a.sum()), "torch", int(free_b.sum()), "jaccard", round(jac(free_a, free_b), 4))
    print("lo exact-equal fraction:", float((lo_r == ref.lo.astype(np.int32)).mean()))
    print("quality max|diff|:", float(np.abs(h["quality"] - ref.quality).max()), "| npass diff voxels:", int((h["npass"] != ref.npass).sum()))
    print("mat agreement on occupied:", float((h["mat"][occ_a & occ_b] == ref.mat[occ_a & occ_b]).mean()))
    print("median fuse ms (12 frames):", round(float(np.median(t_fuse[2:])), 2))
    ok = jac(occ_a, occ_b) > 0.97 and jac(free_a, free_b) > 0.97
    print("PARITY", "OK" if ok else "MISMATCH")


if __name__ == "__main__":
    main()
