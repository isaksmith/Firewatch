// Segment 2: the false-alarm trap. Suppressed tab ("likely prescribed burn"), then the Burn log.
// State changed: logs two permitted burns (Henderson, Ortiz; called in at 10:40 and 11:15 am on Tue Mar 17) in the
// scratch database via POST /api/burns. The next scenario run clears sample burns again.
import * as L from './lib.mjs';
const burns = [
  { caller: 'Henderson', label: 'Henderson pasture burn', lat: 37.36, lon: -99.3, start: '2026-03-17T16:00:00Z', end: '2026-03-17T22:00:00Z', called_in: '2026-03-17T15:40:00Z' },
  { caller: 'Ortiz', label: 'Ortiz pasture burn', lat: 37.25, lon: -99.5, start: '2026-03-17T16:30:00Z', end: '2026-03-17T22:30:00Z', called_in: '2026-03-17T16:15:00Z' },
];
const existing = await (await fetch(`${L.API}/burns`)).json();
const seeded = [];
for (const b of burns) if (!existing.burns.some((x) => x.caller === b.caller)) { const r = await fetch(`${L.API}/burns`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(b) }); seeded.push(r.status); }
const rec = await L.open('falsealarm');
const p = rec.page;
await p.goto(L.APP + '/'); await p.waitForSelector('select'); await L.sleep(2500);
await L.start(rec); await L.sleep(1000);
L.mark(rec, 'start');
const ok = await L.safely('falsealarm', async () => {
  await L.click(rec, p.getByText(/^Suppressed/i).first());
  L.mark(rec, 'suppressed_tab');
  await L.sleep(3500);
  await L.click(rec, p.getByRole('button', { name: /burn log/i }).first());
  L.mark(rec, 'burn_log');
  await L.sleep(2500);
  await L.click(rec, p.getByPlaceholder('Henderson'));
  await p.getByPlaceholder('Henderson').pressSequentially('Henderson', { delay: 55 });
  L.mark(rec, 'typed_caller');
  await L.sleep(1500);
  const h = p.getByText(/Burns on file/i).first();
  await h.scrollIntoViewIfNeeded();
  await L.wheel(rec, 1100, 500, 300, 10, 45);
  L.mark(rec, 'burns_on_file');
  await L.sleep(4500);
});
await L.finish(rec, { ok, seeded });
