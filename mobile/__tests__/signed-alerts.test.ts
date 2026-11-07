// The "What the app does" table in docs/mobile/FW1-CODEC.md (Signatures), run against ingestCode.
import vectors from '../../docs/mobile/codec-vectors.json';
import { getAlert, ingestCode, ingestText, listAlerts, shouldReplace } from '../src/lib/alerts';

// Trust the TEST-ONLY key for this file only, by standing in for app.json. The real app.json never lists it.
jest.mock('../app.json', () => {
  const v = jest.requireActual('../../docs/mobile/codec-vectors.json');
  return { expo: { extra: { fw1Keys: [{ id: 'test-only', key: v.signing.test_only_public_key }] } } };
});
jest.mock('../src/lib/packs', () => ({
  loadPack: async (code: string) => (code === 'cwc' ? { code: 'cwc', origin: { lat: 37.2689, lon: -99.3268 } } : null),
}));

type Row = { pack: string; id: number; code: string; kind: string; level: string; score: number; lat: number; lon: number; t: number; source: string; received: number };
const mockRows = new Map<string, Row>();
jest.mock('../src/lib/db', () => ({
  kvSet: async () => {},
  getDb: async () => ({
    getFirstAsync: async (sql: string, pack: string, id: number) => {
      const r = mockRows.get(`${pack}|${id}`);
      if (!r) return null;
      return sql.startsWith('SELECT t, code') ? { t: r.t, code: r.code } : { ...r };
    },
    getAllAsync: async () => [...mockRows.values()].map((r) => ({ ...r })),
    runAsync: async (_sql: string, ...a: (string | number)[]) => {
      const [pack, id, code, kind, level, score, lat, lon, t, source, received] = a;
      mockRows.set(`${pack}|${id}`, { pack, id, code, kind, level, score, lat, lon, t, source, received } as Row);
    },
  }),
}));

const S = vectors.signing.vectors;
// 0: alert investigate 18:51, 1: escalate 19:05, 2: escalate 19:20, 3: clear 23:40 (all id 12); 4: not a fire, id 1295
const signed = (i: number) => S[i].signed;
const plain = (i: number) => S[i].code;
const stored = () => mockRows.get('cwc|12')?.code;

beforeEach(() => mockRows.clear());

describe('verified codes', () => {
  it('a newer verified code replaces an older verified one, never the reverse', async () => {
    expect(await ingestCode(signed(1), 'text')).toMatchObject({ ok: true, changed: true });
    expect(await ingestCode(signed(2), 'feed')).toMatchObject({ ok: true, changed: true });
    expect(await ingestCode(signed(1), 'feed')).toMatchObject({ ok: true, changed: false });
    expect(stored()).toBe(signed(2));
    expect((await getAlert('cwc', 12))?.verified).toBe(true);
  });
  it('a verified code replaces an unverified one regardless of t', async () => {
    await ingestCode(plain(2), 'paste');
    expect(await ingestCode(signed(1), 'feed')).toMatchObject({ ok: true, changed: true });
    expect(stored()).toBe(signed(1));
  });
  it('a verified clear clears a verified alert', async () => {
    await ingestCode(signed(2), 'feed');
    expect(await ingestCode(signed(3), 'feed')).toMatchObject({ ok: true, changed: true });
    expect((await getAlert('cwc', 12))?.kind).toBe('clear');
  });
});

describe('unsigned codes: Not confirmed by dispatch', () => {
  it('a newer unsigned code does not replace a verified one', async () => {
    await ingestCode(signed(1), 'feed');
    const r = await ingestCode(plain(2), 'paste');
    expect(r).toMatchObject({ ok: true, changed: false });
    expect(stored()).toBe(signed(1));
    expect((await getAlert('cwc', 12))?.verified).toBe(true);
  });
  it('an unsigned clear or not-a-fire changes nothing that exists, verified or not', async () => {
    await ingestCode(signed(2), 'feed');
    expect(await ingestCode(plain(3), 'paste')).toMatchObject({ ok: true, changed: false });
    expect(stored()).toBe(signed(2));
    mockRows.clear();
    await ingestCode(plain(0), 'paste');
    expect(await ingestCode(plain(3), 'paste')).toMatchObject({ ok: true, changed: false });
    expect(stored()).toBe(plain(0));
  });
  it('an unsigned code never downgrades a verified alert', async () => {
    await ingestCode(signed(2), 'feed'); // escalate
    await ingestCode(plain(0), 'radio'); // older investigate
    expect((await getAlert('cwc', 12))?.level).toBe('escalate');
  });
  it('is shown, marked not verified, when nothing verified exists; newer unsigned replaces older unsigned', async () => {
    const r = await ingestCode(plain(0), 'paste');
    expect(r.ok && r.alert.verified).toBe(false);
    expect(await ingestCode(plain(1), 'paste')).toMatchObject({ ok: true, changed: true });
    expect(await ingestCode(plain(0), 'paste')).toMatchObject({ ok: true, changed: false });
    expect(stored()).toBe(plain(1));
    const list = await listAlerts();
    expect(list).toHaveLength(1);
    expect(list[0].verified).toBe(false);
  });
  it('an unsigned not-a-fire with nothing stored is shown, not confirmed', async () => {
    expect(await ingestCode(plain(4), 'paste')).toMatchObject({ ok: true, changed: true });
    expect((await getAlert('cwc', 1295))?.verified).toBe(false);
  });
});

describe('refused codes: nothing is stored', () => {
  for (const r of vectors.signing.must_reject_signed) {
    it(`refuses (${r.why})`, async () => {
      expect(await ingestCode(r.code, 'paste')).toEqual({ ok: false, reason: 'not_from_dispatch' });
      expect(mockRows.size).toBe(0);
    });
  }
  it('a bad signature does not touch an existing alert', async () => {
    await ingestCode(plain(0), 'paste');
    const forged = vectors.signing.must_reject_signed[2].code;
    expect(await ingestCode(forged, 'paste')).toMatchObject({ ok: false, reason: 'not_from_dispatch' });
    expect(stored()).toBe(plain(0));
  });
  it('a damaged checksum is still "damaged"', async () => {
    expect(await ingestCode(vectors.must_reject[0], 'paste')).toEqual({ ok: false, reason: 'damaged' });
    expect(mockRows.size).toBe(0);
  });
  it('paste finds a signed code in a text message and opens it verified', async () => {
    const res = await ingestText(`Fire update. Firewatch app: firewatch://a/${signed(1)}`, 'paste');
    expect(res.found).toBe(1);
    expect(res.opened[0]).toMatchObject({ ok: true, changed: true });
    expect((await getAlert('cwc', 12))?.verified).toBe(true);
  });
});

describe('shouldReplace', () => {
  const v = (kind: 'alert' | 'clear', time: number, verified: boolean) => ({ kind, time, verified });
  it.each([
    ['nothing stored', v('alert', 1, false), null, true],
    ['verified older over unverified newer', v('alert', 1, true), { t: 5, verified: false }, true],
    ['verified same t over verified', v('alert', 5, true), { t: 5, verified: true }, false],
    ['unsigned newer over verified', v('alert', 9, false), { t: 5, verified: true }, false],
    ['unsigned clear over unverified', v('clear', 9, false), { t: 5, verified: false }, false],
    ['unsigned newer over unverified', v('alert', 9, false), { t: 5, verified: false }, true],
  ] as const)('%s', (_n, f, old, want) => {
    expect(shouldReplace(f, old)).toBe(want);
  });
});
