# Vitals from artificial feeds (Presage SmartSpectra)

Experiment: can the backend get heart rate and breathing rate from a video feed
by calling Presage, and what does it do with photos of injured or grimacing people?

## Pipeline

1. `fetch_samples.py` downloads real photos from Wikimedia Commons with license info.
   18 curated ones live in `samples/` (images gitignored, `samples/manifest.json` committed).
2. `make_feeds.py` turns each photo into four 30 s, 30 fps clips:
   - `static`: photo repeated, no physiology (negative control)
   - `calm`: injected pulse 72 bpm (skin-pixel colour change, green strongest) and breathing 15 brpm (vertical stretch)
   - `distress`: injected 120 bpm / 28 brpm
   - `drone`: `distress` degraded to 640x360 with hover shake, sensor noise and JPEG q35
3. `node/measure.mjs` streams one clip through `@smartspectra/node-sdk` using
   `useCustomInput()` + `sendFrame()` at real-time pace, the same path a backend
   would use for relay frames. It writes every metrics packet and validation code.
4. `node/bench.mjs` runs `measure.mjs` per clip and writes `results/bench.json`.

```
cd vitals
uv venv --python 3.12 .venv && uv pip install --python .venv opencv-python-headless numpy
.venv/bin/python make_feeds.py samples feeds
cd node && npm install
echo 'PRESAGE_API_KEY=...' > ../.env
node bench.mjs crying_1 neutral_4      # skips clips already in results/raw
```

Credits: 1 credit = 30 s of measurement, so each clip costs about 1 credit.

## Dead end: `presage_technologies` (Python REST client)

The PyPI client (`Physiology.queue_processing_hr_rr`) targets
`api.physiology.presagetech.com/v1/upload-url`, which now returns
`403 {"message":"Missing Authentication Token"}` (API Gateway: no such route).
Its preprocessing also needs Python <= 3.12 and `mediapipe==0.10.21`.
Use the SmartSpectra SDK instead.

## Results (2026-10-24, node-sdk 3.4.0, 5 images x 4 variants)

`trusted` = median of pulse readings with `stable && confidence >= 80`.

| clip | truth HR / RR | raw HR | trusted HR (n) | RR | first HR / RR (s) | validation |
|---|---|---|---|---|---|---|
| crying_1 calm | 72 / 15 | 72.2 | 72.2 (22) | 15.0 | 12.9 / 11.7 | ok |
| crying_1 distress | 120 / 28 | 119.6 | 120.1 (7) | 28.0 | 12.2 / 10.8 | ok |
| crying_1 static | - | 76.0 | none (0/14) | - | 12.2 / - | ok |
| crying_1 drone | 120 / 28 | - | - | - | - | ChestNotVisible |
| neutral_4 calm | 72 / 15 | 72.1 | 72.1 (22) | 15.0 | 12.2 / 11.7 | ok |
| neutral_4 distress | 120 / 28 | 120.2 | 120.2 (37) | 28.0 | 13.3 / 12.3 | ok |
| neutral_4 static | - | 83.1 | none (0/21) | 19.6 | 12.2 / 16.8 | ok |
| neutral_4 drone | 120 / 28 | - | - | - | - | ChestNotVisible |
| pain_3 calm (sepia) | 72 / 15 | 72.1 | 72.1 (22) | - | 14.9 / - | ok |
| pain_3 distress | 120 / 28 | 120.2 | 120.2 (37) | - | 15.0 / - | ok |
| pain_3 static | - | 82.6 | none (0/26) | - | 16.5 / - | ok |
| pain_3 drone | 120 / 28 | - | - | - | - | ChestNotVisible |
| grimace_1 (all 4) | | - | - | - | - | FaceTooClose |
| casualty_5 (all 4) | | - | - | - | - | NoFaceFound |

Findings:

- When the SDK accepts the frame, injected HR comes back within 0.5 bpm and RR
  exactly, after about 12 s of warm-up.
- Still photos are not rejected. The SDK reports a plausible but wrong HR
  (76-83 bpm) and sometimes RR (19.6). These readings are never `stable` with
  confidence >= 80, so the backend must apply that gate before showing a vital.
- Validation is strict about framing. Close-up faces fail with `FaceTooClose`.
  Wide scenes with small faces (the casualty/rubble photos) fail with `NoFaceFound`.
  A drone feed needs a medium shot: whole face plus shoulders.
- The `drone` degradation kills all output (`ChestNotVisible`). Not yet known
  which part (640x360 resolution, shake, noise or JPEG) is responsible.
- Sepia photo `pain_3` gives HR but no RR, though validation reported ok.
- The sample photos and the injected signal are synthetic. These numbers show what
  the SDK accepts and how it fails, not accuracy on real injured people.

Caveat: `make_feeds.py` uses a YCrCb skin threshold. On beige backgrounds
(`grimace_3`, `grimace_4`, sepia photos) it marks most of the frame as skin,
so the pulse is injected into the background too.

One batch run lost 5 clips: the `measure.mjs` child exited without writing
output. A rerun of the same clips succeeded. `bench.mjs` now logs the exit
status and stderr tail.
