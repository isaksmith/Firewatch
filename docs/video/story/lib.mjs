// Shared recorder: Chromium + CDP screencast at 1280x720 CSS px, DSF 1.5, a drawn cursor, named marks.
// Every recorder writes build/rec/<name>.mp4 (1920x1080, 30 fps, constant) and build/rec/<name>.json (marks).
import { chromium } from 'playwright-core';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REC = path.join(HERE, 'build', 'rec');
export const APP = process.env.FW_APP || 'http://localhost:5181';
export const API = process.env.FW_API || 'http://127.0.0.1:8031/api';
export const FFMPEG = '/opt/homebrew/bin/ffmpeg';
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(process.env.HOME, 'Library/Caches/ms-playwright');

const CURSOR = `(() => {
  const mk = () => {
    if (document.getElementById('fw-cur')) return;
    const st = document.createElement('style');
    st.textContent = '#fw-cur{position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px);filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}.fw-rip{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;border-radius:50%;border:3px solid #ff5a36;animation:fwrip .55s ease-out forwards}@keyframes fwrip{to{transform:scale(4);opacity:0}}';
    document.documentElement.appendChild(st);
    const c = document.createElement('div'); c.id = 'fw-cur';
    c.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M3 2 L3 18 L7.5 14 L10.5 21 L13 20 L10 13 L16 13 Z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', (e) => { c.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px)'; }, true);
    addEventListener('mousedown', (e) => { const r = document.createElement('div'); r.className = 'fw-rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'; document.documentElement.appendChild(r); setTimeout(() => r.remove(), 700); }, true);
  };
  if (document.documentElement) mk(); else document.addEventListener('DOMContentLoaded', mk);
  addEventListener('DOMContentLoaded', mk);
})();`;

/** Open a recorder. opts.css is injected into every page (bypassCSP is on). */
export async function open(name, opts = {}) {
  fs.mkdirSync(REC, { recursive: true });
  const dir = path.join(REC, name + '-frames');
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch({ headless: true, channel: opts.channel, args: ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', '--hide-scrollbars'] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5, bypassCSP: true });
  await ctx.addInitScript(() => { try { localStorage.setItem('fw.lowData', '0'); } catch {} });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  if (opts.css) await ctx.addInitScript((css) => { const f = () => { const s = document.createElement('style'); s.textContent = css; document.documentElement.appendChild(s); }; f(); }, opts.css);
  const rec = { name, dir, frames: [], marks: [], mouse: { x: 640, y: 360 }, browser, ctx, page, cdp: null, n: 0 };
  rec.cdp = await ctx.newCDPSession(page);
  rec.cdp.on('Page.screencastFrame', async (f) => {
    const file = path.join(dir, String(rec.n++).padStart(6, '0') + '.jpg');
    fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
    rec.frames.push({ file, ts: f.metadata.timestamp });
    try { await rec.cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }); } catch {}
  });
  return rec;
}

export async function start(rec) {
  await rec.cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
  rec.startedAt = Date.now();
}
/** Log a named mark (wall clock ms) and any extra fields. */
export function mark(rec, what, extra = {}) { rec.marks.push({ what, ms: Date.now(), ...extra }); }

/** Stop, write the ffconcat list, encode to mp4 and save marks as JSON. */
export async function finish(rec, extra = {}) {
  const endMs = Date.now();
  await sleep(300);
  try { await rec.cdp.send('Page.stopScreencast'); } catch {}
  await rec.browser.close();
  const fr = [];
  for (const f of rec.frames.sort((a, b) => a.ts - b.ts)) if (!fr.length || f.ts > fr[fr.length - 1].ts) fr.push(f);
  if (!fr.length) throw new Error('no frames captured for ' + rec.name);
  const t0 = fr[0].ts;
  const endTs = Math.max(fr[fr.length - 1].ts + 0.1, endMs / 1000 - 0.3);
  let list = 'ffconcat version 1.0\n';
  fr.forEach((f, i) => { const d = (i + 1 < fr.length ? fr[i + 1].ts : endTs) - f.ts; list += `file '${f.file}'\nduration ${Math.max(d, 0.001).toFixed(4)}\n`; });
  list += `file '${fr[fr.length - 1].file}'\n`;
  const lp = path.join(REC, rec.name + '.ffconcat');
  fs.writeFileSync(lp, list);
  const out = path.join(REC, rec.name + '.mp4');
  execFileSync(FFMPEG, ['-nostdin', '-v', 'error', '-y', '-safe', '0', '-f', 'concat', '-i', lp, '-vf', 'fps=30,scale=1920:1080:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-crf', '17', '-preset', 'medium', '-movflags', '+faststart', out]);
  const meta = { name: rec.name, duration: endTs - t0, frames: fr.length, marks: rec.marks.map((m) => ({ ...m, t: m.ms / 1000 - t0 })), ...extra };
  fs.writeFileSync(path.join(REC, rec.name + '.json'), JSON.stringify(meta, null, 1));
  fs.rmSync(rec.dir, { recursive: true, force: true });
  fs.rmSync(lp, { force: true });
  console.log(rec.name, 'frames', fr.length, 'duration', meta.duration.toFixed(1), 's ->', out, fs.statSync(out).size, 'bytes');
  return meta;
}

// Mouse helpers --------------------------------------------------------------------------------------
const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
export async function moveTo(rec, x, y, ms = 520) {
  const { page, mouse } = rec; const steps = Math.max(6, Math.round(ms / 16));
  for (let i = 1; i <= steps; i++) { const e = ease(i / steps); await page.mouse.move(mouse.x + (x - mouse.x) * e, mouse.y + (y - mouse.y) * e); await sleep(16); }
  rec.mouse = { x, y };
}
/** Scroll into view, glide the cursor onto the element, pause, click. Accepts a Playwright locator. */
export async function click(rec, loc, { pause = 220, ms = 560 } = {}) {
  const el = loc.first();
  await el.scrollIntoViewIfNeeded();
  const b = await el.boundingBox();
  if (!b) throw new Error('no box for click');
  await moveTo(rec, b.x + b.width / 2, b.y + b.height / 2, ms);
  await sleep(pause);
  await rec.page.mouse.down(); await sleep(60); await rec.page.mouse.up();
}
export async function drag(rec, x1, y1, x2, y2, ms = 900) {
  await moveTo(rec, x1, y1, 400); await rec.page.mouse.down();
  const steps = Math.round(ms / 16);
  for (let i = 1; i <= steps; i++) { const e = ease(i / steps); await rec.page.mouse.move(x1 + (x2 - x1) * e, y1 + (y2 - y1) * e); await sleep(16); }
  await rec.page.mouse.up(); rec.mouse = { x: x2, y: y2 };
}
/** Small wheel steps over (x,y). */
export async function wheel(rec, x, y, dy, steps = 12, gap = 40) {
  await rec.page.mouse.move(x, y); rec.mouse = { x, y };
  for (let i = 0; i < steps; i++) { await rec.page.mouse.wheel(0, dy / steps); await sleep(gap); }
}
export async function type(rec, loc, text) { await click(rec, loc); await loc.first().pressSequentially(text, { delay: 55 }); }

// Backend helpers ------------------------------------------------------------------------------------
export async function sms(from, body) {
  const r = await fetch(`${API}/sms/simulate`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ from, body }) });
  return { status: r.status, reply: await r.json().catch(() => null) };
}
export const scenario = async (slug = 'cottonwood-creek-packet') => (await fetch(`${API}/scenario/${slug}`)).json();
export const PEOPLE = { duty: '+13165550101', chief: '+13165550102', sam: '+13165550111', kelsey: '+13165550112', mike: '+13165550113' };

/** Run a segment safely: log and carry on. */
export async function safely(name, fn) {
  try { await fn(); return true; } catch (e) { console.error('SEGMENT FAILED', name, e); return false; }
}
