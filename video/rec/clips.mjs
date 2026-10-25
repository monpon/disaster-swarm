// Records short Part A clips of the real landing page (race split, map story,
// vitals) using the same slow-motion screencast approach as record.mjs.
// Usage: node rec/clips.mjs <race|mapstory|vitals> [baseUrl]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const which = process.argv[2];
const BASE = process.argv[3] ?? "http://localhost:5317";
const OUT = path.resolve(`rec/clip-${which}`);
const W = 1600;
const H = 900;
const DSF = 2;
const SLOW = 3;

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, "frames"), { recursive: true });

const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome-stable",
  headless: true,
  args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist", "--hide-scrollbars", "--force-color-profile=srgb", `--force-device-scale-factor=${DSF}`, `--window-size=${W},${H + 87}`],
});
const ctx = await browser.newContext({ viewport: null });
const WALL0 = Date.now();
await ctx.addInitScript(([SLOW, WALL0]) => {
  const pn = performance.now.bind(performance);
  const dn = Date.now;
  performance.now = () => pn() / SLOW;
  Date.now = () => WALL0 + (dn() - WALL0) / SLOW;
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => raf(() => cb(performance.now()));
  const st = window.setTimeout.bind(window);
  const si = window.setInterval.bind(window);
  window.setTimeout = (f, d = 0, ...a) => st(f, d * SLOW, ...a);
  window.setInterval = (f, d = 0, ...a) => si(f, d * SLOW, ...a);
  const s = document.createElement("style");
  s.textContent = "html{scroll-behavior:auto!important}";
  document.documentElement.appendChild(s);
}, [SLOW, WALL0]);

const page = await ctx.newPage();
const anim = await ctx.newCDPSession(page);
await anim.send("Animation.enable");
await page.goto(BASE + "/", { waitUntil: "load" });
await anim.send("Animation.setPlaybackRate", { playbackRate: 1 / SLOW });
await page.waitForTimeout(2000);

const cdp = await ctx.newCDPSession(page);
const frames = [];
const pending = [];
let t0 = null;
cdp.on("Page.screencastFrame", (f) => {
  cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  if (t0 === null) return;
  const file = `frames/${String(frames.length).padStart(6, "0")}.jpg`;
  frames.push({ file, t: (f.metadata.timestamp - t0) / SLOW });
  pending.push(fs.promises.writeFile(path.join(OUT, file), Buffer.from(f.data, "base64")));
});

const now = () => (Date.now() / 1000 - t0) / SLOW;
const until = async (t) => {
  const d = t - now();
  if (d > 0) await page.waitForTimeout(d * 1000 * SLOW);
};
const scrollWin = (to, dur) =>
  page.evaluate(
    ([to, dur]) =>
      new Promise((r) => {
        const from = scrollY;
        const s = performance.now();
        const e = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
        const f = () => {
          const p = Math.min(1, (performance.now() - s) / (dur * 1000));
          scrollTo(0, from + (to - from) * e(p));
          p < 1 ? requestAnimationFrame(f) : r();
        };
        requestAnimationFrame(f);
      }),
    [to, dur],
  );
const top = (sel) => page.evaluate((sel) => document.querySelector(sel).getBoundingClientRect().top + scrollY, sel);
const box = async (loc) => {
  const b = await loc.first().boundingBox();
  return { x: b.x, y: b.y, w: b.width, h: b.height };
};
let meta = {};
let END = 0;

if (which === "race") {
  // Park on the split comparison before it starts, then let the full 9 s run play.
  const y = await top("#race");
  await page.evaluate((y) => scrollTo(0, y - 1500), y);
  await page.waitForTimeout(800);
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W * DSF, maxHeight: H * DSF });
  t0 = Date.now() / 1000;
  await scrollWin(y + 30, 0.01);
  await until(10.5);
  END = 10.5;
} else if (which === "mapstory") {
  const y = await top("#how");
  const h = await page.evaluate(() => document.querySelector("#how").offsetHeight);
  const at = (p) => y + p * (h - H);
  await page.evaluate((v) => scrollTo(0, v), at(0.05));
  await page.waitForTimeout(1500);
  meta.card = await box(page.getByText("Demo console").locator("xpath=ancestor::div[contains(@class,'rounded')][1]"));
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W * DSF, maxHeight: H * DSF });
  t0 = Date.now() / 1000;
  // Each step animates on its own once scroll reaches it; time the steps to the
  // narration: spread out (0.3 s), one live map (7.0 s), people and danger (11.4 s).
  await scrollWin(at(0.25), 0.35);
  await until(7.0);
  await scrollWin(at(0.48), 0.35);
  await until(11.4);
  await scrollWin(at(0.72), 0.35);
  await until(20.5);
  END = 20.5;
} else if (which === "vitals") {
  const y = await top("#vitals");
  await page.evaluate((y) => scrollTo(0, y - 1200), y);
  await page.waitForTimeout(800);
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W * DSF, maxHeight: H * DSF });
  t0 = Date.now() / 1000;
  await scrollWin(y - 40, 0.01);
  await page.waitForTimeout(200);
  meta.section = await box(page.locator("#vitals"));
  await until(9);
  END = 9;
}

await cdp.send("Page.stopScreencast");
await Promise.all(pending);
fs.writeFileSync(path.join(OUT, "frames.json"), JSON.stringify({ W, H, DSF, END, meta, frames }));
console.log(which, "frames", frames.length, "meta", JSON.stringify(meta));
await browser.close();
