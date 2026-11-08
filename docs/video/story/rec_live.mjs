// Segment 1: the live scenario. Picks "Packet: line fault", runs it at 3 s per scenario minute, simulates the chief
// replying PAGE and three volunteers replying R, opens the alert and scrolls to Texts, lets the run finish.
// State changed: runs the scenario on the backend (replaces earlier scenario events in the scratch database) and
// sends simulated texts (sample mode: they never reach a phone).
import * as L from './lib.mjs';

const SPM = 3;
const rec = await L.open('live');
const p = rec.page;
const log = {};
await p.route('**/api/scenario/*/run', (r) => r.continue({ url: r.request().url().split('?')[0] + `?seconds_per_minute=${SPM}` }));
await p.goto(L.APP + '/');
await p.waitForSelector('select');
await L.sleep(1500);
await L.start(rec);
await L.sleep(1200);
L.mark(rec, 'start');
const ok = await L.safely('live', async () => {
  const sel = p.locator('select').first();
  await L.click(rec, sel); // opens the native list in a real browser; headless just focuses it
  await sel.selectOption('cottonwood-creek-packet');
  L.mark(rec, 'picked');
  await L.sleep(1800);
  await L.click(rec, p.getByText(/run scenario/i));
  L.mark(rec, 'run');
  // scenario clock vs wall time
  const t0wall = Date.now();
  let sentPage = false, sentR = 0, openedAlert = false, scrolledTexts = false, i = 0;
  const readers = [[L.PEOPLE.sam, 8.5], [L.PEOPLE.kelsey, 10], [L.PEOPLE.mike, 12]];
  for (;;) {
    const s = await L.scenario();
    const t = s.t_min ?? 0;
    if (s.running === false && Date.now() - t0wall > 8000) break;
    if (s.running) L.mark(rec, 't', { t_min: Math.round(t * 10) / 10, texts: s.texts_sent });
    if (!openedAlert && t >= 1) {
      openedAlert = true;
      L.mark(rec, 'open_alert');
      await L.click(rec, p.getByText(/NW of Coldwater/i).first());
      await L.sleep(1200);
      L.mark(rec, 'alert_opened');
    }
    if (!sentPage && t >= 6.5) { sentPage = true; L.mark(rec, 'chief_page', { t_min: t }); log.page = await L.sms(L.PEOPLE.chief, 'PAGE'); }
    if (sentPage && sentR < readers.length && t >= readers[sentR][1]) { const [who] = readers[sentR]; L.mark(rec, 'volunteer_R', { t_min: t, who }); (log.r ||= []).push(await L.sms(who, 'R')); sentR++; }
    if (!scrolledTexts && t >= 13) {
      scrolledTexts = true;
      L.mark(rec, 'scroll_texts');
      const box = await p.evaluate(() => { const els = [...document.querySelectorAll('*')].filter((e) => e.scrollHeight > e.clientHeight + 40 && ['auto', 'scroll'].includes(getComputedStyle(e).overflowY) && e.getBoundingClientRect().left > 700); const e = els.sort((a, b) => b.scrollHeight - a.scrollHeight)[0]; if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; });
      log.drawerBox = box;
      if (box) {
        for (let k = 0; k < 40; k++) {
          const top = await p.evaluate(() => { const h = [...document.querySelectorAll('h1,h2,h3,div,span')].filter((e) => e.childElementCount === 0 && /^texts$/i.test(e.textContent.trim())).pop(); return h ? h.getBoundingClientRect().top : null; });
          if (top !== null && top < 330) break;
          await L.wheel(rec, box.x, box.y, 120, 6, 45);
        }
      }
      L.mark(rec, 'texts_visible');
    }
    await L.sleep(500);
    if (++i > 600) break;
  }
  L.mark(rec, 'run_end');
  await L.sleep(3500);
  log.final = await L.scenario();
});
await L.finish(rec, { log, ok });
