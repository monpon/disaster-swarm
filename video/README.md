# Swarm demo video

Remotion project for the Cal Hacks 13.0 video. It builds Part A (problem, solution,
research), Part B (website demo), Part C (technical section + roadmap) and Part D (closing), about 3:31 in total.

## Layout

| Path | What |
|---|---|
| `src/timeline.ts` | Master timing: scene bounds and narration cue times |
| `src/scenes/` | One component per scene (`S1Problem` … `S6Research`, `PartB`, `Closing`) |
| `src/components/kit.tsx` | Shared pieces: Ken Burns, stock clips, bullets with nested logos, citations, clock |
| `vo/script.json` | Narration cue sheet (absolute times). `vo/timing.md` is the measured table |
| `public/stock/` | Stock footage, photos, logos. Licences in `public/stock/CREDITS.md` |
| `public/rec/` | Screen recordings of the real web app (generated, see below) |
| `public/audio/` | `music.wav` (custom score), `vo.wav` (scratch TTS narration) |
| `sources.md` | Works cited |

## Rebuild

```sh
npm install
# 1. Serve the production web app on :5317 (from ui/apps/web)
#    bunx vite build && PORT=5317 node .output/server/index.mjs
# 2. Record the website (slow-motion capture, 3200x1800, then retimed to 30 fps)
node rec/record.mjs                       # Part B take
for c in race mapstory vitals; do node rec/clips.mjs $c; done
python3 rec/assemble.py rec/take public/rec/partB.mp4 78
python3 rec/assemble.py rec/clip-race public/rec/race.mp4 "" 1300:731:150:70
python3 rec/assemble.py rec/clip-mapstory public/rec/mapstory.mp4 "" 920:632:554:168
python3 rec/assemble.py rec/clip-vitals public/rec/vitals.mp4 "" 1000:452:250:228
cp rec/take/events.json src/data/events.json
# 3. Audio
python3 -m venv tools/.venv && tools/.venv/bin/pip install numpy scipy soundfile piper-tts
python3 tools/sfx.py
tools/.venv/bin/python tools/music.py
tools/.venv/bin/python vo/scratch.py      # needs tools/voices/en_US-ryan-high.onnx
# 4. Render (Chrome draws on the GPU via ANGLE, ffmpeg encodes with VAAPI)
./render.sh
```

`npm run studio` opens Remotion Studio for scrubbing.

## Swapping in the real voiceover

Record each line from `vo/script.json` (Part C lines included) at its `at` time, or record one take and
align it in Studio. Then export it as `public/audio/vo.wav` (48 kHz, full length 210.8 s)
and run `VO=1 ./render.sh`.

## Part C

`src/scenes/PartC.tsx` is the technical section: a hand-drawn architecture diagram
(rough.js + the Virgil font) and a roadmap slide. The script with timings and graphics cues
is in `vo/part-c-script.md`. Put team photos, flight video and simulator screenshots in
`public/team/` (file names listed in that doc) and re-render; empty slots show a dashed placeholder.
