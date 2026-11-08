// Segment 4: community board. Posts a smoke report as a neighbour would and shows it listed, then opens the
// board panel on the dashboard where staff confirm it. State changed: one test post in the scratch database
// (sample mode: any text it triggers is simulated and never reaches a phone).
import * as L from './lib.mjs';
const rec = await L.open('board');
const p = rec.page;
await p.goto(L.APP + '/board'); await L.sleep(1500);
await L.start(rec); await L.sleep(800);
L.mark(rec, 'start');
const ok = await L.safely('board', async () => {
  await L.click(rec, p.getByRole('button', { name: 'SMOKE', exact: false }).first());
  L.mark(rec, 'category');
  await L.click(rec, p.getByLabel('Post text'));
  await p.getByLabel('Post text').pressSequentially('Smoke rising south of the Hutchins pasture, drifting north. Looks like more than a burn pile.', { delay: 55 });
  L.mark(rec, 'typed');
  await L.sleep(700);
  await L.click(rec, p.getByRole('button', { name: /^post$/i }));
  L.mark(rec, 'posted');
  await L.sleep(2500);
  await L.wheel(rec, 640, 450, 420, 14, 45);
  L.mark(rec, 'scrolled');
  await L.sleep(1500);
  const conf = p.getByRole('button', { name: /i see it|see it|seeing/i }).first();
  if (await conf.count()) { await L.click(rec, conf); L.mark(rec, 'confirm'); await L.sleep(2500); }
  else L.mark(rec, 'no_confirm_button');
});
await L.finish(rec, { ok });
