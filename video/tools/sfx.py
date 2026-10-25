"""Generates the small UI sound set into public/sfx: soft tones, tick, click, hit, whoosh."""
import os
import wave

import numpy as np

SR = 48000
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "sfx")
os.makedirs(OUT, exist_ok=True)


def save(name, x):
    x = np.clip(x / max(1e-9, np.abs(x).max()) * 0.9, -1, 1)
    st = np.stack([x, x], 1)
    with wave.open(os.path.join(OUT, name), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((st * 32767).astype("<i2").tobytes())


def t(d):
    return np.arange(int(SR * d)) / SR


def env(n, a, d):
    """Attack in samples then exponential decay with time constant d seconds."""
    e = np.exp(-np.arange(n) / (SR * d))
    e[:a] *= np.linspace(0, 1, a)
    return e


# Soft bell tone for logos sliding in: sine + quiet fifth partial.
x = t(0.9)
tone = (np.sin(2 * np.pi * 880 * x) + 0.25 * np.sin(2 * np.pi * 1320 * x) + 0.12 * np.sin(2 * np.pi * 1760 * x)) * env(len(x), 200, 0.22)
save("tone.wav", tone)

# Brighter two-note tone for the logo reveal.
x = t(1.6)
a = np.sin(2 * np.pi * 659.25 * x) * env(len(x), 200, 0.5)
b = np.zeros_like(x)
off = int(0.12 * SR)
xb = x[: len(x) - off]
b[off:] = (np.sin(2 * np.pi * 987.77 * xb) + 0.3 * np.sin(2 * np.pi * 1975.5 * xb)) * env(len(xb), 200, 0.6)
save("tone_hi.wav", a * 0.7 + b)

# Clock tick: short filtered click.
x = t(0.06)
rng = np.random.default_rng(1)
tick = (rng.standard_normal(len(x)) * 0.4 + np.sin(2 * np.pi * 2400 * x)) * env(len(x), 20, 0.006)
save("tick.wav", tick)

# Mouse click: two tiny transients.
x = t(0.08)
c = np.sin(2 * np.pi * 3200 * x) * env(len(x), 10, 0.004)
c2 = np.zeros_like(x)
o = int(0.035 * SR)
c2[o:] = np.sin(2 * np.pi * 2600 * x[: len(x) - o]) * env(len(x) - o, 10, 0.004) * 0.6
save("click.wav", c + c2)

# Low soft hit for keyword stamps: sine drop with a little noise body.
x = t(0.7)
f = 110 * np.exp(-x * 5) + 50
ph = 2 * np.pi * np.cumsum(f) / SR
hit = np.sin(ph) * env(len(x), 60, 0.16) + rng.standard_normal(len(x)) * env(len(x), 30, 0.02) * 0.25
save("hit.wav", hit)

# Gentle whoosh: band-limited noise swell.
x = t(0.9)
n = rng.standard_normal(len(x))
k = np.ones(40) / 40
n = np.convolve(n, k, mode="same") - np.convolve(n, np.ones(400) / 400, mode="same")
sw = np.sin(np.pi * np.clip(x / 0.9, 0, 1)) ** 2
save("whoosh.wav", n * sw)
print("sfx written to", os.path.abspath(OUT))
