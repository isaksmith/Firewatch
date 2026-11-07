import vectors from '../../docs/mobile/codec-vectors.json';
import { decodeFw1, findCodes, packOfCode } from '../src/lib/codec';

const origin = vectors.origin;

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
