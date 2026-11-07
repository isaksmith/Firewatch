import vectors from '../../docs/mobile/codec-vectors.json';
import appJson from '../app.json';
import { APP_KEYS, BadSignature, decodeFw1, findCodes, hasSig, packOfCode, unb64url, verifySig } from '../src/lib/codec';

const origin = vectors.origin;
// TEST-ONLY key from codec-vectors.json, injected here; the app itself never trusts it.
const TEST_KEYS = [{ id: 'test-only', key: vectors.signing.test_only_public_key }];

describe('FW1 codec vectors', () => {
  for (const v of vectors.vectors) {
    it(`decodes ${v.code}`, () => {
      const d = decodeFw1(v.code, origin);
      const i = v.input;
      expect(d.pack).toBe(i.pack);
      expect(d.id).toBe(i.id);
      expect(d.score).toBe(i.score);
      expect(d.lat).toBeCloseTo(i.lat, 4);
      expect(d.lon).toBeCloseTo(i.lon, 4);
      expect(new Date(d.time).toISOString().replace('.000Z', 'Z')).toBe(v.decoded_time_iso);
      expect(d.towardDeg).toBe(i.toward_deg == null ? null : Math.round(i.toward_deg / 5) % 72 * 5);
      expect(d.mph).toBe(i.mph == null ? null : Math.round(i.mph * 2) / 2);
      expect([...d.flags].sort()).toEqual([...i.flags].sort());
      expect(d.kind).toBe(i.kind);
      expect(d.level).toBe(i.level);
    });
  }
  for (const bad of vectors.must_reject) {
    it(`rejects ${JSON.stringify(bad)}`, () => {
      expect(() => decodeFw1(bad, origin)).toThrow();
    });
  }
  it('finds codes inside text', () => {
    const c = vectors.vectors[1].code;
    expect(findCodes(`Fire near Rd K. Firewatch app: firewatch://a/${c}. Thanks`)).toEqual([c]);
    const empty = vectors.vectors[0].code;
    expect(findCodes(`x ${empty}`)).toEqual([empty]);
    expect(packOfCode(c)).toBe('cwc');
    expect(findCodes('nothing here')).toEqual([]);
  });
});

describe('FW1 signed vectors (TEST-ONLY key)', () => {
  for (const v of vectors.signing.vectors) {
    it(`verifies ${v.signed.slice(0, 40)}...`, () => {
      const d = decodeFw1(v.signed, origin, TEST_KEYS);
      const plain = decodeFw1(v.code, origin, TEST_KEYS);
      expect(d.verified).toBe(true);
      expect(d.sig).toBe(v.signed.split('.')[12]);
      expect(plain.verified).toBe(false);
      expect(plain.sig).toBeNull();
      const { code: _a, sig: _b, verified: _c, ...rest } = d;
      const { code: _d, sig: _e, verified: _f, ...restPlain } = plain;
      expect(rest).toEqual(restPlain);
      expect(v.signed.length).toBeLessThanOrEqual(126);
      expect(packOfCode(v.signed)).toBe('cwc');
    });
  }
  for (const r of vectors.signing.must_reject_signed) {
    it(`refuses: ${r.why}`, () => {
      expect(() => decodeFw1(r.code, origin, TEST_KEYS)).toThrow(BadSignature);
    });
  }
  it('refuses a signed code when no key is trusted, and with the keys built into the app', () => {
    const s = vectors.signing.vectors[1].signed;
    expect(() => decodeFw1(s, origin, [])).toThrow(BadSignature);
    expect(() => decodeFw1(s, origin)).toThrow(BadSignature);
  });
  it('refuses odd signature shapes', () => {
    const s = vectors.signing.vectors[1].signed;
    const [body, sig] = [s.slice(0, s.lastIndexOf('.')), s.slice(s.lastIndexOf('.') + 1)];
    const abc = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
    const nonCanonical = sig.slice(0, -1) + abc[abc.indexOf(sig[85]) ^ 1];
    for (const bad of [`${body}.${sig.slice(0, 85)}`, `${body}.${sig}A`, `${body}.${nonCanonical}`, `${body}.`, `${body}.${sig.replace(/./, '+')}`]) {
      expect(() => decodeFw1(bad, origin, TEST_KEYS)).toThrow();
    }
    expect(() => decodeFw1(`${s}.x`, origin, TEST_KEYS)).toThrow();
  });
  it('a damaged checksum on a signed code is damaged, not a signature problem', () => {
    const s = vectors.signing.vectors[1].signed;
    const parts = s.split('.');
    parts[11] = parts[11] === '000' ? '001' : '000';
    expect(() => decodeFw1(parts.join('.'), origin, TEST_KEYS)).toThrow(/checksum/);
  });
  it('verifies the pack signature vector', () => {
    const pk = vectors.signing.pack;
    expect(verifySig(pk.message, pk.sig, TEST_KEYS)).toBe(true);
    expect(verifySig(pk.message.replace('cwc', 'cwd'), pk.sig, TEST_KEYS)).toBe(false);
  });
  it('the finder picks up signed codes in texts, links and feed lines', () => {
    const s = vectors.signing.vectors[1].signed;
    const plain = vectors.signing.vectors[1].code;
    expect(findCodes(`Firewatch app: firewatch://a/${s}`)).toEqual([s]);
    expect(findCodes(`Fire near Rd K. Firewatch app: firewatch://a/${s}. Thanks`)).toEqual([s]);
    expect(findCodes(`17 ${s}\n18 ${plain}\n`)).toEqual([s, plain]);
    expect(findCodes(`see ${plain}.Thanks`)).toEqual([plain]);
    const empty = vectors.signing.vectors[0].signed; // empty dir and speed fields
    expect(findCodes(`x ${empty} y`)).toEqual([empty]);
    // a damaged signature is kept so the app refuses it instead of showing the code unsigned
    const cut = s.slice(0, -3);
    expect(findCodes(cut)).toEqual([cut]);
    expect(hasSig(cut)).toBe(true);
    expect(() => decodeFw1(cut, origin, TEST_KEYS)).toThrow(BadSignature);
  });
});

describe('trusted keys built into the app', () => {
  it('come from app.json and never include the TEST-ONLY key', () => {
    expect(APP_KEYS).toEqual(appJson.expo.extra.fw1Keys);
    expect(APP_KEYS.length).toBeGreaterThan(0);
    for (const k of APP_KEYS) {
      expect(k.key).toHaveLength(43);
      expect(unb64url(k.key)?.length).toBe(32);
      expect(k.key).not.toBe(vectors.signing.test_only_public_key);
    }
    expect(APP_KEYS.find((k) => k.id === 'firewatch-demo-2026-11')).toBeTruthy();
  });
});


describe('hyphenated pack codes (ks-comanche and friends)', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ed25519 } = require('@noble/curves/ed25519');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { checkDigits } = require('../src/lib/codec');
  const seed = Uint8Array.from(Buffer.from(vectors.signing.test_only_seed_hex, 'hex'));
  const make = (pack: string) => {
    const body = ['FW1', pack, 'ae', 'zzzzzz', '2s', '-255s', '-255s', '2c7t', '1z', 'b4', 'v'].join('.');
    const code = `${body}.${checkDigits(body)}`;
    return `${code}.${Buffer.from(ed25519.sign(Buffer.from(code, 'ascii'), seed)).toString('base64url')}`;
  };
  it.each(['cwc', 'ks-barber', 'ks-clark', 'ks-comanche'])('%s: found in the link text, read and verified', (pack) => {
    const s = make(pack);
    const link = `firewatch://a/${s}`;
    expect(link.length).toBeLessThanOrEqual(160);
    expect(findCodes(link)).toEqual([s]);
    expect(packOfCode(s)).toBe(pack);
    const d = decodeFw1(s, origin, TEST_KEYS);
    expect(d.pack).toBe(pack);
    expect(d.verified).toBe(true);
  });
  it.each(['-ks', 'KS-x', 'a/b', 'a'.repeat(33)])('still refuses pack %p', (pack) => {
    expect(packOfCode(make(pack))).toBeNull();
  });
});
