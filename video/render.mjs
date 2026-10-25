// Incremental render: each part (A–D) is rendered on its own and cached under
// out/parts/. A part is re-rendered only when something it uses changes:
//   - any source file it imports (followed recursively),
//   - the timeline.ts values those files import (by value, not the whole file),
//   - any media file it references (stock/, rec/, web/, team/, sfx/, fonts/),
//   - the render settings below.
// The cached parts are joined, the narration and music are mixed in with
// ffmpeg, and the result is encoded once on the GPU (VAAPI) to out/swarm.mp4.
//
//   node render.mjs              render what changed, then assemble
//   node render.mjs --force B    re-render part B even if cached (any of A B C D)
//   node render.mjs --dry        print each part's hash and cache status, render nothing
//   VO=0 node render.mjs         leave the narration out
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.dirname(new URL(import.meta.url).pathname);
const OUT = path.join(ROOT, "out");
const CACHE = path.join(OUT, "parts");
const CHROME = "/usr/bin/google-chrome-stable";
const FPS = 30;
// Bump when the way parts are rendered changes; invalidates every cached part.
const RENDER_VERSION = "1";
const PART_FLAGS = ["--codec=h264-mkv", "--audio-codec=pcm-16", "--crf=12", "--x264-preset=veryfast"];
const BROWSER_FLAGS = [
  "--gl=angle-egl",
  "--concurrency=14",
  "--offthreadvideo-threads=12",
  "--offthreadvideo-cache-size-in-bytes=6000000000",
  `--browser-executable=${CHROME}`,
  "--log=error",
];

const T = await import(path.join(ROOT, "src/timeline.ts"));
const frames = (s) => Math.round(s * FPS);
const PARTS = [
  { id: "A", comp: "PartA", entry: "src/scenes/PartA.tsx", start: 0, len: T.PART_A.end },
  { id: "B", comp: "PartB", entry: "src/scenes/PartB.tsx", start: T.PART_A.end, len: T.PART_B.end - T.PART_B.start },
  { id: "C", comp: "PartC", entry: "src/scenes/PartC.tsx", start: T.PART_B.end, len: T.PART_C_LEN },
  { id: "D", comp: "PartD", entry: "src/scenes/Closing.tsx", start: T.PART_B.end + T.PART_C_LEN, len: T.PART_D_LEN },
];

// ---------- dependency hashing ----------
const IMPORT_RE = /^\s*import\s+(?:([\s\S]*?)\s+from\s+)?["']([^"']+)["']/gm;
const ASSET_RE = /["'`]((?:stock|rec|web|team|sfx|fonts|audio)\/[^"'`$]+)["'`]/g;

function resolve(from, spec) {
  const base = path.resolve(path.dirname(from), spec);
  for (const cand of [base, `${base}.ts`, `${base}.tsx`, `${base}.json`, path.join(base, "index.ts"), path.join(base, "index.tsx")]) {
    if (fs.existsSync(cand) && fs.statSync(cand).isFile()) return cand;
  }
  throw new Error(`cannot resolve ${spec} from ${from}`);
}

const fileHashCache = new Map();
function hashFile(p) {
  if (!fileHashCache.has(p)) fileHashCache.set(p, crypto.createHash("sha1").update(fs.readFileSync(p)).digest("hex"));
  return fileHashCache.get(p);
}

function partHash(part) {
  const timelinePath = path.join(ROOT, "src/timeline.ts");
  const seen = new Set();
  const timelineNames = new Set();
  const assets = new Set();
  const usesSfx = { v: false };
  const usesLogos = { v: false };
  const visit = (file) => {
    if (seen.has(file)) return;
    seen.add(file);
    if (!/\.(tsx?|json)$/.test(file)) return;
    const src = fs.readFileSync(file, "utf8");
    for (const m of src.matchAll(ASSET_RE)) assets.add(m[1]);
    if (/<Sfx\b/.test(src)) usesSfx.v = true;
    if (/<Logo\b|logos?\s*[:=]|logo:\s*\{/.test(src)) usesLogos.v = true;
    for (const m of src.matchAll(IMPORT_RE)) {
      const [, names, spec] = m;
      if (!spec.startsWith(".")) continue;
      const target = resolve(file, spec);
      if (target === timelinePath) {
        for (const n of (names ?? "").replace(/[{}]/g, "").split(",")) {
          const name = n.trim().split(/\s+as\s+/)[0];
          if (name) timelineNames.add(name);
        }
        continue;
      }
      visit(target);
    }
  };
  visit(path.join(ROOT, part.entry));
  const files = [...seen].sort();
  const media = [...assets].map((a) => path.join(ROOT, "public", a));
  // Sounds and logos are referenced by bare file name, so hash their whole folders.
  if (usesSfx.v) for (const f of fs.readdirSync(path.join(ROOT, "public/sfx"))) media.push(path.join(ROOT, "public/sfx", f));
  if (usesLogos.v) for (const f of fs.readdirSync(path.join(ROOT, "public/stock/logos"))) media.push(path.join(ROOT, "public/stock/logos", f));
  const h = crypto.createHash("sha1");
  h.update(`v${RENDER_VERSION}|${PART_FLAGS.join(" ")}|${part.comp}|${part.len}\n`);
  h.update(fs.readFileSync(path.join(ROOT, "package-lock.json")));
  for (const f of files) h.update(`${path.relative(ROOT, f)}:${hashFile(f)}\n`);
  for (const n of [...timelineNames].sort()) h.update(`timeline.${n}=${JSON.stringify(T[n])}\n`);
  for (const m of [...new Set(media)].sort()) {
    if (!fs.existsSync(m)) throw new Error(`part ${part.id} references missing media ${path.relative(ROOT, m)}`);
    h.update(`${path.relative(ROOT, m)}:${hashFile(m)}\n`);
  }
  part.deps = { files: files.length, timeline: [...timelineNames].sort(), media: new Set(media).size };
  return h.digest("hex");
}

// ---------- rendering ----------
const run = (cmd, args, opts = {}) => execFileSync(cmd, args, { stdio: "inherit", cwd: ROOT, ...opts });
const clip = (id) => path.join(CACHE, `${id}.mkv`);
const stamp = (id) => path.join(CACHE, `${id}.hash`);
const isCached = (part, hash) => fs.existsSync(clip(part.id)) && fs.existsSync(stamp(part.id)) && fs.readFileSync(stamp(part.id), "utf8") === hash;

function renderPart(part, hash) {
  const tmp = `${clip(part.id)}.tmp.mkv`;
  console.log(`part ${part.id}: rendering ${frames(part.len)} frames`);
  run("npx", ["remotion", "render", "src/index.ts", part.comp, tmp, ...PART_FLAGS, ...BROWSER_FLAGS]);
  fs.renameSync(tmp, clip(part.id));
  fs.writeFileSync(stamp(part.id), hash);
}

function assemble() {
  const list = path.join(CACHE, "concat.txt");
  fs.writeFileSync(list, PARTS.map((p) => `file '${clip(p.id)}'`).join("\n") + "\n");
  const joined = path.join(CACHE, "joined.mkv");
  run("ffmpeg", ["-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", joined]);

  const vo = process.env.VO !== "0";
  const cStart = T.PART_B.end;
  const dStart = cStart + T.PART_C_LEN;
  // Music sits under the narration and comes up to full for the closing (same curve as Root.tsx).
  const duck = vo ? `if(lt(t,${dStart - 0.3}),0.3,if(lt(t,${dStart + 0.3}),0.3+0.7*(t-${dStart - 0.3})/0.6,1))` : "1";
  const inputs = ["-i", joined, "-i", "public/audio/music.wav"];
  let filter = `[1:a]volume='${duck}':eval=frame[m]`;
  let mixIn = "[0:a][m]";
  let n = 2;
  if (vo) {
    inputs.push("-i", "public/audio/narration.wav", "-i", "public/audio/partC.wav");
    const ms = Math.round(cStart * 1000);
    filter += `;[3:a]adelay=${ms}|${ms}[c]`;
    mixIn += "[2:a][c]";
    n = 4;
  }
  filter += `;${mixIn}amix=inputs=${n}:normalize=0:duration=first[a]`;
  run("ffmpeg", [
    "-hide_banner", "-loglevel", "error", "-y", "-vaapi_device", "/dev/dri/renderD128",
    ...inputs,
    "-filter_complex", filter,
    "-map", "0:v", "-map", "[a]",
    "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-qp", "18", "-profile:v", "high",
    "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
    path.join(OUT, "swarm.mp4"),
  ]);
  console.log("out/swarm.mp4");
}

// ---------- main ----------
fs.mkdirSync(CACHE, { recursive: true });
const args = process.argv.slice(2);
const force = new Set();
const fi = args.indexOf("--force");
if (fi !== -1) for (const id of (args[fi + 1] ?? "").split(",")) force.add(id.trim().toUpperCase());
if (args.includes("--dry")) {
  for (const part of PARTS) {
    const hash = partHash(part);
    console.log(`part ${part.id}: ${hash.slice(0, 10)} ${isCached(part, hash) ? "cached" : "needs render"} · ${part.deps.files} files, ${part.deps.media} media, timeline: ${part.deps.timeline.join(", ")}`);
  }
  process.exit(0);
}

for (const part of PARTS) {
  const hash = partHash(part);
  if (!force.has(part.id) && isCached(part, hash)) {
    console.log(`part ${part.id}: unchanged, using cache`);
  } else {
    renderPart(part, hash);
  }
}
assemble();
