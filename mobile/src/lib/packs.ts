import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';
import { APP_KEYS, verifySig, type TrustedKey } from './codec';
import { getDb } from './db';
import type { Pack, PackInfo } from './types';

// The demo pack ships inside the app, so the demo works with zero network.
const BUNDLED: Record<string, Pack> = { cwc: require('../../assets/packs/cwc.json') as Pack };

export const BUNDLED_INFOS: PackInfo[] = Object.values(BUNDLED).map((p) => ({
  code: p.code,
  name: p.name,
  state: p.state,
  counties: p.counties,
  version: p.version,
  bytes: JSON.stringify(p).length,
  sha256: '',
}));

const cache = new Map<string, Pack>();

// Pack codes become file names, so only plain lowercase names are allowed (no "/", "..", or leading "-").
const PACK_CODE = /^[a-z0-9][a-z0-9-]{0,31}$/;
export function isPackCode(code: unknown): code is string {
  return typeof code === 'string' && PACK_CODE.test(code);
}

function packFile(code: string): File {
  if (!isPackCode(code)) throw new Error('Bad pack code');
  return new File(Paths.document, 'packs', `${code}.json`);
}

export async function loadPack(code: string): Promise<Pack | null> {
  const hit = cache.get(code);
  if (hit) return hit;
  try {
    const f = packFile(code);
    if (f.exists) {
      const p = JSON.parse(await f.text()) as Pack;
      cache.set(code, p);
      return p;
    }
  } catch {
    // fall through to the bundled copy
  }
  const b = BUNDLED[code];
  if (b) cache.set(code, b);
  return b ?? null;
}

export async function installedPacks(): Promise<PackInfo[]> {
  const db = await getDb();
  const rows = await db.getAllAsync<{
    code: string; name: string; state: string; counties: string; version: string; bytes: number;
  }>('SELECT * FROM packs ORDER BY name');
  return rows.map((r) => ({ ...r, counties: JSON.parse(r.counties) as string[], sha256: '' }));
}

/** Mark the bundled demo pack as installed so a no-network first run still works. */
export async function installBundled(code: string): Promise<void> {
  const p = BUNDLED[code];
  if (!p) return;
  await recordPack({ code: p.code, name: p.name, state: p.state, counties: p.counties, version: p.version, bytes: JSON.stringify(p).length, sha256: '' });
}

async function recordPack(i: PackInfo): Promise<void> {
  const db = await getDb();
  await db.runAsync(
    'INSERT OR REPLACE INTO packs (code, name, state, counties, version, bytes) VALUES (?,?,?,?,?,?)',
    i.code, i.name, i.state, JSON.stringify(i.counties), i.version, i.bytes,
  );
}

export async function fetchPackIndex(server: string): Promise<PackInfo[]> {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 8000);
  try {
    const r = await fetch(`${server}/api/m/packs`, { signal: ctl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    const list = (Array.isArray(j) ? j : j.packs) as PackInfo[];
    return (Array.isArray(list) ? list : []).filter((p) => p && isPackCode(p.code));
  } finally {
    clearTimeout(timer);
  }
}

/** An index entry as the server sends it: PackInfo plus `sig` (FW1-CODEC.md, "Region packs are signed too"). */
export type SignedPackInfo = PackInfo & { sig?: string };

/** The text a pack's `sig` signs: `fwpack/1|<code>|<version>|<sha256 lowercase hex>`. */
export function packMessage(code: string, version: string, sha256: string): string {
  return `fwpack/1|${code}|${version}|${sha256.toLowerCase()}`;
}

const NOT_FROM_DISPATCH = 'This map did not come from your dispatch server, so the phone will not use it. Tell whoever runs the server.';

export class PackDamaged extends Error {}
/** A pack the phone will not use; the message is plain words that can be shown as is. */
export class PackRefused extends PackDamaged {}

const isNum = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);

/**
 * Check the signature, hash and shape of a downloaded pack. Returns the pack, or throws PackDamaged (PackRefused
 * when it has no safety check or its signature is missing or wrong). Packs built into the app never come here.
 */
export async function verifyPackText(text: string, info: SignedPackInfo, keys: readonly TrustedKey[] = APP_KEYS): Promise<Pack> {
  if (!info.sha256) throw new PackRefused('This map has no safety check, so the phone will not use it. Tell whoever runs the server.');
  if (typeof info.sig !== 'string' || !verifySig(packMessage(info.code, String(info.version), info.sha256), info.sig, keys)) {
    throw new PackRefused(NOT_FROM_DISPATCH);
  }
  const got = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text);
  if (got.toLowerCase() !== info.sha256.toLowerCase()) throw new PackDamaged('sha256 mismatch');
  let raw: Record<string, unknown>;
  try { raw = JSON.parse(text) as Record<string, unknown>; } catch { throw new PackDamaged('not json'); }
  const o = raw?.origin as { lat?: unknown; lon?: unknown } | undefined;
  const bb = raw?.bbox;
  if (
    !raw || raw.format !== 'fwpack/1' || raw.code !== info.code ||
    !o || !isNum(o.lat) || !isNum(o.lon) ||
    !Array.isArray(bb) || bb.length !== 4 || !bb.every(isNum)
  ) throw new PackDamaged('wrong pack');
  for (const k of ['roads', 'towns', 'buildings', 'places', 'stations', 'power_lines']) {
    if (raw[k] === undefined) raw[k] = [];
    else if (!Array.isArray(raw[k])) throw new PackDamaged('wrong pack');
  }
  return raw as unknown as Pack;
}

/** Download one pack, check its sha256 and shape, store it. Throws PackDamaged when it is not trustworthy. */
export async function downloadPack(server: string, info: SignedPackInfo): Promise<void> {
  if (!isPackCode(info.code)) throw new PackDamaged();
  const r = await fetch(`${server}/api/m/packs/${info.code}`);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const text = await r.text();
  const pack = await verifyPackText(text, info);
  new Directory(Paths.document, 'packs').create({ intermediates: true, idempotent: true });
  const f = packFile(info.code);
  f.create({ intermediates: true, overwrite: true });
  f.write(text);
  cache.set(info.code, pack);
  await recordPack({ ...info, bytes: info.bytes || text.length });
}

export function fmtBytes(n: number): string {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
