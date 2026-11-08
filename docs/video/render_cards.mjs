// Renders the HTML cards build_video.py writes (captions, chips, composites) to 1920x1080 PNGs.
// Usage: node render_cards.mjs cards.json   where cards.json is [{ out, html, transparent }].
import { chromium } from "playwright";
import fs from "node:fs";

const cards = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
for (const c of cards) {
  await page.setContent(c.html, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: c.out, omitBackground: !!c.transparent });
}
await browser.close();
console.log(`rendered ${cards.length} cards`);
