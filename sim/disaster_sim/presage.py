"""SIMULATED stand-in for Presage SmartSpectra (contactless heart rate and breathing rate from video).

The real SDK estimates vitals from subtle skin-colour changes in a camera feed. The simulator's people are flat-shaded figures
with no such signal, so this class does not look at pixels: it takes the person's hidden health state and returns a noisy
reading whose quality falls with distance and rises with how long the drone has held steady in front of them, the way the
real thing behaves. The call shape (`measure(...) -> {hr, rr, confidence}`) is what a real Presage client would return, so
the real SDK can replace this class without touching the master. Everything it produces is labelled "simulated".
"""
from __future__ import annotations

import numpy as np

NAME = "Presage SmartSpectra (simulated)"


class SimulatedPresage:
    name = NAME

    def __init__(self, rng: np.random.Generator):
        self.rng = rng

    def measure(self, health: dict, distance: float, dwell_s: float) -> dict:
        """One reading of a person's heart rate (beats/min) and breathing rate (breaths/min).
        `distance` is how far the camera is from them (m), `dwell_s` how long it has held on them (s)."""
        q = float(np.clip(1.0 - (distance - 1.5) / 4.0, 0.2, 1.0) * np.clip(dwell_s / 10.0, 0.4, 1.0))
        hr = health["hr"] + self.rng.normal(0.0, 2.0 + 10.0 * (1.0 - q))
        rr = health["rr"] + self.rng.normal(0.0, 0.8 + 4.0 * (1.0 - q))
        return {"hr": int(round(hr)), "rr": round(float(max(rr, 0.0)), 1), "confidence": round(q, 2), "source": "simulated"}


def random_health(rng: np.random.Generator) -> dict:
    """A survivor's hidden condition: about half stable, a third injured, the rest critical."""
    r = rng.random()
    if r < 0.5:
        return {"cond": "stable", "hr": float(rng.uniform(62, 92)), "rr": float(rng.uniform(12, 18))}
    if r < 0.8:
        hr = rng.uniform(98, 124) if rng.random() < 0.85 else rng.uniform(48, 56)
        return {"cond": "injured", "hr": float(hr), "rr": float(rng.uniform(20, 26))}
    if rng.random() < 0.7:
        return {"cond": "critical", "hr": float(rng.uniform(132, 165)), "rr": float(rng.uniform(30, 38))}
    return {"cond": "critical", "hr": float(rng.uniform(36, 46)), "rr": float(rng.uniform(5, 8))}


def triage(hr: float, rr: float, confidence: float) -> tuple[int, str]:
    """Urgency score 0-100 and a START-style tier from a vitals reading.
    IMMEDIATE (red): breathing or pulse far out of range. URGENT (amber): clearly abnormal. DELAYED (green): near normal."""
    s_hr = float(np.clip(max((hr - 100.0) / 50.0, (60.0 - hr) / 25.0, 0.0), 0.0, 1.0))   # a slow pulse is worse than a fast one
    s_rr = float(np.clip(max((rr - 20.0) / 14.0, (12.0 - rr) / 8.0, 0.0), 0.0, 1.0))
    score = int(round(100.0 * (0.55 * max(s_hr, s_rr) + 0.45 * (s_hr + s_rr) / 2.0)))
    tier = "IMMEDIATE" if score >= 55 else "URGENT" if score >= 18 else "DELAYED"
    return score, tier
