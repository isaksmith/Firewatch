// FW1 alert code decoder. Contract: docs/mobile/FW1-CODEC.md (do not change).
import { ed25519 } from '@noble/curves/ed25519';
// Built into the app at compile time. Keys from a server, a pack or a radio are never trusted.
import appConfig from '../../app.json';

export type Kind = 'alert' | 'clear' | 'notfire';
export type Level = 'escalate' | 'investigate' | 'monitor';
export type Flag = 'red_flag' | 'homes_in_path' | 'exercise' | 'mutual_aid' | 'two_sources';

export type Fw1 = {
  code: string;
  pack: string;
  kind: Kind;
  level: Level;
  id: number;
  score: number;
  lat: number;
  lon: number;
  /** Epoch milliseconds. */
  time: number;
  towardDeg: number | null;
  mph: number | null;
  flags: Flag[];
  /** The 13th field, or null when the code is unsigned. */
  sig: string | null;
  /** True only when sig verifies with a key built into the app. */
  verified: boolean;
};

export type TrustedKey = { id: string; key: string };

/** The public keys the app trusts: `expo.extra.fw1Keys` in app.json, nothing else. */
export const APP_KEYS: readonly TrustedKey[] = Object.freeze(
  ((appConfig as { expo: { extra?: { fw1Keys?: TrustedKey[] } } }).expo.extra?.fw1Keys ?? []).map((k) => Object.freeze({ ...k })),
);

/** A code whose sig is present but does not verify with a trusted key. */
export class BadSignature extends Error {}

const B64URL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
export const SIG_LEN = 86;

/** Strict base64url without padding. Returns null for anything else, including a non-canonical last character. */
export function unb64url(s: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]+$/.test(s) || s.length % 4 === 1) return null;
  const out = new Uint8Array(Math.floor((s.length * 6) / 8));
  let acc = 0, bits = 0, j = 0;
  for (let i = 0; i < s.length; i++) {
    acc = (acc << 6) | B64URL.indexOf(s[i]);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[j++] = (acc >> bits) & 0xff;
    }
    acc &= (1 << bits) - 1;
  }
  return acc === 0 ? out : null;
}

function asciiBytes(text: string): Uint8Array | null {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c > 0x7f) return null;
    out[i] = c;
  }
  return out;
}

const verifiedCache = new Map<string, boolean>();

/** Ed25519 check of `sig` (86-char base64url) over the ASCII text, against each trusted key in turn. */
export function verifySig(text: string, sig: string, keys: readonly TrustedKey[] = APP_KEYS): boolean {
  const cacheKey = `${keys.map((k) => k.key).join(',')}|${text}|${sig}`;
  const hit = verifiedCache.get(cacheKey);
  if (hit !== undefined) return hit;
  let ok = false;
  const sigBytes = sig.length === SIG_LEN ? unb64url(sig) : null;
  const msg = asciiBytes(text);
  if (sigBytes && sigBytes.length === 64 && msg) {
    for (const k of keys) {
      const pub = typeof k.key === 'string' && k.key.length === 43 ? unb64url(k.key) : null;
      if (!pub || pub.length !== 32) continue;
      try {
        if (ed25519.verify(sigBytes, msg, pub, { zip215: false })) { ok = true; break; }
      } catch {
        // a malformed key or signature is a failed check, never a crash
      }
    }
  }
  if (verifiedCache.size > 500) verifiedCache.clear();
  verifiedCache.set(cacheKey, ok);
  return ok;
}

// Same rule as a pack's file name (packs.ts isPackCode): lowercase, digits and inner hyphens, like ks-comanche.
const PACK_FIELD = /^[a-z0-9][a-z0-9-]{0,31}$/;

export const EPOCH_MS = Date.UTC(2026, 0, 1);
const KINDS: Record<string, Kind> = { a: 'alert', c: 'clear', x: 'notfire' };
const LEVELS: Record<string, Level> = { e: 'escalate', i: 'investigate', m: 'monitor' };
const FLAGS: [Flag, number][] = [
  ['red_flag', 1],
  ['homes_in_path', 2],
  ['exercise', 4],
  ['mutual_aid', 8],
  ['two_sources', 16],
];

export function unb36(s: string): number {
  const neg = s.startsWith('-');
  const body = neg ? s.slice(1) : s;
  if (!/^[0-9a-z]+$/.test(body)) throw new Error('bad number');
  const n = parseInt(body, 36);
  return neg ? -n : n;
}

export function crc16(text: string): number {
  let crc = 0xffff;
  for (let i = 0; i < text.length; i++) {
    crc ^= (text.charCodeAt(i) & 0xff) << 8;
    for (let b = 0; b < 8; b++) {
      crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
    }
  }
  return crc;
}

export function checkDigits(body: string): string {
  return (crc16(body) % 46656).toString(36).padStart(3, '0');
}

/**
 * Decode one code. Throws on anything damaged, and throws BadSignature when a sig is present but does not verify
 * with a trusted key. An unsigned code decodes with verified false. Needs the pack origin to place the fire.
 */
export function decodeFw1(code: string, origin: { lat: number; lon: number }, keys: readonly TrustedKey[] = APP_KEYS): Fw1 {
  let parts = code.split('.');
  let sig: string | null = null;
  if (parts.length === 13 && parts[0] === 'FW1') {
    sig = parts[12];
    parts = parts.slice(0, 12);
  }
  if (parts.length !== 12 || parts[0] !== 'FW1') throw new Error('not an FW1 code');
  const body = parts.slice(0, 11).join('.');
  if (checkDigits(body) !== parts[11]) throw new Error('checksum mismatch');
  const [, pack, kl, id, score, dlat, dlon, t, dir, spd, flags] = parts;
  if (kl.length !== 2 || !KINDS[kl[0]] || !LEVELS[kl[1]] || !PACK_FIELD.test(pack)) {
    throw new Error('bad kind or level');
  }
  const fl = unb36(flags);
  const idN = unb36(id), scoreN = unb36(score), dlatN = unb36(dlat), dlonN = unb36(dlon), tN = unb36(t);
  const dirN = dir === '' ? null : unb36(dir);
  const spdN = spd === '' ? null : unb36(spd);
  const MAX_T = (Date.UTC(2100, 0, 1) - EPOCH_MS) / 60000;
  const ok = (n: number) => Number.isFinite(n);
  if (
    ![idN, scoreN, dlatN, dlonN, tN, fl].every(ok) ||
    scoreN < 0 || scoreN > 100 ||
    idN < 0 ||
    (dirN !== null && (dirN < 0 || dirN > 71)) ||
    (spdN !== null && (spdN < 0 || spdN > 400)) ||
    fl < 0 || fl > 31 ||
    Math.abs(dlatN) > 100000 || Math.abs(dlonN) > 100000 ||
    tN < 0 || tN > MAX_T
  ) {
    throw new Error('value out of range');
  }
  // The checksum and fields are good, so the 12-field text is plain ASCII; now the signature, if any.
  const verified = sig !== null && verifySig(parts.join('.'), sig, keys);
  if (sig !== null && !verified) throw new BadSignature('signature does not verify');
  return {
    code,
    pack,
    kind: KINDS[kl[0]],
    level: LEVELS[kl[1]],
    id: idN,
    score: scoreN,
    lat: Math.round((origin.lat + dlatN / 1e4) * 1e4) / 1e4,
    lon: Math.round((origin.lon + dlonN / 1e4) * 1e4) / 1e4,
    time: EPOCH_MS + tN * 60000,
    towardDeg: dirN === null ? null : dirN * 5,
    mph: spdN === null ? null : spdN / 2,
    flags: FLAGS.filter(([, bit]) => fl & bit).map(([f]) => f),
    sig,
    verified,
  };
}

/** True when the code carries a 13th (signature) field, whether or not it verifies. */
export function hasSig(code: string): boolean {
  const p = code.split('.');
  return p.length === 13 && p[0] === 'FW1';
}

/** The pack code is the second field; readable without the pack installed. */
export function packOfCode(code: string): string | null {
  const p = code.split('.');
  return (p.length === 12 || p.length === 13) && p[0] === 'FW1' && PACK_FIELD.test(p[1]) ? p[1] : null;
}

/**
 * Find every FW1 code in free text (pasted message, link, feed line): `FW1.` and 11 more fields, plus an optional
 * 13th field of 86 base64url characters (the signature). A 13th field that looks like a damaged signature (64 or
 * more base64url characters) is kept too, so the app refuses it instead of quietly showing the code unsigned.
 */
export function findCodes(text: string): string[] {
  const out: string[] = [];
  const re = /FW1\.[0-9A-Za-z._-]*/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    // A trailing sentence period is not part of the code.
    const c = m[0].replace(/\.+$/, '');
    // Dots may be consecutive for empty fields, so keep interior runs. Trim trailing junk to 12 or 13 fields.
    const fields = c.split('.');
    if (fields.length < 12) {
      out.push(c);
      continue;
    }
    const sig = fields[12];
    const keepSig = sig !== undefined && /^[A-Za-z0-9_-]+$/.test(sig) && sig.length >= 64;
    out.push(fields.slice(0, keepSig ? 13 : 12).join('.'));
  }
  return out;
}
