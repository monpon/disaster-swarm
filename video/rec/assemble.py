"""Turn a screencast capture (frames + timestamps) into a constant-30-fps clip.

Usage: python3 rec/assemble.py <capture dir> <out.mp4> [end seconds] [crop w:h:x:y in CSS px]
Encodes on the GPU with VAAPI (H.264, near-lossless, no B-frames) so Remotion gets a clean source.
"""
import json
import os
import subprocess
import sys

src, out = sys.argv[1], sys.argv[2]
meta = json.load(open(os.path.join(src, "frames.json")))
frames = meta["frames"]
end = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else meta.get("END") or frames[-1]["t"] + 0.5
crop = sys.argv[4] if len(sys.argv) > 4 else None

lines = ["ffconcat version 1.0"]
for i, fr in enumerate(frames):
    t = 0 if i == 0 else fr["t"]
    nxt = frames[i + 1]["t"] if i + 1 < len(frames) else end
    lines += [f"file '{fr['file']}'", f"duration {max(0.001, nxt - t):.4f}"]
lines.append(f"file '{frames[-1]['file']}'")
listfile = os.path.join(src, "list.ffconcat")
open(listfile, "w").write("\n".join(lines) + "\n")

vf = "fps=30"
if crop:
    w, h, x, y = (float(v) * meta["DSF"] for v in crop.split(":"))
    # Even dimensions for the encoder.
    vf += f",crop={int(w) // 2 * 2}:{int(h) // 2 * 2}:{int(x)}:{int(y)}"
vf += ",format=nv12,hwupload"
subprocess.run(
    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-vaapi_device", "/dev/dri/renderD128",
     "-f", "concat", "-safe", "0", "-i", listfile, "-vf", vf, "-c:v", "h264_vaapi", "-qp", "14", "-bf", "0", "-t", f"{end:.3f}", out],
    check=True,
)
print(out)
