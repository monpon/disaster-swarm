"""Builds a scratch narration track from vo/script.json with Piper TTS and
reports any line that runs past the next cue, so timings can be checked
before the real voiceover is recorded.

Usage: tools/.venv/bin/python vo/scratch.py   (writes public/audio/vo.wav and vo/timing.md)
"""
import json
import os
import subprocess
import tempfile

import numpy as np
import soundfile as sf

ROOT = os.path.join(os.path.dirname(__file__), "..")
MODEL = os.path.join(ROOT, "tools", "voices", "en_US-ryan-high.onnx")
PIPER = os.path.join(ROOT, "tools", ".venv", "bin", "piper")
TOTAL = 215.0
SR = 48000
GAP = 0.2

lines = json.load(open(os.path.join(ROOT, "vo", "script.json")))["lines"]
out = np.zeros(int(TOTAL * SR) + SR)
rows = []
prev_end = 0.0
with tempfile.TemporaryDirectory() as tmp:
    for i, ln in enumerate(lines):
        wav = os.path.join(tmp, f"{i}.wav")
        # TTS reads capitals as acronyms; emphasis is for the human reader only.
        text = ln["text"].lower().replace("3d", "3D").replace("swarm", "Swarm").replace("presage", "Presage").replace("sensors", "Sensors")
        subprocess.run([PIPER, "-m", MODEL, "-f", wav, "--length-scale", "0.92", "--sentence-silence", "0.1"], input=text.encode(), check=True, capture_output=True)
        x, sr = sf.read(wav)
        if x.ndim > 1:
            x = x.mean(1)
        # Resample to 48 kHz by linear interpolation (scratch quality is fine).
        n = int(len(x) * SR / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)
        start = ln["at"] if ln["at"] is not None else prev_end + GAP
        i0 = int(start * SR)
        out[i0 : i0 + len(x)] += x * 0.9
        end = start + len(x) / SR
        rows.append((ln["scene"], start, end, ln["text"]))
        prev_end = end

sf.write(os.path.join(ROOT, "public", "audio", "vo.wav"), np.stack([out, out], 1)[: int(TOTAL * SR)].astype(np.float32), SR, subtype="PCM_16")

md = ["| Scene | Start | End | Line | Note |", "|---|---|---|---|---|"]
issues = 0
for k, (scene, s, e, text) in enumerate(rows):
    nxt = rows[k + 1][1] if k + 1 < len(rows) else TOTAL
    note = ""
    if e > nxt - 0.05:
        note = f"runs {e - nxt + 0.05:.2f}s into next cue"
        issues += 1
    md.append(f"| {scene} | {s:.2f} | {e:.2f} | {text} | {note} |")
open(os.path.join(ROOT, "vo", "timing.md"), "w").write("\n".join(md) + "\n")
print("\n".join(r for r in md if "runs" in r) or "no overlaps")
print(f"{issues} overlaps")
