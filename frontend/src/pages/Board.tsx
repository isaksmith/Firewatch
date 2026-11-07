import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  boardApi,
  BoardError,
  getDeviceToken,
  isWellFormedToken,
  setDeviceToken,
  type BoardCategory,
  type BoardPost,
  type ConfirmKind,
  type StationAction,
} from '../api'
import { Mark } from '../components/ui'

const CATEGORIES: { key: BoardCategory; label: string }[] = [
  { key: 'fire', label: 'Fire' },
  { key: 'smoke', label: 'Smoke' },
  { key: 'hazard', label: 'Hazard' },
  { key: 'burn', label: 'Burn' },
  { key: 'other', label: 'Other' },
]
const MAX_BODY = 500

type Position = { lat: number; lon: number } | null

function getPosition(): Promise<Position> {
  return new Promise((resolve) => {
    if (!('geolocation' in navigator)) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }),
      () => resolve(null),
      { timeout: 8000, maximumAge: 60000 },
    )
  })
}

function ago(iso: string, now: number): string {
  const t = Date.parse(iso.endsWith('Z') || /[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z')
  if (Number.isNaN(t)) return ''
  const s = Math.max(0, Math.round((now - t) / 1000))
  if (s < 60) return 'just now'
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h} hr ago`
  return `${Math.round(h / 24)} d ago`
}

function seeText(n: number): string {
  if (n === 0) return 'No one has confirmed yet'
  return n === 1 ? '1 person sees it' : `${n} people see it`
}

function confirmMessage(reason: string, counted: boolean): string {
  if (counted) return 'Thanks. The fire district has your answer.'
  switch (reason) {
    case 'own_post':
      return 'This is your post.'
    case 'duplicate':
      return 'You already answered this one.'
    case 'too_far':
      return 'Saved, but you are too far away for it to count.'
    case 'no_position':
      return 'Saved, but we could not tell where you are, so it does not count.'
    case 'closed':
    case 'expired':
      return 'This post is no longer open.'
    default:
      return 'Saved.'
  }
}

function NewPost({ onPosted }: { onPosted: () => void }) {
  const [category, setCategory] = useState<BoardCategory>('fire')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [attach, setAttach] = useState(true)
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)

  async function submit() {
    if (busy || !body.trim()) return
    setBusy(true)
    setMsg(null)
    try {
      const pos = attach ? await getPosition() : null
      const r = await boardApi.post({ category, body: body.trim(), lat: pos?.lat ?? null, lon: pos?.lon ?? null, attach_location: attach })
      let text: string
      if (r.known) text = 'This one is already known and being watched.'
      else if (r.flagged && r.asked > 0) text = 'Posted. Neighbors nearby are being asked.'
      else if (r.flagged) text = 'Posted.'
      else if (r.event_id != null) text = 'Report received. The duty officer is being told.'
      else if (category === 'burn') text = 'Posted. To register a burn, text BURN.'
      else text = 'Posted to the board.'
      if (attach && !pos) text += ' This post has no location, because we could not get yours.'
      if (r.reissued) text += ' Your sign-in had expired, so this went in as a community post.'
      setMsg({ text })
      setBody('')
      onPosted()
    } catch (e) {
      setMsg({ text: `Could not post: ${e instanceof Error ? e.message : 'try again'}`, bad: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="border border-line bg-panel p-4">
      <h2 className="label mb-3">New post</h2>
      <div className="grid grid-cols-5 gap-1.5" role="group" aria-label="Category">
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            type="button"
            aria-pressed={category === c.key}
            onClick={() => setCategory(c.key)}
            className={`btn !h-11 !px-1 ${category === c.key ? 'btn-primary' : ''}`}
          >
            {c.label}
          </button>
        ))}
      </div>
      <textarea
        value={body}
        maxLength={MAX_BODY}
        onChange={(e) => setBody(e.target.value)}
        rows={4}
        placeholder="What do you see, and where?"
        aria-label="Post text"
        className="mt-3 block w-full resize-y border border-line-2 bg-void p-3 text-[16px] text-text outline-none focus:border-muted"
      />
      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="num text-[11px] text-muted">
          {body.length} / {MAX_BODY}
        </span>
      </div>
      <label className="mt-2 flex items-start gap-2 text-[13px] text-text">
        <input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} className="mt-[3px] h-4 w-4" />
        <span>
          Attach my location
          <span className="block text-[12px] text-muted">Helps the fire district find it. The public sees it rounded to about a kilometer.</span>
        </span>
      </label>
      <button type="button" onClick={submit} disabled={busy || !body.trim()} className="btn btn-primary mt-3 !h-11 w-full">
        {busy ? 'Posting' : 'Post'}
      </button>
      {msg && (
        <p role="status" className={`mt-3 text-[13px] leading-snug ${msg.bad ? 'text-escalate' : 'text-text'}`}>
          {msg.text}
        </p>
      )}
    </section>
  )
}

function PostCard({
  post,
  now,
  station,
  canPage,
  onChanged,
}: {
  post: BoardPost
  now: number
  station: boolean
  canPage: boolean
  onChanged: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null)
  const [pageArmed, setPageArmed] = useState(false)
  const open = post.status === 'open'

  useEffect(() => {
    if (!pageArmed) return
    const t = setTimeout(() => setPageArmed(false), 6000)
    return () => clearTimeout(t)
  }, [pageArmed])

  async function confirm(kind: ConfirmKind) {
    if (busy) return
    setBusy(kind)
    setNote(null)
    try {
      const pos = await getPosition()
      const r = await boardApi.confirm(post.id, { kind, lat: pos?.lat ?? null, lon: pos?.lon ?? null })
      setNote({ text: confirmMessage(r.reason, r.counted) + (r.reissued ? ' Your sign-in had expired, so this went in as a community post.' : '') })
      onChanged()
    } catch (e) {
      setNote({ text: `Could not send: ${e instanceof Error ? e.message : 'try again'}`, bad: true })
    } finally {
      setBusy(null)
    }
  }

  async function act(action: StationAction) {
    if (busy) return
    if (action === 'page' && !pageArmed) {
      setPageArmed(true)
      return
    }
    setPageArmed(false)
    setBusy(action)
    setNote(null)
    try {
      await boardApi.station(post.id, action)
      setNote({ text: 'Done.' })
      onChanged()
    } catch (e) {
      const text = e instanceof BoardError || e instanceof Error ? e.message : 'Could not do that.'
      setNote({ text, bad: true })
    } finally {
      setBusy(null)
    }
  }

  const cat = CATEGORIES.find((c) => c.key === post.category)?.label ?? post.category
  const hot = post.category === 'fire' || post.category === 'smoke'

  return (
    <article className={`border bg-panel p-4 ${post.flagged ? 'border-escalate/70' : 'border-line'}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`num border px-1.5 py-[1px] text-[10px] font-medium tracking-[0.14em] uppercase ${hot ? 'border-escalate/60 text-escalate' : 'border-line-2 text-muted'}`}>
          {cat}
        </span>
        {post.flagged && <span className="num bg-escalate px-1.5 py-[1px] text-[10px] font-semibold tracking-[0.14em] text-white uppercase">Flagged</span>}
        {post.estimated && <span className="num text-[10px] tracking-[0.14em] text-investigate uppercase">Estimated location</span>}
        {post.hearsay && <span className="num text-[10px] tracking-[0.14em] text-investigate uppercase">Secondhand</span>}
        {station && post.held && <span className="num text-[10px] tracking-[0.14em] text-degraded uppercase">Held</span>}
        {station && post.event_status && <span className="num text-[10px] tracking-[0.14em] text-sample uppercase">Event: {post.event_status}</span>}
      </div>

      {post.badge && (
        <p className="mt-2 border border-investigate/60 bg-investigate/10 px-2 py-1.5 text-[13px] leading-snug font-medium text-investigate">{post.badge}</p>
      )}

      <p className="mt-2 text-[15px] leading-snug break-words whitespace-pre-wrap text-text">{post.body}</p>

      <p className="mt-2 text-[12px] text-muted">
        {post.author ?? 'A neighbor'} <span className="text-dim">·</span> {ago(post.created_at, now)} <span className="text-dim">·</span>{' '}
        <span className="text-text">{seeText(post.confirms)}</span>
      </p>

      {typeof post.notes === 'number' && post.notes > 0 && (
        <p className="mt-2 text-[12px] text-muted">
          {post.notes} other {post.notes === 1 ? 'answer' : 'answers'}
        </p>
      )}

      {open && (
        <div className="mt-3 grid grid-cols-1 gap-1.5 sm:grid-cols-3">
          <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => confirm('see')}>
            I see it too
          </button>
          <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => confirm('not_seeing')}>
            Not seeing it
          </button>
          <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => confirm('burn')}>
            It's a controlled burn
          </button>
        </div>
      )}

      {station && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="label mb-2">Fire district</p>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => act('ack')}>
              Acknowledge
            </button>
            <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => act('send')}>
              Send to alerts
            </button>
            <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => act('dismiss')}>
              Dismiss
            </button>
            {post.category === 'hazard' && (
              <button type="button" className="btn !h-11" disabled={busy !== null} onClick={() => act('resolve')}>
                Resolve hazard
              </button>
            )}
            {canPage && (
              <button
                type="button"
                className={`btn !h-11 ${pageArmed ? 'btn-danger' : ''}`}
                disabled={busy !== null}
                onClick={() => act('page')}
              >
                {pageArmed ? 'Tap again to page' : 'Page'}
              </button>
            )}
          </div>
          {pageArmed && <p className="mt-2 text-[12px] text-escalate">This sends a page to the whole department.</p>}
        </div>
      )}

      {note && (
        <p role="status" className={`mt-3 text-[13px] leading-snug ${note.bad ? 'text-escalate' : 'text-text'}`}>
          {note.text}
        </p>
      )}
    </article>
  )
}

export function Board() {
  const qc = useQueryClient()
  const [now, setNow] = useState(() => Date.now())
  const lastGood = useRef<BoardPost[] | null>(null)

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])

  const [pending, setPending] = useState<{ token: string; name: string } | null>(null)
  const [linkMsg, setLinkMsg] = useState<string | null>(null)

  useEffect(() => {
    let m: RegExpMatchArray | null = null
    try {
      m = window.location.hash.match(/[#&]d=([^&]+)/)
      if (m) history.replaceState(null, '', window.location.pathname + window.location.search)
    } catch {
      /* ignore */
    }
    if (!m) return
    let t: string
    try {
      t = decodeURIComponent(m[1])
    } catch {
      return
    }
    if (!isWellFormedToken(t)) return
    const stored = getDeviceToken()
    if (stored === t) return
    if (!stored) {
      setDeviceToken(t)
      qc.invalidateQueries({ queryKey: ['board-me'] })
      qc.invalidateQueries({ queryKey: ['board-posts'] })
      return
    }
    boardApi
      .me(t)
      .then((r) => {
        if (r) setPending({ token: t, name: r.name ?? 'this account' })
      })
      .catch((e) => {
        setLinkMsg(e instanceof BoardError && e.status === 401 ? 'That link is no longer valid.' : 'Could not check that link.')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function switchTo() {
    if (!pending) return
    setDeviceToken(pending.token)
    setPending(null)
    qc.invalidateQueries({ queryKey: ['board-me'] })
    qc.invalidateQueries({ queryKey: ['board-posts'] })
  }

  const me = useQuery({
    queryKey: ['board-me'],
    queryFn: () => boardApi.me(),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const posts = useQuery({
    queryKey: ['board-posts'],
    queryFn: boardApi.posts,
    refetchInterval: 15_000,
  })

  if (posts.data) lastGood.current = posts.data
  const list = posts.data ?? lastGood.current
  const station = !!me.data?.station
  const canPage = me.data?.role === 'duty_officer' || me.data?.role === 'chief'

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['board-posts'] })
    qc.invalidateQueries({ queryKey: ['board-me'] })
  }

  return (
    <div className="h-full overflow-y-auto bg-bg">
      <header className="sticky top-0 z-10 border-b border-line bg-void">
        <div className="mx-auto flex h-11 max-w-[640px] items-center gap-3 px-4">
          <Mark size={16} />
          <span className="num text-[13px] font-semibold tracking-[0.28em]">FIREWATCH</span>
          <span className="label">Community board</span>
          <Link to="/" className="num ml-auto inline-flex min-h-11 items-center text-[10px] tracking-[0.14em] text-dim uppercase hover:text-muted">
            Console
          </Link>
        </div>
        <p className="border-t border-escalate/60 bg-escalate px-4 py-2 text-center text-[14px] font-semibold text-white">
          Call 911 first if anyone is in danger.
        </p>
      </header>

      <main className="mx-auto flex max-w-[640px] flex-col gap-4 px-4 py-4">
        {pending && (
          <div role="status" className="flex flex-wrap items-center gap-2 border border-investigate/60 bg-investigate/10 px-3 py-2 text-[13px] text-text">
            <span className="flex-1">This link signs you in as {pending.name}. Switch to it?</span>
            <button type="button" className="btn btn-primary !h-11" onClick={switchTo}>
              Switch
            </button>
            <button type="button" className="btn !h-11" onClick={() => setPending(null)}>
              Keep current
            </button>
          </div>
        )}
        {linkMsg && (
          <p role="status" className="border border-escalate/60 px-3 py-2 text-[13px] text-escalate">
            {linkMsg}
          </p>
        )}
        {me.data && (me.data.member || me.data.station) && (
          <p className="text-[12px] text-muted">
            Signed in as <span className="text-text">{me.data.name}</span>
            {station ? ' (fire district)' : ''}
          </p>
        )}

        <NewPost onPosted={refresh} />

        <section className="flex flex-col gap-3" aria-label="Posts">
          <h2 className="label">Last 24 hours</h2>
          {posts.isError && list && (
            <p role="status" className="border border-investigate/60 px-3 py-2 text-[13px] text-investigate">
              Could not refresh. Showing the last list we got.
            </p>
          )}
          {posts.isLoading && <p className="text-[13px] text-muted">Loading posts.</p>}
          {posts.isError && !list && (
            <p role="status" className="border border-escalate/60 px-3 py-2 text-[13px] text-escalate">
              Could not load posts. We will keep trying.
            </p>
          )}
          {list && list.length === 0 && <p className="text-[13px] text-muted">Nothing posted in the last 24 hours.</p>}
          {list?.map((p) => (
            <PostCard key={p.id} post={p} now={now} station={station} canPage={canPage} onChanged={refresh} />
          ))}
        </section>
      </main>
    </div>
  )
}
