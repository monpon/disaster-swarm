"""GPU voxel map vs the CPU reference on identical frames (run: python -m tests.test_gpu_map)."""
import time

import numpy as np
import torch

from disaster_sim.config import SimConfig
from disaster_sim.sim import Simulation
from disaster_sim.camera import Frame
from disaster_sim.estimation import rot_z
from disaster_sim.gpu import DEV
import disaster_sim.voxelmap as G
import tests.ref_voxelmap as R


def make_frames(sim, n=24, seed=0):
    rng = np.random.default_rng(seed)
    items = []
    for i in range(n):
        p = np.array([rng.uniform(55, 135), rng.uniform(38, 90), rng.uniform(2, 12)])
        items.append((i % 16, p, rot_z(rng.uniform(0, 6.28)), np.zeros(3)))
    pk = sim.camera.capture_many(items, 0.0)
    return items, pk


def main():
    sim = Simulation(SimConfig(known_outline=True))
    cfg = sim.cfg
    items, pk = make_frames(sim)
    shape = sim.b.vox.shape
    ref, new, new_b = R.VoxelMap(shape, cfg), G.VoxelMap(shape, cfg), G.VoxelMap(shape, cfg)
    for m in (ref, new, new_b):
        sparse = np.ones(shape[:2], dtype=bool)
        m.sparse2d = sparse
    # same inputs for both: depth + rgb as the master would see them
    depth = torch.stack([p.sim_truth["depth"] for p in pk]).reshape(len(pk), -1)
    rgb = torch.stack([p.rgb.reshape(-1, 3) for p in pk])
    pos = torch.as_tensor(np.stack([it[1] for it in items]), device=DEV, dtype=torch.float32)
    rot = torch.as_tensor(np.stack([it[2] for it in items]), device=DEV, dtype=torch.float32)
    tt = torch.arange(len(pk), device=DEV, dtype=torch.float32)
    dr = torch.as_tensor([it[0] for it in items], device=DEV)
    for i, it in enumerate(items):
        d = depth[i].cpu().numpy().reshape(cfg.cam_h, cfg.cam_w)
        ref.integrate(Frame(it[0], float(i), it[1], it[2], d, rgb[i].cpu().numpy().reshape(cfg.cam_h, cfg.cam_w, 3)), i)
        new.integrate_batch(pos[i:i + 1], rot[i:i + 1], depth[i:i + 1], rgb[i:i + 1], tt[i:i + 1], dr[i:i + 1], i)
    t0 = time.perf_counter()
    new_b.integrate_batch(pos, rot, depth, rgb, tt, dr, 0)
    if DEV.type == "cuda":
        torch.cuda.synchronize()
    print("batch of", len(pk), "frames:", round((time.perf_counter() - t0) * 1000, 1), "ms")

    new.sync_host(True); new_b.sync_host(True)
    # --- sequential (B=1) must agree with the CPU reference
    occ_r, free_r = ref.occupied, ref.free
    occ_n, free_n = new.occupied, new.free
    print("sequential: occupied", int(occ_r.sum()), int(occ_n.sum()), "diff", int((occ_r != occ_n).sum()),
          "| free", int(free_r.sum()), int(free_n.sum()), "diff", int((free_r != free_n).sum()))
    print("            lo exact-equal fraction", float((ref.lo == new.lo).mean()))
    print("            quality max diff", float(np.abs(ref.quality - new.quality).max()),
          "| npass diff voxels", int((ref.npass != new.npass).sum()))
    print("            points", ref.npts, new.npts)
    # --- batched: same maps up to ordering effects
    jac = lambda a, b: float((a & b).sum() / max((a | b).sum(), 1))
    print("batched   : occupied jaccard", round(jac(occ_r, new_b.occupied), 4), "free jaccard", round(jac(free_r, new_b.free), 4),
          "points", new_b.npts)
    ok = (occ_r != occ_n).sum() == 0 and (free_r != free_n).sum() == 0
    print("PARITY", "OK" if ok else "MISMATCH")


if __name__ == "__main__":
    main()
