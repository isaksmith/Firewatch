// Records the sensor node explorer full-frame: orbit the rich node on its pole band, then explode
// the bare enclosure and orbit again. Needs `python sensors/viewer/serve.py` on 5174.
import { launch, startCapture, sleep } from "./capture.mjs";

const FIT = Number(process.env.FIT || 0.85);

const { browser, page } = await launch();
// fitView re-frames on every explode step, so tighten its margin instead of zooming the camera.
await page.route("**/app.js", async (route) => {
  const res = await route.fetch();
  const body = (await res.text()).replace("radius/Math.sin(angle)*1.15", "radius/Math.sin(angle)*(window.__fit||1.15)");
  await route.fulfill({ response: res, body });
});
await page.addInitScript((fit) => { window.__fit = fit; }, FIT);
await page.goto("http://127.0.0.1:5174/", { waitUntil: "networkidle" });
await page.waitForFunction(() => document.getElementById("loading").hidden, null, { timeout: 30000 });
await page.addStyleTag({ content: `
  .header, .controls, .details, .details-resizer, .stage-heading, .view-toolbar, .stage-footer { display: none !important; }
  .app { display: block !important; height: 100vh !important; }
  .stage { position: fixed !important; inset: 0 !important; width: 100vw !important; height: 100vh !important; }
  .canvas-host { position: absolute !important; inset: 0 !important; }
` });
const set = (id, value) => page.evaluate(([id, value]) => {
  const el = document.getElementById(id);
  el.value = value;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}, [id, value]);
const resetView = async () => { await page.evaluate(() => document.getElementById("reset-view").click()); await sleep(1000); };
const orbit = async (dx, ms) => {
  const y = 420, x0 = 640 - dx / 2, steps = Math.round(ms / 16);
  await page.mouse.move(x0, y);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(x0 + dx * (0.5 - Math.cos((Math.PI * i) / steps) / 2), y);
    await sleep(16);
  }
  await page.mouse.up();
};

await sleep(800);
await resetView();
const cap = await startCapture(page, "viewer");
cap.mark("band");
await sleep(500);
await orbit(360, 7000);
await sleep(800);
await set("mount", "none");
await sleep(2000);
await resetView();
cap.mark("explode");
for (let v = 0; v <= 100; v += 2) { await set("explode", String(v)); await sleep(70); }
await sleep(400);
await orbit(-260, 6000);
await sleep(1000);
cap.mark("end");
await cap.stop();
await browser.close();
