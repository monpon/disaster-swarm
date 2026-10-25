import { chromium } from "playwright";
const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome-stable", headless: true, args: ["--use-angle=vulkan","--enable-gpu","--ignore-gpu-blocklist","--hide-scrollbars"] });
const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
await page.goto("http://localhost:5317/", { waitUntil: "load" }); await page.waitForTimeout(1000);
console.log(await page.evaluate(() => ({ H: document.documentElement.scrollHeight,
  sections: [...document.querySelectorAll("body section, body [id]")].map(s => ({ tag: s.tagName, id: s.id, top: Math.round(s.getBoundingClientRect().top + scrollY), h: Math.round(s.offsetHeight), text: s.innerText.slice(0, 50).replace(/\n/g," | ") })) })));
for (const y of [0]) {}
await browser.close();
