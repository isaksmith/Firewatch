// Segment 3: 3D spread preview. Opens the alert, clicks "3D spread preview", plays the forecast, overrides the wind
// with the sliders, then hides the side panel and orbits. Reads the packet alert from the backend; changes nothing.
import * as L from './lib.mjs';
const rec = await L.open('spread3d', { css: '' });
const p = rec.page;
const s = await L.scenario();
const eid = s.events?.[0]?.id ?? s.fires?.[0]?.event_id;
await p.goto(L.APP + '/'); await p.waitForSelector('select'); await L.sleep(800);
await L.start(rec); await L.sleep(800);
L.mark(rec, 'start');
const setRange = (idx, v) => p.evaluate(([i, val]) => { const el = document.querySelectorAll('input[type=range]')[i]; const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, String(val)); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }, [idx, v]);
const ok = await L.safely('3d', async () => {
  await L.click(rec, p.getByText(/Coldwater/i).first());
  await L.sleep(1500);
  L.mark(rec, 'alert_open');
  await L.click(rec, p.getByText(/3D spread preview/i).first());
  L.mark(rec, 'open3d');
  await p.waitForURL(/\/3d/); await L.sleep(4500);
  L.mark(rec, 'loaded');
  // let it play at 4x
  await L.click(rec, p.getByRole('button', { name: '4×' }));
  L.mark(rec, 'speed4');
  await L.sleep(5500);
  await L.click(rec, p.getByRole('button', { name: /reset/i }));
  L.mark(rec, 'reset');
  await L.sleep(3000);
  // wind override
  await L.click(rec, p.getByText(/override wind/i));
  L.mark(rec, 'override');
  await L.sleep(800);
  for (const v of [56, 40, 25]) { await setRange(0, v); await L.sleep(350); }
  for (const v of [180, 200, 220, 245]) { await setRange(1, v); await L.sleep(350); }
  L.mark(rec, 'wind_set');
  await L.sleep(4000);
  // hide panels, orbit with a right-button drag
  await p.addStyleTag({ content: '.hud.top-6.right-6{display:none!important}' });
  L.mark(rec, 'panel_hidden');
  await L.sleep(500);
  await L.moveTo(rec, 700, 330, 500);
  await p.mouse.down({ button: 'right' });
  for (let i = 1; i <= 70; i++) { await p.mouse.move(700 + i * 5, 330 + i * 0.15); await L.sleep(16); }
  await p.mouse.up({ button: 'right' });
  L.mark(rec, 'orbit');
  await L.sleep(4000);
});
await L.finish(rec, { ok, eid });
