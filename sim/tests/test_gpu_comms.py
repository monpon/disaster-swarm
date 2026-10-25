"""GPU radio vs the CPU model (run: python -m tests.test_gpu_comms)."""
import numpy as np
import torch

from disaster_sim.config import SimConfig
from disaster_sim.sim import Simulation
from disaster_sim import materials as M
from disaster_sim.radio import TX_DBM, NOISE_DBM, path_loss_db, obstruction_db
from disaster_sim.gcomms import snr_pairs


def main():
    sim = Simulation(SimConfig(known_outline=True))
    b = sim.b
    rng = np.random.default_rng(0)
    pos = np.array([[rng.uniform(2, 155), rng.uniform(2, 125), rng.uniform(0.5, 14)] for _ in range(40)])
    ii, jj = np.triu_indices(40, 1)
    sel = rng.choice(len(ii), 400, replace=False)
    ii, jj = ii[sel], jj[sel]
    sim.radio.update(pos[:16], np.ones(16, bool))     # builds the GPU world
    w = sim.radio._world
    from disaster_sim.gpu import DEV
    a = torch.as_tensor(pos[ii], dtype=torch.float32, device=DEV)
    c = torch.as_tensor(pos[jj], dtype=torch.float32, device=DEV)
    g = snr_pairs(w, a, c).cpu().numpy()
    ref = np.array([TX_DBM - path_loss_db(np.array(np.linalg.norm(pos[j] - pos[i]))) -
                    obstruction_db(b.material_at(pos[i][None, :] + (pos[j] - pos[i])[None, :] *
                                   ((np.arange(max(int(np.linalg.norm(pos[j] - pos[i]) / 0.5), 1)) + 0.5)[:, None] /
                                    max(int(np.linalg.norm(pos[j] - pos[i]) / 0.5), 1))), 0.5) - NOISE_DBM
                    for i, j in zip(ii, jj)])
    d = g - ref
    print("pairs", len(d), "| max |gpu - cpu| dB:", float(np.abs(d).max()).__round__(3), "| mean", float(d.mean()).__round__(4),
          "| within 0.01 dB:", float((np.abs(d) < 0.01).mean()))
    print("PARITY", "OK" if np.abs(d).max() < 0.05 else "MISMATCH")


if __name__ == "__main__":
    main()
