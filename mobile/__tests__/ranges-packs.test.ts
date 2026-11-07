import { checkDigits, decodeFw1 } from '../src/lib/codec';
import { verifyPackText } from '../src/lib/packs';
import type { PackInfo } from '../src/lib/types';

jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  digestStringAsync: async (_a: string, t: string) => require('crypto').createHash('sha256').update(t).digest('hex'),
}));
jest.mock('expo-file-system', () => ({ Directory: class {}, File: class {}, Paths: {} }));
jest.mock('../src/lib/db', () => ({ getDb: async () => ({}) }));

const origin = { lat: 37.5, lon: -97.5 };
type F = { id: string; score: string; dlat: string; dlon: string; t: string; dir: string; spd: string; flags: string };
const good: F = { id: 'c', score: '2g', dlat: 'vg', dlon: '-139', t: '2c7t', dir: '0', spd: '6', flags: 'n' };
const make = (o: Partial<F>) => {
  const f = { ...good, ...o };
  const body = ['FW1', 'cwc', 'ae', f.id, f.score, f.dlat, f.dlon, f.t, f.dir, f.spd, f.flags].join('.');
  return `${body}.${checkDigits(body)}`;
};

describe('decodeFw1 ranges', () => {
  it('accepts the baseline', () => { expect(() => decodeFw1(make({}), origin)).not.toThrow(); });
  const bad: [string, Partial<F>][] = [
    ['score 200', { score: '5k' }],
    ['score huge', { score: 'zzzzzzzzzzzz' }],
    ['negative id', { id: '-c' }],
    ['dir 6475', { dir: 'zz' }],
    ['speed over 400', { spd: 'bz' }],
    ['flags over 31', { flags: 'z' }],
    ['dlat huge', { dlat: 'zzzzzzzz' }],
    ['dlon huge', { dlon: '-zzzzzzzz' }],
    ['negative time', { t: '-1' }],
    ['time 15 z', { t: 'zzzzzzzzzzzzzzz' }],
    ['time past 2100', { t: 'zzzzzz' }],
  ];
  for (const [name, o] of bad) it(`rejects ${name}`, () => { expect(() => decodeFw1(make(o), origin)).toThrow(); });
  it('accepts empty dir and speed', () => { expect(() => decodeFw1(make({ dir: '', spd: '' }), origin)).not.toThrow(); });
});

describe('verifyPackText', () => {
  const sha = (t: string) => require('crypto').createHash('sha256').update(t).digest('hex');
  const pack = { format: 'fwpack/1', code: 'cwc', origin: { lat: 1, lon: 2 }, bbox: [0, 0, 1, 1] };
  const info = (text: string, s?: string): PackInfo => ({ code: 'cwc', name: 'x', state: 'KS', counties: [], version: '1', bytes: 1, sha256: s ?? sha(text) });
  it('accepts a good pack and defaults missing arrays', async () => {
    const t = JSON.stringify(pack);
    const p = await verifyPackText(t, info(t));
    expect(p.roads).toEqual([]);
    expect(p.places).toEqual([]);
  });
  it('refuses a missing sha256', async () => {
    const t = JSON.stringify(pack);
    await expect(verifyPackText(t, info(t, ''))).rejects.toThrow(/no safety check/);
  });
  it('refuses a wrong sha256', async () => {
    const t = JSON.stringify(pack);
    await expect(verifyPackText(t, info(t, 'abc'))).rejects.toThrow(/sha256/);
  });
  it('refuses a pack without origin', async () => {
    const t = JSON.stringify({ ...pack, origin: undefined });
    await expect(verifyPackText(t, info(t))).rejects.toThrow();
  });
  it('refuses a bad bbox or non-array roads', async () => {
    for (const bad of [{ bbox: [1, 2] }, { roads: {} }, { code: 'zzz' }]) {
      const t = JSON.stringify({ ...pack, ...bad });
      await expect(verifyPackText(t, info(t))).rejects.toThrow();
    }
  });
});

describe('pack codes are safe file names', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { isPackCode } = require('../src/lib/packs');
  it.each(['cwc', 'ks-comanche', 'a1'])('accepts %s', (c) => expect(isPackCode(c)).toBe(true));
  it.each(['../x', 'a/b', '..', '-x', 'CWC', '', 'a'.repeat(33), 5, null])('rejects %p', (c) => expect(isPackCode(c)).toBe(false));
});
