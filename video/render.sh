#!/usr/bin/env bash
# Renders the full cut. Frames are drawn by Chrome on the GPU (ANGLE/EGL),
# then encoded on the GPU with VAAPI. Output: out/swarm.mp4 (music + SFX).
# The recorded narration (public/audio/narration.wav) is mixed in; VO=0 ./render.sh leaves it out.
set -euo pipefail
cd "$(dirname "$0")"
COMP=${COMP:-Full}
CHROME=/usr/bin/google-chrome-stable
FLAGS=(--gl=angle-egl --concurrency=14 --offthreadvideo-threads=12 --offthreadvideo-cache-size-in-bytes=6000000000 --browser-executable="$CHROME" --log=error)
mkdir -p out/frames
rm -f out/frames/*.jpeg
npx remotion render src/index.ts "$COMP" out/frames --sequence --image-format=jpeg --jpeg-quality=95 "${FLAGS[@]}"
VO_PROP=$([ "${VO:-1}" = 0 ] && echo false || echo true)
npx remotion render src/index.ts "$COMP" out/audio.wav --codec=wav --props="{\"music\":true,\"vo\":$VO_PROP}" "${FLAGS[@]}"
first=$(basename "$(find out/frames -name "element-*.jpeg" -print -quit)")
pattern="out/frames/element-%0$(( ${#first} - 13 ))d.jpeg"
ffmpeg -hide_banner -loglevel error -y -vaapi_device /dev/dri/renderD128 -framerate 30 -i "$pattern" -i out/audio.wav \
  -vf 'format=nv12,hwupload' -c:v h264_vaapi -qp 18 -profile:v high -c:a aac -b:a 256k -movflags +faststart -shortest out/swarm.mp4
echo out/swarm.mp4
