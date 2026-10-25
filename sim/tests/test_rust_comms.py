"""Rust SNR kernel vs the torch one on random links through the true building."""
import numpy as np
import torch

from disaster_sim.config import SimConfig
from disaster_sim.gcomms import snr_pairs
from disaster_sim.gpu import DEV
from disaster_sim.sim import Simulation
import time


def main():
    sim = Simulation(SimConfig(known_outline=True))
    assert sim.core is not None
    rng = np.random.default_rng(0)
    P = 3000
    a = np.stack([[rng.uniform(2, 155), rng.uniform(2, 125), rng.uniform(0.5, 14)] for _ in range(P)]).astype(np.float32)
    b = np.stack([[rng.uniform(2, 155), rng.uniform(2, 125), rng.uniform(0.5, 14)] for _ in range(P)]).astype(np.float32)
    sim.radio.core = None
    sim.radio.update(sim.fleet.pos, np.ones(16, bool))  # builds the torch world
    w = sim.radio._world
    ref = snr_pairs(w, torch.as_tensor(a, device=DEV), torch.as_tensor(b, device=DEV)).cpu().numpy()
    got = np.asarray(sim.core.link_snr(a, b, 0))
    d = got - ref
    print("links", P, "| max |rust - torch| %.3f dB | within 0.01 dB: %.4f | within 1 dB: %.4f" % (np.abs(d).max(), (np.abs(d) < 0.01).mean(), (np.abs(d) < 1).mean()))
    for _ in range(3): sim.core.link_snr(a, b, 0)
    t = time.perf_counter()
    for _ in range(20): sim.core.link_snr(a, b, 0)
    print("rust %.2f ms for %d links" % ((time.perf_counter() - t) / 20 * 1000, P))
    torch.cuda.synchronize(); t = time.perf_counter()
    for _ in range(20): snr_pairs(w, torch.as_tensor(a, device=DEV), torch.as_tensor(b, device=DEV)).cpu()
    print("torch %.2f ms for %d links" % ((time.perf_counter() - t) / 20 * 1000, P))
    print("COMMS", "OK" if (np.abs(d) < 1).mean() > 0.995 else "CHECK")


if __name__ == "__main__":
    main()
