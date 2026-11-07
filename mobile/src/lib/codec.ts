// FW1 alert code decoder. Contract: docs/mobile/FW1-CODEC.md (do not change).
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
};

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

/** Decode one code. Throws on anything damaged. Needs the pack origin to place the fire. */
export function decodeFw1(code: string, origin: { lat: number; lon: number }): Fw1 {
  const parts = code.split('.');
  if (parts.length !== 12 || parts[0] !== 'FW1') throw new Error('not an FW1 code');
  const body = parts.slice(0, 11).join('.');
  if (checkDigits(body) !== parts[11]) throw new Error('checksum mismatch');
  const [, pack, kl, id, score, dlat, dlon, t, dir, spd, flags] = parts;
  if (kl.length !== 2 || !KINDS[kl[0]] || !LEVELS[kl[1]] || !/^[a-z0-9]+$/.test(pack)) {
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
  };
}

/** The pack code is the second field; readable without the pack installed. */
export function packOfCode(code: string): string | null {
  const p = code.split('.');
  return p.length === 12 && p[0] === 'FW1' && /^[a-z0-9]+$/.test(p[1]) ? p[1] : null;
}

/** Find every FW1 code in free text (pasted message, link, feed line). */
export function findCodes(text: string): string[] {
  const out: string[] = [];
  const re = /FW1\.[0-9a-z.\-]*/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    // A trailing sentence period is not part of the code.
    const c = m[0].replace(/\.+$/, '');
    // Dots may be consecutive for empty fields, so keep interior runs. Trim trailing junk to 12 fields.
    const fields = c.split('.');
    if (fields.length >= 12) out.push(fields.slice(0, 12).join('.'));
    else out.push(c);
  }
  return out;
}
