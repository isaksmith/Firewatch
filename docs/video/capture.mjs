// Shared browser capture for the story video. Playwright's recordVideo ignores deviceScaleFactor,
// so frames come from the CDP screencast at 1920x1080 and are timed by their own timestamps.
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

export const BUILD = path.resolve(path.dirname(new URL(import.meta.url).pathname), "build", "rec");
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function launch() {
  const browser = await chromium.launch({ args: ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5 });
  return { browser, page };
}

export async function startCapture(page, name) {
  const dir = path.join(BUILD, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const cdp = await page.context().newCDPSession(page);
  const frames = [];
  const marks = [];
  cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
    const f = path.join(dir, `f${String(frames.length).padStart(5, "0")}.jpg`);
    fs.writeFileSync(f, Buffer.from(data, "base64"));
    frames.push({ f, ts: metadata.timestamp });
    await cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080 });
  return {
    mark: (what, extra = {}) => marks.push({ what, ts: Date.now() / 1000, ...extra }),
    async stop() {
      await cdp.send("Page.stopScreencast");
      fs.writeFileSync(path.join(BUILD, `${name}.json`), JSON.stringify({ frames, marks }));
      const span = frames.at(-1).ts - frames[0].ts;
      console.log(`${name}: ${frames.length} frames over ${span.toFixed(1)} s`);
    },
  };
}
