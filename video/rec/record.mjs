// Records the Part B website take: one continuous real-time run through the
// real Swarm web app, captured with the CDP screencast at 60 fps.
// Usage: node rec/record.mjs [baseUrl]
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2] ?? "http://localhost:5317";
const OUT = path.resolve("rec/take");
const W = 1600;
const H = 900;
const DSF = 2;

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(path.join(OUT, "frames"), { recursive: true });

const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome-stable",
  headless: true,
  args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist", "--hide-scrollbars", "--force-color-profile=srgb", `--force-device-scale-factor=${DSF}`, `--window-size=${W},${H + 87}`],
});
const ctx = await browser.newContext({ viewport: null });

// Slow-motion capture: page clocks run at 1/SLOW speed so the screencast keeps
// up at 2x resolution; frame timestamps are divided by SLOW afterwards.
const SLOW = 3;
const WALL0 = Date.now();
await ctx.addInitScript(([SLOW, WALL0]) => {
  const pn = performance.now.bind(performance);
  const dn = Date.now;
  performance.now = () => pn() / SLOW;
  Date.now = () => WALL0 + (dn() - WALL0) / SLOW;
  const raf = window.requestAnimationFrame.bind(window);
  // Ignore the frame timestamp: the CSS playback rate also scales the
  // document timeline it comes from. performance.now() is the one clock.
  window.requestAnimationFrame = (cb) => raf(() => cb(performance.now()));
  const st = window.setTimeout.bind(window);
  const si = window.setInterval.bind(window);
  window.setTimeout = (f, d = 0, ...a) => st(f, d * SLOW, ...a);
  window.setInterval = (f, d = 0, ...a) => si(f, d * SLOW, ...a);
}, [SLOW, WALL0]);

// Synthetic cursor drawn into the page so the screencast captures it.
await ctx.addInitScript(() => {
  const install = () => {
    if (document.getElementById("__cur")) return;
    const s = document.createElement("style");
    s.textContent = `
      #__cur{position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transition:opacity .35s ease;will-change:transform}
      #__cur svg{display:block;filter:drop-shadow(0 2px 3px rgb(0 0 0/.35))}
      .__rip{position:fixed;z-index:2147483646;pointer-events:none;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
        border:2.5px solid #FF5A1F;background:rgb(255 90 31/.18);animation:__rip .55s ease-out forwards}
      @keyframes __rip{from{transform:scale(.2);opacity:1}to{transform:scale(1.25);opacity:0}}
      html{scroll-behavior:auto!important}`;
    document.head.appendChild(s);
    const c = document.createElement("div");
    c.id = "__cur";
    c.innerHTML = `<svg width="26" height="30" viewBox="0 0 26 30"><path d="M3 2 L3 24 L8.6 18.8 L12.4 27.4 L16.2 25.8 L12.5 17.4 L20 17.4 Z" fill="#151515" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>`;
    const st = JSON.parse(sessionStorage.getItem("__cur") ?? '{"x":1300,"y":760,"o":0}');
    c.style.transform = `translate(${st.x - 3}px,${st.y - 2}px)`;
    c.style.opacity = st.o;
    document.body.appendChild(c);
    window.__curState = st;
    document.addEventListener("mousemove", (e) => {
      c.style.transform = `translate(${e.clientX - 3}px,${e.clientY - 2}px)`;
      window.__curState.x = e.clientX;
      window.__curState.y = e.clientY;
      sessionStorage.setItem("__cur", JSON.stringify(window.__curState));
    }, true);
    document.addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      r.className = "__rip";
      r.style.left = e.clientX + "px";
      r.style.top = e.clientY + "px";
      document.body.appendChild(r);
      setTimeout(() => r.remove(), 700);
    }, true);
    window.__curShow = (o) => {
      c.style.opacity = o;
      window.__curState.o = o;
      sessionStorage.setItem("__cur", JSON.stringify(window.__curState));
    };
  };
  if (document.body) install();
  else document.addEventListener("DOMContentLoaded", install);
});

const page = await ctx.newPage();
const anim = await ctx.newCDPSession(page);
await anim.send("Animation.enable");
const slowCss = () => anim.send("Animation.setPlaybackRate", { playbackRate: 1 / SLOW }).catch(() => {});
page.on("framenavigated", (f) => f === page.mainFrame() && slowCss());
page.on("load", slowCss);
await slowCss();
await page.goto(BASE + "/", { waitUntil: "load" });
await page.evaluate(() => sessionStorage.clear());
await page.reload({ waitUntil: "load" });
await page.waitForTimeout(2500);

// ---- capture ----
const cdp = await ctx.newCDPSession(page);
const frames = [];
let t0 = null;
const pending = [];
cdp.on("Page.screencastFrame", (f) => {
  cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
  if (t0 === null) return;
  const i = frames.length;
  const file = `frames/${String(i).padStart(6, "0")}.jpg`;
  frames.push({ file, t: (f.metadata.timestamp - t0) / SLOW });
  pending.push(fs.promises.writeFile(path.join(OUT, file), Buffer.from(f.data, "base64")));
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: W * DSF, maxHeight: H * DSF });
await page.waitForTimeout(300);

const wall0 = Date.now() / 1000;
t0 = wall0;
const now = () => (Date.now() / 1000 - wall0) / SLOW;
const sleep = (s) => page.waitForTimeout(s * 1000 * SLOW);
const until = async (t) => {
  const d = t - now();
  if (d > 0) await sleep(d);
};
const events = [];
const mark = (name, extra = {}) => { events.push({ t: +now().toFixed(3), name, ...extra }); if (!name.startsWith("rect")) console.log(now().toFixed(2), name); };

let cur = { x: 1300, y: 760 };
const ease = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
async function moveTo(x, y, dur = 0.9) {
  const from = { ...cur };
  const start = now();
  // Slight arc so the path reads as a hand movement, not a ruler line.
  const nx = -(y - from.y) * 0.12;
  const ny = (x - from.x) * 0.12;
  for (;;) {
    const p = Math.min(1, (now() - start) / dur);
    const e = ease(p);
    const arc = Math.sin(Math.PI * e);
    await page.mouse.move(from.x + (x - from.x) * e + nx * arc, from.y + (y - from.y) * e + ny * arc);
    if (p >= 1) break;
    await page.waitForTimeout(12 * SLOW);
  }
  cur = { x, y };
}
async function center(selector, opts = {}) {
  const loc = (typeof selector === "string" ? page.locator(selector) : selector).first();
  await loc.waitFor({ state: "visible", timeout: 10000 });
  const b = await loc.boundingBox();
  return { x: b.x + b.width * (opts.fx ?? 0.5), y: b.y + b.height * (opts.fy ?? 0.5), box: b };
}
async function rect(name, selector) {
  const loc = (typeof selector === "string" ? page.locator(selector) : selector).first();
  const b = await loc.boundingBox();
  mark("rect:" + name, { box: b && { x: b.x, y: b.y, w: b.width, h: b.height } });
}
async function click(target, dur = 0.9, settle = 0.25) {
  const c = await center(target);
  await moveTo(c.x, c.y, dur);
  await sleep(settle);
  await page.mouse.down();
  await sleep(0.09);
  await page.mouse.up();
  mark("click", { x: c.x, y: c.y });
}
const showCursor = (o) => page.evaluate((o) => window.__curShow?.(o), o);
// Eased window scroll driven inside the page for smoothness.
const scrollWin = (to, dur) =>
  page.evaluate(
    ([to, dur]) =>
      new Promise((r) => {
        const from = scrollY;
        const s = performance.now();
        const e = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
        const f = (t) => {
          const p = Math.min(1, (t - s) / (dur * 1000));
          scrollTo(0, from + (to - from) * e(p));
          p < 1 ? requestAnimationFrame(f) : r();
        };
        requestAnimationFrame(f);
      }),
    [to, dur],
  );
const scrollEl = (selector, to, dur) =>
  page.evaluate(
    ([selector, to, dur]) =>
      new Promise((r) => {
        const el = document.querySelector(selector);
        const from = el.scrollTop;
        const target = to === "end" ? el.scrollHeight - el.clientHeight : to;
        const s = performance.now();
        const e = (p) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
        const f = (t) => {
          const p = Math.min(1, (t - s) / (dur * 1000));
          el.scrollTop = from + (target - from) * e(p);
          p < 1 ? requestAnimationFrame(f) : r();
        };
        requestAnimationFrame(f);
      }),
    [selector, to, dur],
  );

// Scene starts in take seconds, synced to the recorded narration. Mirrors B in src/timeline.ts.
const S = { s7: 0, s8: 10.4, s9: 20.8, s10: 23.2, s11: 26.7, s12: 31.2, s13: 35.6, s14: 40.5, s15: 48.6, s16: 55.5, s17: 63.7, s18: 70.9, end: 75.6 };

// ===== Scene 7: hero hold =====
mark("scene7");
await page.mouse.move(cur.x, cur.y);
await until(S.s8 - 0.2);

// ===== Scene 8: homepage scroll =====
mark("scene8");
await scrollWin(1411, 2.0); // race comparison
mark("race");
await until(S.s8 + 4.0);
await scrollWin(6911, 3.4); // through how-it-works and vitals to advantages
mark("advantages");
await until(S.s8 + 9.0);
await scrollWin(9287 - 900, 1.2); // closing CTA with the mission-start action
await until(S.s9 - 0.3);

// ===== Scene 9: enter mission mode =====
mark("scene9");
await showCursor(1);
const demo = page.getByRole("link", { name: "or start a demo mission" });
await rect("demoLink", demo);
await click(demo, 1.0, 0.2);
await page.waitForURL("**/missions/new");
await until(S.s10);

// ===== Scene 10: create mission =====
mark("scene10");
const result = page.getByRole("button", { name: /418 Elm St/ }).first();
await rect("address", result);
await click(result, 0.55, 0.1);
await until(S.s10 + 1.4);
const quake = page.getByRole("button", { name: "Earthquake" });
await rect("types", page.getByRole("button", { name: "Structural collapse" }));
await click(quake, 0.55, 0.1);
await until(S.s10 + 2.4);
const cont = page.getByText("Continue to setup");
await rect("continue", cont);
await click(cont, 0.6, 0.1);
await page.waitForURL("**/setup");
await until(S.s11);

// ===== Scene 11: launch =====
mark("scene11");
await sleep(0.1);
await rect("plan", page.locator("main, .relative.min-w-0.flex-1").first());
const droneList = page.locator("aside").getByText("D1", { exact: true }).locator("xpath=ancestor::div[contains(@class,'overflow-hidden')][1]");
await rect("drones", droneList);
const d1 = await center(page.locator("aside").getByText("D1", { exact: true }).first());
const d4 = await center(page.locator("aside").getByText("D4", { exact: true }).first());
await moveTo(d1.x + 120, d1.y, 0.5);
await moveTo(d4.x + 120, d4.y, 0.6);
await until(S.s11 + 1.0);
const launch = page.getByText("Launch 4 drones");
await rect("launch", launch);
await click(launch, 0.6, 0.15);
await page.waitForURL("**/live");
await until(S.s12);

// ===== Scene 12: dashboard overview =====
mark("scene12");
await sleep(0.2);
await moveTo(1590, 470, 0.8);
await showCursor(0);
await rect("map", page.getByAltText("Point cloud of the ground floor"));
await rect("feeds", page.getByAltText("D1 camera").locator("xpath=ancestor::div[contains(@class,'overflow-x-auto')][1]"));
await rect("findings", page.getByRole("tablist"));
await until(S.s13);

// ===== Scene 13: four feeds =====
mark("scene13");
await showCursor(1);
for (const [id, at] of [["D1", 0.6], ["D3", 1.7], ["D4", 2.8], ["D2", 3.9]]) {
  const feed = page.getByAltText(`${id} camera`);
  await rect("feed" + id, feed);
  await click(feed, 0.55, 0.1);
  await until(S.s13 + at + 0.3);
}
await until(S.s14);

// ===== Scene 14: shared 3D map =====
mark("scene14");
for (const [id, at] of [["D1", 0.8], ["D3", 2.1], ["D2", 3.5]]) {
  const m = page.getByRole("button", { name: `Select ${id}` });
  await rect("marker" + id, m);
  await click(m, 0.7, 0.15);
  await until(S.s14 + at + 0.4);
}
const coverage = page.getByText("mapped, 2 rooms left");
await rect("coverage", coverage.locator("xpath=ancestor::div[contains(@class,'rounded-lg')][1]"));
const cv = await center(coverage);
await until(S.s14 + 5.3);
await moveTo(cv.x + 40, cv.y + 18, 0.8);
await until(S.s15);

// ===== Scene 15: survivor detection =====
mark("scene15");
const person = page.getByText("Person on floor", { exact: true }).locator("xpath=ancestor::div[contains(@class,'flex-col')][1]");
await rect("person", person);
await rect("snapshot", page.getByAltText("Snapshot of the person from D2").locator("xpath=.."));
await rect("vitals", page.getByText("Breathing", { exact: true }).locator("xpath=../.."));
const pt = await center(page.getByText("Person on floor", { exact: true }));
await moveTo(pt.x + 60, pt.y, 0.8);
await until(S.s15 + 1.9);
const pin = page.getByRole("button", { name: "Person on floor" });
await rect("personPin", pin);
const pc = await center(pin);
await moveTo(pc.x + 14, pc.y + 10, 0.9);
await until(S.s15 + 4.2);
const br = await center(page.getByText("Breathing", { exact: true }));
await moveTo(br.x + 30, br.y + 22, 0.9);
await until(S.s16);

// ===== Scene 16: hazards and obstacles =====
mark("scene16");
const listSel = "[role=tablist] + div";
await rect("findingsList", page.locator(listSel));
const lc = await center(page.locator(listSel), { fy: 0.6 });
await moveTo(lc.x + 40, lc.y, 0.7);
await until(S.s16 + 1.1);
await scrollEl(listSel, "end", 2.6);
mark("findingsScrolled");
for (const t of ["Closed door to garage", "Passage blocked by debris", "Gas cylinder"]) await rect(t, page.getByText(t, { exact: true }).locator("xpath=ancestor::button[1]"));
await until(S.s17);

// ===== Scene 17: crew communication =====
mark("scene17");
await scrollEl(listSel, 0, 0.9);
await until(S.s17 + 1.0);
const send = page.getByRole("button", { name: "Send route to crew" });
await rect("send", send);
const sc = await center(send);
await moveTo(sc.x, sc.y, 0.8);
await until(S.s17 + 3.6);
const crew = page.getByText("Crew channel", { exact: true }).locator("xpath=../..");
await rect("crew", crew);
const cm = await center(page.getByText(/Go left from the front door/));
await moveTo(cm.x + 60, cm.y + 10, 0.9);
await until(S.s18);

// ===== Scene 18: handoff =====
mark("scene18");
await moveTo(1590, 470, 0.8);
await showCursor(0);
await until(S.end + 0.3);
mark("end");

await cdp.send("Page.stopScreencast");
await Promise.all(pending);
fs.writeFileSync(path.join(OUT, "frames.json"), JSON.stringify({ W, H, DSF, frames }, null, 0));
fs.writeFileSync(path.join(OUT, "events.json"), JSON.stringify(events, null, 1));
console.log("frames", frames.length, "span", frames.at(-1).t.toFixed(2));
await browser.close();
