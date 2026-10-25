"""Custom soundtrack for the Swarm video, synthesized and synced to the edit.

Section boundaries mirror src/timeline.ts. Output: public/audio/music.wav (48 kHz stereo).
Run with the tools venv: tools/.venv/bin/python tools/music.py
"""
import os

import numpy as np
import soundfile as sf
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
A_END = 102.3
B_LEN = 75.6
C_SLOT = 49.0
D_LEN = 5.5
B0 = A_END
C0 = B0 + B_LEN
D0 = C0 + C_SLOT
TOTAL = D0 + D_LEN
BEAT = 0.5  # 120 bpm
N = int(TOTAL * SR) + SR

rng = np.random.default_rng(7)
L = np.zeros(N)
R = np.zeros(N)
verb_send = np.zeros(N)


def hz(note):
    names = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    n, o = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((names[n] + 12 * (o + 1) - 69) / 12)


def lp(x, f, order=2):
    return sosfilt(butter(order, min(f, SR / 2 - 100) / (SR / 2), "low", output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f / (SR / 2), "high", output="sos"), x)


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo / (SR / 2), hi / (SR / 2)], "band", output="sos"), x)


def place(x, t0, gain=1.0, pan=0.0, verb=0.0):
    i = int(t0 * SR)
    if i >= N:
        return
    x = x[: N - i]
    gl = gain * np.cos((pan + 1) * np.pi / 4)
    gr = gain * np.sin((pan + 1) * np.pi / 4)
    L[i : i + len(x)] += x * gl
    R[i : i + len(x)] += x * gr
    if verb:
        verb_send[i : i + len(x)] += x * gain * verb


def adsr(n, a, r, sustain_end=None):
    e = np.ones(n)
    na, nr = int(a * SR), int(r * SR)
    e[: min(na, n)] = np.linspace(0, 1, min(na, n))
    if nr and n > nr:
        e[-nr:] *= np.linspace(1, 0, nr) ** 1.5
    return e


def saw(f, n, phase=0.0):
    t = np.arange(n) / SR
    return 2 * ((f * t + phase) % 1.0) - 1


# ---------------- instruments ----------------
def pad(notes, t0, t1, gain=0.12, cutoff=1200, attack=1.5, release=1.5, verb=0.6, swell=None):
    n = int((t1 - t0 + release) * SR)
    x = np.zeros(n)
    for note in notes:
        f = hz(note)
        for d in (-0.07, 0.0, 0.08):
            x += saw(f * 2 ** (d / 12), n, rng.random())
    x = lp(x, cutoff, 2) / (len(notes) * 3)
    env = adsr(n, attack, release)
    if swell is not None:
        env *= np.linspace(swell[0], swell[1], n)
    place(x * env, t0, gain, 0.0, verb)


def pluck(note, t0, gain=0.16, dur=1.4, pan=0.0, bright=1.0, verb=0.35):
    f = hz(note)
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for k in range(1, 8):
        x += np.sin(2 * np.pi * f * k * t) / k ** 1.3 * np.exp(-t * (2.5 + k * 1.6 / bright))
    x *= np.minimum(1, t / 0.003)
    place(x, t0, gain, pan, verb)


def bass(note, t0, dur, gain=0.22):
    f = hz(note)
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * f * t) + 0.35 * lp(saw(f, n), 500)
    x *= np.minimum(1, t / 0.005) * np.exp(-t * 2.2) * adsr(n, 0.001, 0.04)
    place(x, t0, gain, 0.0, 0.0)


def kick(t0, gain=0.5):
    n = int(0.42 * SR)
    t = np.arange(n) / SR
    f = 46 + 110 * np.exp(-t * 28)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)
    x[: int(0.002 * SR)] += rng.standard_normal(int(0.002 * SR)) * 0.3
    place(x, t0, gain)


def clap(t0, gain=0.16):
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    noise = bp(rng.standard_normal(n), 900, 3200)
    env = np.zeros(n)
    for k, o in enumerate((0, 0.011, 0.022)):
        i = int(o * SR)
        env[i:] += np.exp(-(t[: n - i]) * (60 if k < 2 else 16))
    place(noise * env, t0, gain, 0.0, 0.25)


def hat(t0, gain=0.05, open_=False, pan=0.25):
    n = int((0.25 if open_ else 0.06) * SR)
    t = np.arange(n) / SR
    x = hp(rng.standard_normal(n), 7000) * np.exp(-t * (14 if open_ else 70))
    place(x, t0, gain, pan)


def crash(t0, gain=0.12):
    n = int(2.6 * SR)
    t = np.arange(n) / SR
    x = hp(rng.standard_normal(n), 3500) * np.exp(-t * 1.6)
    place(x, t0, gain, 0.0, 0.4)


def riser(t0, t1, gain=0.08):
    n = int((t1 - t0) * SR)
    t = np.arange(n) / SR
    p = t / (t1 - t0)
    x = rng.standard_normal(n)
    # Crude sweep: crossfade from a low band to a high band.
    x = bp(x, 400, 1500) * (1 - p) + bp(x, 2500, 9000) * p
    x *= p ** 2.2
    place(x, t0, gain, 0.0, 0.5)


def heartbeat(t0, gain=0.35):
    for o, g in ((0, 1.0), (0.24, 0.7)):
        n = int(0.3 * SR)
        t = np.arange(n) / SR
        f = 38 + 30 * np.exp(-t * 20)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 14)
        place(x, t0 + o, gain * g)


def impact(t0, notes, gain=0.25):
    kick(t0, 0.6)
    crash(t0, 0.13)
    pad(notes, t0, t0 + 2.5, gain=gain, cutoff=3000, attack=0.01, release=2.0, verb=0.7)


# ---------------- arrangement ----------------
PROG_HOPE = [("F2", ["F3", "A3", "C4", "E4"]), ("C2", ["C3", "G3", "C4", "E4"]), ("G2", ["G3", "B3", "D4", "G4"]), ("A2", ["A3", "C4", "E4", "G4"])]
ARP = {
    "F2": ["F4", "A4", "C5", "E5"],
    "C2": ["C4", "G4", "C5", "E5"],
    "G2": ["G4", "B4", "D5", "G5"],
    "A2": ["A4", "C5", "E5", "G5"],
}


def groove(t0, t1, kick_g=0.45, clap_on=True, hats=True, arp_g=0.09, bass_on=True, pad_g=0.07):
    bar = 4 * BEAT
    t = t0
    i = 0
    while t < t1 - 0.01:
        root, chord = PROG_HOPE[i % 4]
        end = min(t + bar, t1)
        pad(chord, t, end, gain=pad_g, cutoff=1800, attack=0.3, release=0.6, verb=0.5)
        for b in range(4):
            bt = t + b * BEAT
            if bt >= t1:
                break
            if kick_g:
                kick(bt, kick_g)
            if clap_on and b in (1, 3):
                clap(bt)
            if hats:
                hat(bt + BEAT / 2, 0.045)
                hat(bt, 0.02, pan=-0.25)
            if bass_on:
                bass(root, bt, BEAT * 0.9, 0.2 if b % 2 == 0 else 0.14)
                bass(root, bt + BEAT * 0.5, BEAT * 0.4, 0.09)
        if arp_g:
            notes = ARP[root]
            for s in range(16):
                st = t + s * BEAT / 4
                if st >= t1:
                    break
                if s % 4 != 3:
                    pluck(notes[(s * 3) % 4], st, arp_g, 0.6, pan=(-0.3 if s % 2 else 0.3), bright=1.3)
        t += bar
        i += 1


# Part A ---------------------------------------------------------------
# Scene 1: dark, sparse. Heartbeat under "people are trapped".
pad(["A2", "E3", "A3", "C4"], 0.0, 15.1, gain=0.13, cutoff=700, attack=2.5, release=1.0, swell=(0.6, 1.0))
for k in range(8):
    heartbeat(6.5 + k * 1.15, 0.28)
pluck("E5", 10.76, 0.06, 3.0, bright=0.5, verb=0.8)
pluck("C5", 13.0, 0.06, 3.0, bright=0.5, verb=0.8)
# "But there's a problem": tension shift, high held note.
pad(["F2", "C3", "F3", "A3"], 15.0, 22.8, gain=0.12, cutoff=900, attack=0.6, release=0.8, swell=(0.8, 1.2))
pad(["E5"], 16.74, 22.3, gain=0.05, cutoff=4000, attack=1.6, release=0.5)

# Scene 2: driving low pulse, minor progression.
minor = [("A1", ["A2", "E3", "A3", "C4"]), ("F1", ["F2", "C3", "F3", "A3"]), ("D2", ["D3", "F3", "A3", "D4"]), ("E1", ["E2", "B2", "E3", "G#3"])]
t = 22.4
i = 0
while t < 38.9:
    root, chord = minor[i % 4]
    end = min(t + 4.0, 38.9)
    pad(chord, t, end, gain=0.10, cutoff=1000, attack=0.4, release=0.6)
    st = t
    while st < end - 0.01:
        bass(root, st, 0.22, 0.17)
        st += BEAT / 2
    if t >= 26.4:
        for b in range(0, 8, 2):
            if t + b * BEAT < 38.9:
                kick(t + b * BEAT, 0.28)
    t += 4.0
    i += 1
riser(36.5, 39.1, 0.05)

# Scene 3: the question, then the lift into the swarm.
for k, n in enumerate(["C4", "G4", "E5", "D5", "C5", "G4", "E5", "B4"]):
    pluck(n, 39.5 + k * 0.72, 0.12, 2.2, pan=(-0.2 if k % 2 else 0.2), bright=0.8, verb=0.7)
pad(["C3", "G3", "E4"], 39.3, 47.9, gain=0.08, cutoff=1400, attack=2.0, release=0.5)
riser(45.2, 47.9, 0.07)
groove(47.9, 52.9, kick_g=0.35, clap_on=False, hats=True, arp_g=0.08, pad_g=0.06)

# Scenes 4–6: main groove, with small turnarounds on scene cuts.
impact(52.9, ["C3", "G3", "C4", "E4", "G4"], gain=0.14)
groove(52.9, 72.6)
crash(73.0, 0.08)
groove(73.0, 87.3)
crash(87.7, 0.08)
groove(87.7, 100.5, clap_on=True)
riser(100.0, 102.3, 0.05)
pad(["C3", "G3", "C4", "E4"], 100.5, 102.6, gain=0.07, cutoff=1500, attack=0.2, release=0.8)

# Part B: lighter bed under the demo, lift when the dashboard appears.
crash(B0, 0.07)
groove(B0, B0 + 31.2, kick_g=0.3, clap_on=False, hats=False, arp_g=0.06, pad_g=0.06)
crash(B0 + 31.2, 0.06)
groove(B0 + 31.2, B0 + 70.9, kick_g=0.32, clap_on=False, hats=True, arp_g=0.065, pad_g=0.06)
groove(B0 + 70.9, B0 + 74.6, kick_g=0.0, clap_on=False, hats=False, arp_g=0.05, pad_g=0.06, bass_on=False)
riser(B0 + 73.6, C0, 0.05)

# Part C: steady, lighter groove under the technical walkthrough; lift into the roadmap.
groove(C0, C0 + 31.7, kick_g=0.26, clap_on=False, hats=True, arp_g=0.05, pad_g=0.055)
crash(C0 + 31.9, 0.06)
groove(C0 + 31.9, D0 - 0.2, kick_g=0.32, clap_on=True, hats=True, arp_g=0.06, pad_g=0.06)

# Part D: "When lives are on the line, every second counts." Then the brand.
pad(["A2", "E3", "A3"], D0, D0 + 2.0, gain=0.1, cutoff=600, attack=0.3, release=0.4)
heartbeat(D0 + 0.2, 0.3)
heartbeat(D0 + 1.1, 0.3)
impact(D0 + 1.9, ["F2", "C3", "F3", "A3"], gain=0.16)
riser(D0 + 2.4, D0 + 3.2, 0.07)
impact(D0 + 3.2, ["C3", "G3", "C4", "E4", "G4", "C5"], gain=0.24)
groove(D0 + 3.2, D0 + 5.0, kick_g=0.4, clap_on=True, hats=True, arp_g=0.08, pad_g=0.07)
pluck("C6", D0 + 3.2, 0.09, 2.5, verb=0.9)

# ---------------- mixdown ----------------
ir_n = int(2.4 * SR)
ti = np.arange(ir_n) / SR
ir_l = rng.standard_normal(ir_n) * np.exp(-ti * 2.8)
ir_r = rng.standard_normal(ir_n) * np.exp(-ti * 2.8)
ir_l, ir_r = lp(ir_l, 5000), lp(ir_r, 5000)
send = hp(verb_send, 200)
L += fftconvolve(send, ir_l)[:N] * 0.05
R += fftconvolve(send, ir_r)[:N] * 0.05

mix = np.stack([L, R], 1)[: int(TOTAL * SR)]
mix = hp(mix.T, 30).T
# Gentle bus compression then a ceiling at -3 dBFS, leaving headroom for narration.
peak = np.abs(mix).max()
mix = np.tanh(mix / peak * 1.4) / np.tanh(1.4)
mix *= 10 ** (-3 / 20)
fade = int(0.8 * SR)
mix[-fade:] *= np.linspace(1, 0, fade)[:, None]

out = os.path.join(os.path.dirname(__file__), "..", "public", "audio", "music.wav")
os.makedirs(os.path.dirname(out), exist_ok=True)
sf.write(out, mix.astype(np.float32), SR, subtype="PCM_16")
print(os.path.abspath(out), f"{TOTAL:.1f}s")
