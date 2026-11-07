import { checkDigits, decodeFw1 } from '../src/lib/codec';
import { ed25519 } from '@noble/curves/ed25519';
import vectors from '../../docs/mobile/codec-vectors.json';
import { packMessage, verifyPackText } from '../src/lib/packs';
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
  // TEST-ONLY key from codec-vectors.json, injected; the app never trusts it on its own.
  const seed = Uint8Array.from(Buffer.from(vectors.signing.test_only_seed_hex, 'hex'));
  const keys = [{ id: 'test-only', key: vectors.signing.test_only_public_key }];
  const b64url = (b: Uint8Array) => Buffer.from(b).toString('base64url');
  const signFor = (s: string, version = '1', code = 'cwc', k = seed) => b64url(ed25519.sign(Buffer.from(packMessage(code, version, s), 'ascii'), k));
  const info = (text: string, s?: string, sig?: string | null): PackInfo & { sig?: string } => {
    const hash = s ?? sha(text);
    return { code: 'cwc', name: 'x', state: 'KS', counties: [], version: '1', bytes: 1, sha256: hash, ...(sig === null ? {} : { sig: sig ?? signFor(hash) }) };
  };
  const verify = (t: string, i: PackInfo & { sig?: string }) => verifyPackText(t, i, keys);
  it('accepts a good pack and defaults missing arrays', async () => {
    const t = JSON.stringify(pack);
    const p = await verify(t, info(t));
    expect(p.roads).toEqual([]);
    expect(p.places).toEqual([]);
  });
  it('refuses a pack with no sig, a bad sig, a sig from another key, or a sig for another version', async () => {
    const t = JSON.stringify(pack);
    const h = sha(t);
    const other = Uint8Array.from(Buffer.alloc(32, 9));
    const good = signFor(h);
    const flipped = good.slice(0, 20) + (good[20] === 'A' ? 'B' : 'A') + good.slice(21);
    for (const sig of [null, '', flipped, signFor(h, '1', 'cwc', other), signFor(h, '2'), signFor(h, '1', 'ks-clark')]) {
      await expect(verify(t, info(t, undefined, sig))).rejects.toThrow(/did not come from your dispatch server/);
    }
    // the app's own keys do not trust the test key
    await expect(verifyPackText(t, info(t))).rejects.toThrow(/did not come from your dispatch server/);
  });
  it('accepts the uppercase sha256 spelling with the same signature', async () => {
    const t = JSON.stringify(pack);
    const h = sha(t);
    await expect(verify(t, info(t, h.toUpperCase(), signFor(h)))).resolves.toBeTruthy();
  });
  it('refuses a missing sha256', async () => {
    const t = JSON.stringify(pack);
    await expect(verify(t, info(t, ''))).rejects.toThrow(/no safety check/);
  });
  it('refuses a wrong sha256', async () => {
    const t = JSON.stringify(pack);
    await expect(verify(t, info(t, 'abc'))).rejects.toThrow(/sha256/);
  });
  it('refuses a pack without origin', async () => {
    const t = JSON.stringify({ ...pack, origin: undefined });
    await expect(verify(t, info(t))).rejects.toThrow();
  });
  it('refuses a bad bbox or non-array roads', async () => {
    for (const bad of [{ bbox: [1, 2] }, { roads: {} }, { code: 'zzz' }]) {
      const t = JSON.stringify({ ...pack, ...bad });
      await expect(verify(t, info(t))).rejects.toThrow();
    }
  });
});

describe('pack codes are safe file names', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { isPackCode } = require('../src/lib/packs');
  it.each(['cwc', 'ks-comanche', 'a1'])('accepts %s', (c) => expect(isPackCode(c)).toBe(true));
  it.each(['../x', 'a/b', '..', '-x', 'CWC', '', 'a'.repeat(33), 5, null])('rejects %p', (c) => expect(isPackCode(c)).toBe(false));
});
