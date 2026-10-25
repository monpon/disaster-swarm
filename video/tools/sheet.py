"""Contact sheet: python3 tools/sheet.py out.jpg img1 img2 ... (4 per row, 480x270 tiles)"""
import subprocess, sys
out, files = sys.argv[1], sys.argv[2:]
n = len(files)
f = "".join(f"[{i}]scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:-1:-1[v{i}];" for i in range(n))
f += "".join(f"[v{i}]" for i in range(n)) + f"xstack=inputs={n}:fill=black:layout=" + "|".join(f"{(i%4)*480}_{(i//4)*270}" for i in range(n)) + "[o]"
subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + sum([["-i", x] for x in files], []) + ["-filter_complex", f, "-map", "[o]", "-frames:v", "1", out], check=True)
