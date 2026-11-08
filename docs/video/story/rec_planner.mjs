// Segment 5: FireNode planner. Reads only: switches between plots-count and budget, changes the plot count.
import * as L from './lib.mjs';
const rec = await L.open('planner');
const p = rec.page;
await p.goto(L.APP + '/planner'); await L.sleep(3500);
await L.start(rec); await L.sleep(1500);
L.mark(rec, 'start');
const ok = await L.safely('planner', async () => {
  await L.moveTo(rec, 1300, 280, 900); await L.sleep(1500);
  L.mark(rec, 'map');
  const plots = p.locator('input').first();
  await L.click(rec, plots);
  await plots.press('Control+a'); await plots.pressSequentially('20', { delay: 55 });
  L.mark(rec, 'plots20');
  await L.sleep(3500);
  await plots.press('Control+a'); await plots.pressSequentially('10', { delay: 55 });
  L.mark(rec, 'plots10');
  await L.sleep(2500);
  await L.wheel(rec, 180, 500, 420, 14, 45);
  L.mark(rec, 'scroll_results');
  await L.sleep(3000);
});
await L.finish(rec, { ok });
