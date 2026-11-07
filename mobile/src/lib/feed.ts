import { ingestCode } from './alerts';
import { kvGet, kvSet } from './db';

/** One feed poll. Lines are "<seq> <code>". Sends If-None-Match and only the pack code; never any user data. */
export async function pollFeed(server: string, pack: string): Promise<'new' | 'same' | 'fail'> {
  try {
    const since = Number((await kvGet(`feedSeq:${pack}`)) ?? '0') || 0;
    const etag = await kvGet(`feedEtag:${pack}`);
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 8000);
    const r = await fetch(`${server}/api/m/feed?pack=${encodeURIComponent(pack)}&since=${since}`, {
      headers: etag ? { 'If-None-Match': etag } : {},
      signal: ctl.signal,
    }).finally(() => clearTimeout(timer));
    if (r.status === 304) return 'same';
    if (!r.ok) return 'fail';
    let maxSeq = since;
    let changed = false;
    for (const line of (await r.text()).split('\n')) {
      const m = /^(\d+)\s+(FW1\.\S+)/.exec(line.trim());
      if (!m) continue;
      maxSeq = Math.max(maxSeq, Number(m[1]));
      const res = await ingestCode(m[2], 'feed');
      if (res.ok && res.changed) changed = true;
    }
    await kvSet(`feedSeq:${pack}`, String(maxSeq));
    const tag = r.headers.get('ETag');
    if (tag) await kvSet(`feedEtag:${pack}`, tag);
    await kvSet('lastFeedOk', String(Date.now()));
    return changed ? 'new' : 'same';
  } catch {
    return 'fail';
  }
}
