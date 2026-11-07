// The board outbox: a queued report survives an app restart, a retry reuses its client_key,
// and the minutes it waited are sent as queued_min. The phone's database is an in-memory map here.
const mockDisk = new Map<string, string>();
jest.mock('../src/lib/db', () => ({
  kvGet: async (k: string) => mockDisk.get(k) ?? null,
  kvSet: async (k: string, v: string) => { mockDisk.set(k, v); },
  kvDelete: async (k: string) => { mockDisk.delete(k); },
}));

type Board = typeof import('../src/lib/board');
const SERVER = 'http://test.local';
const T0 = Date.UTC(2026, 10, 7, 15, 0);

let posts: { body: Record<string, unknown>; token: string | null }[] = [];
let offline = false;
let nextId = 100;

function json(status: number, body: unknown) {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

beforeEach(() => {
  mockDisk.clear();
  posts = [];
  offline = false;
  nextId = 100;
  jest.resetModules();
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    if (offline) throw new TypeError('Network request failed');
    const path = url.replace(`${SERVER}/api/board`, '');
    const token = (init?.headers as Record<string, string> | undefined)?.['X-Firewatch-Device'] ?? null;
    if (path === '/device') return json(200, { token: 'tok-1' });
    if (path === '/posts' && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      posts.push({ body, token });
      const dup = posts.filter((p) => p.body.client_key === body.client_key).length > 1;
      return json(200, { post_id: dup ? 100 : nextId++, duplicate: dup });
    }
    return json(404, { detail: 'Not found' });
  }) as unknown as typeof fetch;
});

const load = (): Board => require('../src/lib/board');

describe('board outbox', () => {
  it('keeps a queued report across a restart and sends it later', async () => {
    let b = load();
    offline = true;
    await b.queueReport('smoke', 'Smoke seen', { lat: 37.27, lon: -99.33 }, T0);
    const r1 = await b.drainOutbox(SERVER, () => T0 + 60000);
    expect(r1).toMatchObject({ offline: true, waiting: 1, sent: [] });

    jest.resetModules(); // the app closes and opens again; only the phone's database is left
    b = load();
    expect(await b.listOutbox()).toHaveLength(1);
    offline = false;
    const r2 = await b.drainOutbox(SERVER, () => T0 + 12 * 60000);
    expect(r2.waiting).toBe(0);
    expect(r2.sent).toHaveLength(1);
    expect(await b.listOutbox()).toHaveLength(0);
    expect(posts[0].token).toBe('tok-1');
    expect(posts[0].body).toMatchObject({ category: 'smoke', body: 'Smoke seen', attach_location: true, lat: 37.27 });
  });

  it('reuses the same client_key on every retry', async () => {
    const b = load();
    const q = await b.queueReport('fire', 'Fire seen', null, T0);
    expect(q.key).toMatch(/^[A-Za-z0-9_-]{16,64}$/);
    // The first send reaches the server but the answer is lost: the phone still has the report.
    let calls = 0;
    const real = global.fetch;
    global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      const r = await (real as unknown as (u: string, i?: RequestInit) => Promise<Response>)(url, init);
      if (String(url).endsWith('/posts') && calls++ === 0) throw new TypeError('lost');
      return r;
    }) as unknown as typeof fetch;
    expect((await b.drainOutbox(SERVER, () => T0)).waiting).toBe(1);
    expect((await b.drainOutbox(SERVER, () => T0 + 3 * 60000)).waiting).toBe(0);
    expect(posts).toHaveLength(2);
    expect(posts[0].body.client_key).toBe(q.key);
    expect(posts[1].body.client_key).toBe(q.key);
    expect(posts[1].body.attach_location).toBe(false);
  });

  it('computes the sent-late minutes', async () => {
    const b = load();
    offline = true;
    await b.queueReport('smoke', 'Smoke seen', null, T0);
    await b.drainOutbox(SERVER, () => T0 + 30000);
    offline = false;
    const r = await b.drainOutbox(SERVER, () => T0 + 17 * 60000 + 20000);
    expect(posts[0].body.queued_min).toBe(17);
    expect(r.sent[0].lateMin).toBe(17);
    expect(b.sentLateText(r.sent[0].lateMin)).toBe('Sent 17 min late (no signal)');
    expect(b.queuedMinutes(T0, T0 + 500 * 60000)).toBe(120);
    expect(b.queuedMinutes(T0, T0 + 10000)).toBe(0);
    expect(b.sentLateText(0)).toBeNull();
  });

  it('does not send a report older than two hours', async () => {
    const b = load();
    await b.queueReport('smoke', 'Smoke seen', null, T0);
    const r = await b.drainOutbox(SERVER, () => T0 + 121 * 60000);
    expect(posts).toHaveLength(0);
    expect(r.waiting).toBe(0);
    expect((await b.listOutbox())[0].problem).toMatch(/Too old/);
  });

  it('remembers own posts after sending', async () => {
    const b = load();
    await b.queueReport('fire', 'Fire seen', null, T0);
    await b.drainOutbox(SERVER, () => T0);
    expect(await b.myPostIds()).toEqual([100]);
  });
});

describe('board words', () => {
  const b = () => load();
  it('says distance and direction', () => {
    expect(b().distanceText({ lat: 37.2689, lon: -99.3268 }, { lat: 37.29, lon: -99.36 })).toMatch(/^2\.\d mi NW$/);
    expect(b().distanceText({ lat: 37.2689, lon: -99.3268 }, { lat: 37.2689, lon: -99.3268 })).toBe('Right by you');
  });
  it('says age plainly', () => {
    expect(b().plainAge(0)).toBe('Just now');
    expect(b().plainAge(12)).toBe('12 min ago');
    expect(b().plainAge(130)).toBe('2 hr ago');
  });
  it('labels confirmations', () => {
    expect(b().confirmWords({ unconfirmed: true, confirms: 0 })).toBe('Unconfirmed');
    expect(b().confirmWords({ unconfirmed: false, confirms: 2 })).toBe('Confirmed by 2 people');
  });
  it('explains refused confirms', () => {
    expect(b().confirmMessage({ ok: false, reason: 'own_post' })).toMatch(/your own report/);
    expect(b().confirmMessage({ ok: true, reason: 'too_far', counted: false })).toMatch(/too far/);
    expect(b().confirmMessage({ ok: true, reason: null, counted: true })).toMatch(/Thanks/);
  });
  it('fills in a plain body', () => {
    expect(b().reportBody('smoke', '  ')).toBe('Smoke seen');
    expect(b().reportBody('other', '')).toBeNull();
    expect(b().reportBody('fire', ' by the creek ')).toBe('by the creek');
  });
});
