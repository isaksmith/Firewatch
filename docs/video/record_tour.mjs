// Records the site in use for the tour cut, one segment per feature, with a drawn cursor so viewers can follow.
// Usage: node record_tour.mjs <segment...>   (segments below; "all" records every one in order)
// Needs the backend on 8000 and the frontend on 5173. The scenario and satellite replay segments reset sample data.
import { launch, startCapture, sleep } from "./capture.mjs";

const API = "http://127.0.0.1:8000/api";
const SITE = "http://localhost:5173";

const CURSOR = () => {
  const install = () => {
    if (document.getElementById("fw-cursor")) return;
    const c = document.createElement("div");
    c.id = "fw-cursor";
    c.innerHTML = `<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8 18.5 L12.5 28 L16.5 26.2 L12 17 L20 17 Z" fill="#fff" stroke="#050607" stroke-width="2" stroke-linejoin="round"/></svg>`;
    Object.assign(c.style, { position: "fixed", left: "-50px", top: "-50px", zIndex: 2147483647, pointerEvents: "none", filter: "drop-shadow(0 2px 3px rgba(0,0,0,.6))" });
    document.documentElement.appendChild(c);
    addEventListener("mousemove", (e) => { c.style.left = e.clientX - 2 + "px"; c.style.top = e.clientY - 2 + "px"; }, true);
    addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      Object.assign(r.style, { position: "fixed", left: e.clientX - 18 + "px", top: e.clientY - 18 + "px", width: "36px", height: "36px", borderRadius: "50%",
        border: "3px solid #FFB21A", zIndex: 2147483646, pointerEvents: "none", transition: "transform .45s ease-out, opacity .45s ease-out" });
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = "scale(1.8)"; r.style.opacity = "0"; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === "loading") addEventListener("DOMContentLoaded", install); else install();
};

let pos = { x: 640, y: 360 };
async function moveTo(page, x, y, ms = 650) {
  const steps = Math.max(1, Math.round(ms / 16)), from = { ...pos };
  for (let i = 1; i <= steps; i++) {
    const e = 0.5 - Math.cos((Math.PI * i) / steps) / 2;
    await page.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e);
    await sleep(16);
  }
  pos = { x, y };
}
async function centre(loc) {
  await loc.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
  const b = await loc.boundingBox({ timeout: 5000 });
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}
async function hover(page, loc, ms) { const c = await centre(loc.first()); await moveTo(page, c.x, c.y, ms); }
async function click(page, loc, { ms = 650, pause = 250 } = {}) {
  const c = await centre(loc.first());
  await moveTo(page, c.x, c.y, ms);
  await sleep(pause);
  await page.mouse.down(); await sleep(70); await page.mouse.up();
}
async function scroll(page, x, y, dy, ms = 1500) {
  await moveTo(page, x, y, 400);
  const steps = Math.round(ms / 40);
  for (let i = 0; i < steps; i++) { await page.mouse.wheel(0, dy / steps); await sleep(40); }
}
async function drag(page, from, to, ms = 2000) {
  await moveTo(page, from.x, from.y);
  await page.mouse.down();
  await moveTo(page, to.x, to.y, ms);
  await page.mouse.up();
}
async function type(loc, text) { await loc.pressSequentially(text, { delay: 55 }); }
const api = (path, method = "GET") => fetch(`${API}${path}`, { method }).then((r) => r.json());

async function session(name, url, body) {
  const { browser, page } = await launch();
  await page.addInitScript(CURSOR);
  await page.goto(`${SITE}${url}`, { waitUntil: "networkidle" });
  await sleep(2500);
  pos = { x: 640, y: 360 };
  await page.mouse.move(pos.x, pos.y);
  const cap = await startCapture(page, `tour-${name}`);
  await sleep(600);
  try {
    await body(page, cap.mark);
  } finally {
    await sleep(800);
    await cap.stop();
    await browser.close();
  }
}

const fireId = async () => (await api("/scenario/cottonwood-creek")).events?.[0]?.id;

const SEGMENTS = {
  // Statewide queue and map: hover, tabs, layers, suppressed footer.
  console: () => session("console", "/", async (page, mark) => {
    mark("start");
    const cards = page.locator("aside li, aside button").filter({ hasText: /mi .* of / });
    for (let i = 1; i <= 3; i++) { await hover(page, cards.nth(i), 700); await sleep(900); }
    mark("tabs");
    await click(page, page.getByRole("button", { name: /^Escalate/i })); await sleep(1600);
    await click(page, page.getByRole("button", { name: /^Suppressed/i })); await sleep(2600);
    await click(page, page.getByRole("button", { name: /^Active/i })); await sleep(1200);
    mark("layers");
    await click(page, page.getByRole("button", { name: /layers/i })); await sleep(1500);
    for (const name of ["Flint Hills", "Lines under wind", "Dry air grid", "NWS alerts"]) {
      const box = page.getByText(name, { exact: false }).first();
      if (await box.count()) { await click(page, box, { ms: 450 }); await sleep(1100); }
    }
    await sleep(1200);
    await click(page, page.getByRole("button", { name: /layers/i })); await sleep(800);
    mark("end");
  }),

  // Satellite replay: real detections flow through the scorer, statewide.
  replay: () => session("replay", "/", async (page, mark) => {
    mark("start");
    await click(page, page.getByRole("button", { name: /satellite replay/i }));
    mark("running");
    await moveTo(page, 1250, 700, 800);
    await sleep(40000);
    mark("end");
  }),

  // One satellite alert's drawer, scrolled section by section.
  drawer: () => session("drawer", "/", async (page, mark) => {
    mark("start");
    await click(page, page.locator("aside").getByText(/Natoma/).first()); await sleep(2500);
    mark("open");
    const how = page.getByText(/how we got here/i).first();
    if (await how.count()) { await click(page, how); await sleep(3500); mark("how"); }
    for (let i = 0; i < 7; i++) { await scroll(page, 1110, 450, 380, 1300); await sleep(1500); }
    mark("end");
  }),

  // The packet fire, with the drawer following the response and its texts.
  scenario: () => session("scenario", "/", async (page, mark) => {
    await api("/scenario/cottonwood-creek/stop", "POST").catch(() => {});
    mark("start");
    await click(page, page.getByRole("button", { name: /run scenario/i }));
    for (let i = 0; i < 60 && !(await api("/scenario/cottonwood-creek")).running; i++) await sleep(250);
    let last = null, scrolledResponse = false, scrolledTexts = false;
    while (true) {
      const st = await api("/scenario/cottonwood-creek");
      if (st.t_min !== last) { mark("t", { t_min: st.t_min }); last = st.t_min; }
      if (!scrolledResponse && last >= 11) { scrolledResponse = true; mark("response"); await scroll(page, 1110, 450, 700, 1500); }
      if (!scrolledTexts && last >= 16) { scrolledTexts = true; mark("texts"); await scroll(page, 1110, 450, 900, 1800); }
      if (!st.running && last !== null && last >= 10) break;
      await sleep(250);
    }
    mark("end");
  }),

  // After the scenario: the 2D forecast slider, then the 3D spread view with a wind override.
  forecast: () => session("forecast", "/", async (page, mark) => {
    const id = await fireId();
    await page.goto(`${SITE}/alerts/${id}`, { waitUntil: "networkidle" }); await sleep(3500);
    mark("start");
    const slider = page.getByLabel("Forecast time");
    const b = await slider.boundingBox();
    await drag(page, { x: b.x + 4, y: b.y + b.height / 2 }, { x: b.x + b.width - 4, y: b.y + b.height / 2 }, 5000);
    await sleep(2000);
    mark("3d");
    await click(page, page.getByRole("link", { name: /3D view/i })); await sleep(9000);
    mark("override");
    await click(page, page.getByText("Override wind")); await sleep(800);
    const ranges = page.locator("input[type=range]");
    const from = await ranges.nth(1).boundingBox();
    const y = from.y + from.height / 2;
    await drag(page, { x: from.x + from.width * 0.5, y }, { x: from.x + from.width * 0.36, y }, 2500);
    await sleep(5000);
    mark("orbit");
    await page.keyboard.down("Control");
    await drag(page, { x: 560, y: 420 }, { x: 820, y: 420 }, 4000);
    await page.keyboard.up("Control");
    await sleep(2500);
    mark("end");
  }),

  // Burn log and low data mode.
  burns: () => session("burns", "/", async (page, mark) => {
    mark("start");
    await click(page, page.getByLabel("Burn log")); await sleep(1500);
    const who = page.getByLabel("Who called");
    await click(page, who); await who.fill(""); await type(who, "Dale Hoffman, NE of Coldwater");
    await sleep(600);
    await click(page, page.getByRole("button", { name: /log this burn/i })); await sleep(3000);
    mark("lowdata");
    await click(page, page.getByLabel("Burn log")); await sleep(800);
    await click(page, page.getByRole("switch", { name: /low data/i })); await sleep(4500);
    await click(page, page.getByRole("switch", { name: /low data/i })); await sleep(3000);
    mark("end");
  }),

  // The public board: a resident starts a smoke report (not sent).
  board: () => session("board", "/board", async (page, mark) => {
    mark("start");
    await click(page, page.getByRole("button", { name: /^smoke$/i })); await sleep(700);
    const box = page.getByPlaceholder(/what do you see/i);
    await click(page, box);
    await type(box, "Grey smoke past the grain elevator on County Line Road, moving north");
    await sleep(800);
    await click(page, page.getByText(/attach my location/i)); await sleep(2500);
    await scroll(page, 900, 600, 500, 1500); await sleep(2500);
    mark("end");
  }),

  // The region planner: a plot's reasons, fewer plots, a budget, then another county.
  planner: () => session("planner", "/planner", async (page, mark) => {
    await sleep(4000);
    mark("start");
    await scroll(page, 190, 500, 1600, 1800);
    await click(page, page.locator("aside button").filter({ hasText: /^S1/ }));
    await sleep(4500);
    await scroll(page, 190, 500, -4000, 1500);
    await sleep(800);
    mark("plots");
    const plots = page.getByLabel("Plots", { exact: true });
    await click(page, plots); await plots.fill(""); await type(plots, "5"); await sleep(6000);
    mark("budget");
    await click(page, page.getByRole("button", { name: "Budget" })); await sleep(800);
    const budget = page.getByLabel(/Budget \$/);
    await click(page, budget); await budget.fill(""); await type(budget, "25000"); await sleep(6000);
    mark("county");
    await page.locator("aside select").first().selectOption({ label: "Barber County" }).catch(async () => {
      await page.locator("aside select").first().selectOption({ index: 5 });
    });
    await sleep(12000);
    mark("scroll");
    for (let i = 0; i < 6; i++) { await scroll(page, 190, 500, 450, 1300); await sleep(1600); }
    mark("end");
  }),
};

const names = process.argv.slice(2);
for (const n of names[0] === "all" ? Object.keys(SEGMENTS) : names) {
  console.log(`recording ${n}`);
  try {
    await SEGMENTS[n]();
  } catch (e) {
    console.log(`  ${n} failed: ${e.message.split("\n")[0]}`);
  }
}
