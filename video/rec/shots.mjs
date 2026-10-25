// Captures the README screenshot matrix from the running web app.
// Usage: node rec/shots.mjs [baseUrl]  -> ../docs/screenshots/*.jpg
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.argv[2] ?? "http://localhost:5317";
const OUT = path.resolve("../docs/screenshots");
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  executablePath: "/usr/bin/google-chrome-stable",
  headless: true,
  args: ["--use-angle=vulkan", "--enable-gpu", "--ignore-gpu-blocklist", "--hide-scrollbars", "--force-color-profile=srgb"],
});

async function shoot(page, name) {
  await page.screenshot({ path: path.join(OUT, `${name}.jpg`), type: "jpeg", quality: 78 });
  console.log(name);
}

// Scroll a landing section into view and give its own animation time to finish.
async function section(page, selector, wait, offset = 0) {
  await page.evaluate(
    ([sel, off]) => {
      const el = document.querySelector(sel);
      scrollTo(0, el.getBoundingClientRect().top + scrollY - 68 + off);
    },
    [selector, offset],
  );
  await page.waitForTimeout(wait);
}

async function landing(page, prefix) {
  await page.goto(BASE + "/", { waitUntil: "load" });
  await page.waitForTimeout(1500);
  await shoot(page, `${prefix}-landing`);
  await section(page, "#race", 10500);
  await shoot(page, `${prefix}-race`);
  // The map story is pinned; scroll deep into it so the findings and route show.
  await page.evaluate(() => {
    const el = document.querySelector("#how");
    const r = el.getBoundingClientRect();
    scrollTo(0, r.top + scrollY + (el.offsetHeight - innerHeight) * 0.8);
  });
  await page.waitForTimeout(4000);
  await shoot(page, `${prefix}-map-story`);
  await section(page, "#vitals", 8000);
  await shoot(page, `${prefix}-vitals`);
}

// Desktop
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  await landing(page, "desktop");
  for (const [route, name, wait] of [
    ["/missions/new", "desktop-new-mission", 1200],
    ["/setup", "desktop-setup", 1200],
    ["/live", "desktop-live", 2500],
    ["/fleet", "desktop-fleet", 1200],
    ["/settings/detection", "desktop-detection", 1200],
    ["/settings/edge", "desktop-edge", 1200],
  ]) {
    await page.goto(BASE + route, { waitUntil: "load" });
    await page.waitForTimeout(wait);
    await shoot(page, name);
  }
  await ctx.close();
}

// Phone
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  await landing(page, "phone");
  await page.goto(BASE + "/live", { waitUntil: "load" });
  await page.waitForTimeout(2500);
  await shoot(page, "phone-live");
  await ctx.close();
}

await browser.close();
