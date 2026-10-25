"""Turn still photos into artificial video feeds for the Presage benchmark.

Presage measures vitals from video (rPPG colour pulse on the face, optical-flow
chest motion for breathing), so a photo has to become a clip first. Each image
yields several feeds:

  static   - the photo repeated; carries no physiology, so it is the negative
             control (any vitals returned here are false positives)
  calm     - synthetic pulse at 72 bpm and breathing at 15 brpm injected
  distress - synthetic pulse at 120 bpm and breathing at 28 brpm injected
  drone    - "distress" passed through E58-like degradation (640x360, camera
             shake, sensor noise, heavy JPEG), to see what survives the link

Pulse is a small sinusoidal colour change on skin pixels (green strongest, as
in real blood-volume signal). Breathing is a vertical stretch anchored at the
top of the frame, so the chest moves more than the head.

    python vitals/make_feeds.py vitals/samples vitals/feeds [--seconds 30]

Writes <feeds>/<image>__<variant>.mp4 and <feeds>/truth.json.
"""
import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

FPS = 30
PROFILES = {"calm": (72, 15), "distress": (120, 28)}
# Peak fractional intensity change per channel (B, G, R); real rPPG is ~0.1-1%.
PULSE_GAIN = np.array([0.004, 0.012, 0.006], np.float32)
BREATH_STRETCH = 0.006  # peak vertical stretch at the bottom row, fraction of height


def skin_mask(img):
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(ycrcb, (0, 133, 77), (255, 173, 127))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return cv2.GaussianBlur(mask, (15, 15), 0).astype(np.float32)[..., None] / 255


def fit(img, max_w=1280):
    h, w = img.shape[:2]
    if w > max_w:
        img = cv2.resize(img, (max_w, round(h * max_w / w)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    return img[: h - h % 2, : w - w % 2]  # yuv420p needs even dimensions


def encoder(path, w, h, crf):
    return subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium",
         "-crf", str(crf), "-pix_fmt", "yuv420p", str(path)],
        stdin=subprocess.PIPE)


def physiology_frames(img, mask, hr, rr, n):
    h, w = img.shape[:2]
    base = img.astype(np.float32)
    ys = np.arange(h, dtype=np.float32)[:, None].repeat(w, 1)
    xs = np.arange(w, dtype=np.float32)[None, :].repeat(h, 0)
    rng = np.random.default_rng(0)
    pulse_phase = rng.uniform(0, 2 * np.pi)
    for i in range(n):
        t = i / FPS
        # Slightly non-sinusoidal pulse (fundamental plus dicrotic harmonic).
        p = np.sin(2 * np.pi * hr / 60 * t + pulse_phase) + 0.3 * np.sin(4 * np.pi * hr / 60 * t + pulse_phase)
        frame = base * (1 + mask * PULSE_GAIN * p)
        b = BREATH_STRETCH * np.sin(2 * np.pi * rr / 60 * t)
        frame = cv2.remap(frame, xs, (ys / (1 + b)).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        yield np.clip(frame, 0, 255).astype(np.uint8)


def degrade(frames, size=(640, 360), quality=35):
    rng = np.random.default_rng(1)
    shake = np.zeros(2)
    for frame in frames:
        shake = 0.9 * shake + rng.normal(0, 0.6, 2)  # random-walk hover drift, pixels
        h, w = frame.shape[:2]
        m = np.float32([[1, 0, shake[0]], [0, 1, shake[1]]])
        frame = cv2.warpAffine(frame, m, (w, h), borderMode=cv2.BORDER_REFLECT)
        s = min(size[0] / w, size[1] / h)
        small = cv2.resize(frame, (round(w * s) // 2 * 2, round(h * s) // 2 * 2), interpolation=cv2.INTER_AREA)
        noisy = np.clip(small.astype(np.float32) + rng.normal(0, 3, small.shape), 0, 255).astype(np.uint8)
        _, jpg = cv2.imencode(".jpg", noisy, [cv2.IMWRITE_JPEG_QUALITY, quality])
        yield cv2.imdecode(jpg, cv2.IMREAD_COLOR)


def write(path, frames, crf=12):
    proc = None
    for frame in frames:
        if proc is None:
            proc = encoder(path, frame.shape[1], frame.shape[0], crf)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples", type=Path)
    ap.add_argument("feeds", type=Path)
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--only", nargs="*", help="image stems to render (default: all)")
    args = ap.parse_args()
    args.feeds.mkdir(parents=True, exist_ok=True)
    n = args.seconds * FPS
    truth = {}
    for src in sorted(args.samples.glob("*.jpg")):
        if args.only and src.stem not in args.only:
            continue
        img = fit(cv2.imread(str(src)))
        mask = skin_mask(img)
        coverage = float(mask.mean())
        write(args.feeds / f"{src.stem}__static.mp4", (img for _ in range(n)))
        truth[f"{src.stem}__static"] = dict(image=src.name, variant="static", hr=None, rr=None, skin=coverage)
        for name, (hr, rr) in PROFILES.items():
            write(args.feeds / f"{src.stem}__{name}.mp4", physiology_frames(img, mask, hr, rr, n))
            truth[f"{src.stem}__{name}"] = dict(image=src.name, variant=name, hr=hr, rr=rr, skin=coverage)
        hr, rr = PROFILES["distress"]
        write(args.feeds / f"{src.stem}__drone.mp4", degrade(physiology_frames(img, mask, hr, rr, n)))
        truth[f"{src.stem}__drone"] = dict(image=src.name, variant="drone", hr=hr, rr=rr, skin=coverage)
        print(f"{src.stem}: skin {coverage:.1%}")
    with open(args.feeds / "truth.json", "w") as f:
        json.dump(truth, f, indent=1)


if __name__ == "__main__":
    main()
