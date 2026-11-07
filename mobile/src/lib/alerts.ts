import { BadSignature, decodeFw1, findCodes, packOfCode, type Fw1 } from './codec';
import { getDb, kvSet } from './db';
import { loadPack } from './packs';
import type { Source } from './types';

export type StoredAlert = Fw1 & { source: Source; received: number };

export type IngestResult =
  | { ok: true; alert: StoredAlert; changed: boolean }
  // not_from_dispatch: a signature is present but does not verify. Nothing is stored.
  | { ok: false; reason: 'damaged' | 'no_pack' | 'not_from_dispatch'; pack?: string };

type Row = {
  pack: string; id: number; code: string; kind: Fw1['kind']; level: Fw1['level']; score: number;
  lat: number; lon: number; t: number; source: Source; received: number;
};

/** Re-decode from the stored code so every field comes from the one contract. */
async function rowToAlert(r: Row): Promise<StoredAlert | null> {
  const pack = await loadPack(r.pack);
  if (!pack) return null;
  try {
    return { ...decodeFw1(r.code, pack.origin), source: r.source, received: r.received };
  } catch {
    return null;
  }
}

/** True when a stored code still verifies with a trusted key (the stored code is the whole record). */
function storedIsVerified(code: string, origin: { lat: number; lon: number }): boolean {
  try {
    return decodeFw1(code, origin).verified;
  } catch {
    return false;
  }
}

/**
 * Should `f` replace what is stored for the same pack and id? The rules (FW1-CODEC.md, Signatures):
 * - verified: replaces an unverified alert regardless of t; replaces a verified one only with a newer t.
 * - unverified ("Not confirmed by dispatch"): never replaces, clears or downgrades a verified alert; a c or x code
 *   changes nothing that exists; otherwise a newer t replaces an older unverified one.
 */
export function shouldReplace(f: Pick<Fw1, 'kind' | 'time' | 'verified'>, old: { t: number; verified: boolean } | null): boolean {
  if (!old) return true;
  if (f.verified) return !old.verified || f.time > old.t;
  if (old.verified) return false;
  if (f.kind !== 'alert') return false;
  return f.time > old.t;
}

/** Open a code. Reading is offline and private: nothing is ever sent. Newer t replaces older, never the reverse. */
export async function ingestCode(code: string, source: Source): Promise<IngestResult> {
  const packCode = packOfCode(code);
  if (!packCode) return { ok: false, reason: 'damaged' };
  const pack = await loadPack(packCode);
  if (!pack) return { ok: false, reason: 'no_pack', pack: packCode };
  let f: Fw1;
  try {
    f = decodeFw1(code, pack.origin);
  } catch (e) {
    return { ok: false, reason: e instanceof BadSignature ? 'not_from_dispatch' : 'damaged' };
  }
  const db = await getDb();
  const old = await db.getFirstAsync<{ t: number; code: string }>('SELECT t, code FROM alerts WHERE pack = ? AND id = ?', f.pack, f.id);
  const received = Date.now();
  const alert: StoredAlert = { ...f, source, received };
  if (!shouldReplace(f, old ? { t: old.t, verified: storedIsVerified(old.code, pack.origin) } : null)) {
    return { ok: true, alert, changed: false };
  }
  await db.runAsync(
    'INSERT OR REPLACE INTO alerts (pack,id,code,kind,level,score,lat,lon,t,source,received) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
    f.pack, f.id, f.code, f.kind, f.level, f.score, f.lat, f.lon, f.time, source, received,
  );
  await kvSet('lastUpdate', JSON.stringify({ at: received, source }));
  return { ok: true, alert, changed: true };
}

export type TextResult = { found: number; opened: IngestResult[]; };

/** Paste or link text: find every FW1 code and open each. */
export async function ingestText(text: string, source: Source): Promise<TextResult> {
  const codes = findCodes(text);
  const opened: IngestResult[] = [];
  for (const c of codes) opened.push(await ingestCode(c, source));
  return { found: codes.length, opened };
}

const LEVEL_RANK = { escalate: 0, investigate: 1, monitor: 2 } as const;

export async function listAlerts(): Promise<StoredAlert[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<Row>('SELECT * FROM alerts');
  const out: StoredAlert[] = [];
  for (const r of rows) {
    const a = await rowToAlert(r);
    if (a) out.push(a);
  }
  // Open fires first (most urgent, then newest); cleared and not-a-fire last.
  const open = (a: StoredAlert) => (a.kind === 'alert' ? 0 : 1);
  out.sort((a, b) => open(a) - open(b) || LEVEL_RANK[a.level] - LEVEL_RANK[b.level] || b.time - a.time);
  return out;
}

export async function getAlert(pack: string, id: number): Promise<StoredAlert | null> {
  const db = await getDb();
  const r = await db.getFirstAsync<Row>('SELECT * FROM alerts WHERE pack = ? AND id = ?', pack, id);
  return r ? rowToAlert(r) : null;
}
