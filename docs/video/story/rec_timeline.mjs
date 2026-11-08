// Segment 6: the results strip after the live run finished: Today lane vs Firewatch lane, worst case at first truck.
// Reads only. Must run after rec_live.mjs (it shows that run's final state, so nothing is stale).
import * as L from './lib.mjs';
const rec = await L.open('timeline');
const p = rec.page;
await p.goto(L.APP + '/'); await p.waitForSelector('select'); await L.sleep(1000);
await L.start(rec); await L.sleep(800);
L.mark(rec, 'start');
const ok = await L.safely('timeline', async () => {
  await p.locator('select').first().selectOption('cottonwood-creek-packet');
  await L.sleep(2500);
  L.mark(rec, 'strip_visible');
  const s = await L.scenario();
  L.mark(rec, 'state', { t_min: s.t_min, running: s.running });
  await L.moveTo(rec, 330, 40, 700);               // along the Today lane
  await L.moveTo(rec, 1120, 40, 1400);
  L.mark(rec, 'today_lane');
  await L.sleep(900);
  await L.moveTo(rec, 330, 64, 800);               // along the Firewatch lane
  await L.moveTo(rec, 760, 64, 1500);
  L.mark(rec, 'firewatch_lane');
  await L.sleep(900);
  await L.moveTo(rec, 1010, 130, 900);             // the worst-case box
  L.mark(rec, 'worst_case');
  await L.sleep(3500);
});
await L.finish(rec, { ok });
