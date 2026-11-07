// The community board: neighbors post what they see, people nearby confirm, today's permitted burns.
// Talks to the public board API (backend/app/routes_posts.py) at the same server address as the feed.
// Reports are written to an outbox on the phone first and sent from there, so no signal never loses one.
import { kvDelete, kvGet, kvSet } from './db';
import { bearing, compass, distMi, fmtMi, toXY } from './geo';

export type Category = 'smoke' | 'fire' | 'other';
export type LatLon = { lat: number; lon: number };

export type BoardPost = {
  id: number;
  category: string;
  body: string;
  lat: number | null;
  lon: number | null;
  status: string;
  author: string | null;
  confirms: number;
  badge: string | null;
  unconfirmed: boolean;
  age_min?: number;
  created_at: string;
  sent_late_min?: number | null;
};

export type BoardBurn = { lat: number; lon: number; radius_km: number; registered_at: string; reports_nearby: boolean };
export type BoardMe = { name: string | null; role: string | null; member: boolean; station: boolean };
export type ConfirmResult = { ok: boolean; reason: string | null; counted?: boolean; count?: number };

/** One report waiting on the phone. `key` is the client_key, the same on every try. */
export type Queued = {
  key: string;
  category: Category;
  body: string;
  lat: number | null;
  lon: number | null;
  savedAt: number;
  /** Set when the server refused it for a reason other than signal (too many reports, bad input). */
  problem?: string | null;
};

/** A report that reached the server, kept briefly so the screen can say how late it went. */
export type Sent = { key: string; postId: number; lateMin: number; sentAt: number; body: string };

const K_TOKEN = 'board:device';
const K_OUTBOX = 'board:outbox';
const K_SENT = 'board:sent';
const K_MINE = 'board:mine';
const K_CACHE = 'board:cache';

/** The server accepts queued_min up to 120. Older reports are too stale to raise an alarm. */
export const MAX_QUEUE_MIN = 120;
const TIMEOUT_MS = 10000;

export class BoardError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}
/** No answer at all: no signal, server down, or timed out. */
export class NoSignal extends Error {}

// ---- small pure helpers (tested) ----

export const CATEGORY_WORDS: Record<string, string> = {
  fire: 'Fire', smoke: 'Smoke', hazard: 'Road or hazard', burn: 'Controlled burn', other: 'Something else',
};
export const categoryWords = (c: string) => CATEGORY_WORDS[c] ?? 'Something else';

const DEFAULT_BODY: Record<Category, string> = { smoke: 'Smoke seen', fire: 'Fire seen', other: '' };

/** The text sent to the server: the note, or a plain default for smoke and fire. Null when Other has no note. */
export function reportBody(category: Category, note: string): string | null {
  const n = note.trim().slice(0, 500);
  if (n) return n;
  return DEFAULT_BODY[category] || null;
}

/** "2.1 mi NW" from the phone to a point. */
export function distanceText(me: LatLon, pt: LatLon): string {
  const a = toXY(me.lon, me.lat, me);
  const b = toXY(pt.lon, pt.lat, me);
  const d = distMi(a, b);
  if (d < 0.1) return 'Right by you';
  return `${fmtMi(d)} ${compass(bearing(a, b))}`;
}

export function plainAge(min: number): string {
  const m = Math.max(0, Math.round(min));
  if (m < 1) return 'Just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h} hr ago` : `${Math.round(h / 24)} days ago`;
}

export function postAgeMin(p: Pick<BoardPost, 'age_min' | 'created_at'>, now: number): number {
  if (p.age_min != null) return p.age_min;
  return Math.max(0, (now - Date.parse(p.created_at)) / 60000);
}

/** Minutes the report waited on the phone, as the server wants it (0 to 120). */
export function queuedMinutes(savedAt: number, now: number): number {
  return Math.max(0, Math.min(MAX_QUEUE_MIN, Math.round((now - savedAt) / 60000)));
}

export const sentLateText = (min: number | null | undefined) => (min ? `Sent ${min} min late (no signal)` : null);

export function confirmWords(p: Pick<BoardPost, 'unconfirmed' | 'confirms'>): string {
  if (p.confirms > 0) return p.confirms === 1 ? 'Confirmed by 1 person' : `Confirmed by ${p.confirms} people`;
  return p.unconfirmed ? 'Unconfirmed' : 'From a fire district member';
}

/** Plain words for the server's answer to "I see it too". */
export function confirmMessage(r: ConfirmResult): string {
  if (r.ok && r.counted) return 'Thanks. The fire district has your answer.';
  switch (r.reason) {
    case 'own_post': return 'This is your own report, so you cannot confirm it.';
    case 'too_far': return 'Saved, but you are too far away for it to count. Only people nearby can confirm.';
    case 'no_position': return 'Saved, but we could not tell where you are, so it does not count. Turn on location and try again.';
    case 'post_unlocated': return 'Saved. This report has no location, so it cannot be confirmed.';
    case 'closed': case 'expired': case 'not_found': return 'This report is no longer open.';
    case 'note': return 'Saved. Thanks.';
    default: return r.ok ? 'Saved. Thanks.' : 'That did not go through. Try again in a minute.';
  }
}

export function newKey(): string {
  const hex = '0123456789abcdef';
  let s = '';
  for (let i = 0; i < 32; i++) s += hex[Math.floor(Math.random() * 16)];
  return s;
}

// ---- server calls ----

const base = (server: string) => `${server.replace(/\/+$/, '')}/api/board`;

async function call<T>(server: string, path: string, init: { method?: string; body?: unknown; token?: string | null } = {}): Promise<T> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (init.body !== undefined) headers['Content-Type'] = 'application/json';
    if (init.token) headers['X-Firewatch-Device'] = init.token;
    res = await fetch(`${base(server)}${path}`, {
      method: init.method ?? 'GET',
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: ctl.signal,
    });
  } catch {
    throw new NoSignal('no signal');
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let detail = '';
    try {
      const j = await res.json();
      detail = typeof j.detail === 'string' ? j.detail : '';
    } catch { /* not JSON */ }
    if (res.status >= 500) throw new NoSignal(`server ${res.status}`);
    throw new BoardError(detail || `The server said no (${res.status}).`, res.status);
  }
  return (await res.json()) as T;
}

export const getToken = () => kvGet(K_TOKEN);

/** Register this phone once (POST /board/device) and keep the token. */
export async function ensureDevice(server: string): Promise<string> {
  const t = await kvGet(K_TOKEN);
  if (t) return t;
  const r = await call<{ token: string }>(server, '/device', { method: 'POST' });
  await kvSet(K_TOKEN, r.token);
  return r.token;
}

/** Ensure a device, call, and on a 401 (token lost on the server) register again and retry once. */
async function withDevice<T>(server: string, fn: (token: string) => Promise<T>): Promise<T> {
  const t = await ensureDevice(server);
  try {
    return await fn(t);
  } catch (e) {
    if (!(e instanceof BoardError) || e.status !== 401) throw e;
  }
  await kvDelete(K_TOKEN);
  return fn(await ensureDevice(server));
}

export async function fetchMe(server: string): Promise<BoardMe> {
  return withDevice(server, (token) => call<BoardMe>(server, '/me', { token }));
}

export type Snapshot = { posts: BoardPost[]; burns: BoardBurn[]; at: number };

/** Posts and burns, saved on the phone so the board still shows something with no signal. */
export async function fetchBoard(server: string, now = Date.now()): Promise<Snapshot> {
  const token = await kvGet(K_TOKEN);
  const [posts, burns] = await Promise.all([
    call<BoardPost[]>(server, '/posts', { token }),
    call<BoardBurn[]>(server, '/burns'),
  ]);
  const snap = { posts, burns, at: now };
  await kvSet(K_CACHE, JSON.stringify(snap));
  return snap;
}

export async function cachedBoard(): Promise<Snapshot | null> {
  const v = await kvGet(K_CACHE);
  if (!v) return null;
  try { return JSON.parse(v) as Snapshot; } catch { return null; }
}

export async function confirmPost(server: string, id: number, at: LatLon | null): Promise<ConfirmResult> {
  return withDevice(server, (token) =>
    call<ConfirmResult>(server, `/posts/${id}/confirm`, { method: 'POST', token, body: { kind: 'see', lat: at?.lat ?? null, lon: at?.lon ?? null } }));
}

// ---- the outbox ----

async function readJson<T>(k: string, fallback: T): Promise<T> {
  const v = await kvGet(k);
  if (!v) return fallback;
  try { return JSON.parse(v) as T; } catch { return fallback; }
}

export const listOutbox = () => readJson<Queued[]>(K_OUTBOX, []);
export const listSent = () => readJson<Sent[]>(K_SENT, []);
export const myPostIds = () => readJson<number[]>(K_MINE, []);

async function writeOutbox(q: Queued[]) { await kvSet(K_OUTBOX, JSON.stringify(q)); }

/** Save a report on the phone. It stays there until the server has it. */
export async function queueReport(category: Category, body: string, at: LatLon | null, now = Date.now(), key = newKey()): Promise<Queued> {
  const q: Queued = { key, category, body, lat: at?.lat ?? null, lon: at?.lon ?? null, savedAt: now, problem: null };
  await writeOutbox([...(await listOutbox()), q]);
  return q;
}

export async function removeQueued(key: string) {
  await writeOutbox((await listOutbox()).filter((q) => q.key !== key));
}

export function requestBody(q: Queued, now: number) {
  return {
    category: q.category,
    body: q.body,
    lat: q.lat,
    lon: q.lon,
    attach_location: q.lat != null,
    client_key: q.key,
    queued_min: queuedMinutes(q.savedAt, now),
  };
}

export const isTooOld = (q: Queued, now: number) => now - q.savedAt > MAX_QUEUE_MIN * 60000;

/** `note` is the server's words when it asked us to wait (too many reports). */
export type DrainResult = { sent: Sent[]; waiting: number; offline: boolean; note: string | null };

let draining: Promise<DrainResult> | null = null;

/** Send waiting reports oldest first, one at a time. Stops at the first sign of no signal. Never runs twice at once. */
export function drainOutbox(server: string, now: () => number = Date.now): Promise<DrainResult> {
  if (draining) return draining;
  draining = (async () => {
    const sent: Sent[] = [];
    let offline = false;
    let note: string | null = null;
    for (const q of await listOutbox()) {
      if (q.problem) continue;
      const t = now();
      if (isTooOld(q, t)) {
        await setProblem(q.key, 'Too old to send. If you still see it, report it again.');
        continue;
      }
      try {
        const body = requestBody(q, t);
        const r = await withDevice(server, (token) => call<{ post_id: number }>(server, '/posts', { method: 'POST', token, body }));
        const s: Sent = { key: q.key, postId: r.post_id, lateMin: body.queued_min, sentAt: t, body: q.body };
        sent.push(s);
        await recordSent(s);
        await removeQueued(q.key);
      } catch (e) {
        if (e instanceof NoSignal) { offline = true; break; }
        if (e instanceof BoardError && e.status === 429) { note = e.message; break; } // try again later, same key
        await setProblem(q.key, e instanceof Error ? e.message : 'The server did not take this report.');
      }
    }
    const waiting = (await listOutbox()).filter((q) => !q.problem).length;
    return { sent, waiting, offline, note };
  })().finally(() => { draining = null; });
  return draining;
}

async function setProblem(key: string, problem: string) {
  await writeOutbox((await listOutbox()).map((q) => (q.key === key ? { ...q, problem } : q)));
}

async function recordSent(s: Sent) {
  const all = [s, ...(await listSent()).filter((x) => x.key !== s.key)].slice(0, 10);
  await kvSet(K_SENT, JSON.stringify(all));
  await kvSet(K_MINE, JSON.stringify([s.postId, ...(await myPostIds())].slice(0, 100)));
}
