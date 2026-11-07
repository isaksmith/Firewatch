// Records the console while the Cottonwood Creek replay runs, logging the scenario clock so
// build_video.py can cut shots by scenario minute. Needs the backend on 8000 and the frontend on 5173.
import { launch, startCapture, sleep } from "./capture.mjs";

const API = "http://127.0.0.1:8000/api";
const SLUG = process.argv[2] || "cottonwood-creek";
const SECONDS_PER_MINUTE = process.argv[3] || "1.5";

const { browser, page } = await launch();
await page.goto("http://localhost:5173/", { waitUntil: "networkidle" });
await sleep(3000);
const cap = await startCapture(page, "console");
await sleep(3000);
await fetch(`${API}/scenario/${SLUG}/run?seconds_per_minute=${SECONDS_PER_MINUTE}`, { method: "POST" });
let last = null;
while (true) {
  const st = await (await fetch(`${API}/scenario/${SLUG}`)).json();
  if (st.t_min !== last) { cap.mark("t", { t_min: st.t_min }); last = st.t_min; }
  if (!st.running && last !== null && last >= 10) break;
  await sleep(250);
}
await sleep(5000);
await cap.stop();
await browser.close();
