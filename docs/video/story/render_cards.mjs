// Render HTML cards to 1920x1080 PNGs. Usage: node render_cards.mjs build/cards/jobs.json
// jobs.json: [{ "out": "path.png", "html": "<html>...", "transparent": true }]. Images are inlined as data URIs
// by the caller (file:// URLs do not load from setContent).
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(process.env.HOME, 'Library/Caches/ms-playwright');
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
for (const j of jobs) {
  await page.setContent(j.html, { waitUntil: 'load' });
  await page.evaluate(() => document.fonts.ready);
  fs.mkdirSync(path.dirname(j.out), { recursive: true });
  await page.screenshot({ path: j.out, omitBackground: !!j.transparent });
}
await browser.close();
console.log('rendered', jobs.length, 'cards');
