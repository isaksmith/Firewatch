import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, BOARD_ADMIN_KEY, type AdminPost, type PendingMember, type StationAction } from '../api'
import { catMeta, useBoardPosts } from '../lib/board'
import { timeAgo } from '../lib/format'
import { useOperator } from '../lib/operator'

const PENDING_KEY = ['members-pending'] as const

const ACTION_LABEL: Record<StationAction, string> = {
  ack: 'Acknowledge',
  send: 'Send to alerts',
  page: 'Page',
  dismiss: 'Dismiss',
  resolve: 'Resolve',
}

function Mark({ children, tone = 'text-dim' }: { children: string; tone?: string }) {
  return <span className={`num text-[10px] tracking-[0.08em] uppercase ${tone}`}>{children}</span>
}

function PostRow({ post, child, focused }: { post: AdminPost; child?: boolean; focused: boolean }) {
  const qc = useQueryClient()
  const operator = useOperator()
  const ref = useRef<HTMLDivElement>(null)
  const [pageArmed, setPageArmed] = useState(false)
  const [pending, setPending] = useState<StationAction | null>(null)
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null)
  const m = catMeta(post.category)
  const open = post.status === 'open'
  const located = post.lat != null && post.lon != null
  const canSend = open && located && (post.category === 'fire' || post.category === 'smoke')

  useEffect(() => {
    if (!pageArmed) return
    const t = setTimeout(() => setPageArmed(false), 6000)
    return () => clearTimeout(t)
  }, [pageArmed])

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: 'nearest' })
  }, [focused])

  const station = useMutation({
    mutationFn: (action: StationAction) => api.boardStation(post.id, action, operator),
    onMutate: (action) => {
      setPending(action)
      setNote(null)
    },
    onSuccess: (res, action) => {
      setNote({ text: res.repeat ? 'Already done' : `${ACTION_LABEL[action]}: done` })
      qc.invalidateQueries({ queryKey: BOARD_ADMIN_KEY })
    },
    onError: (e: Error) => setNote({ text: e.message, bad: true }),
    onSettled: () => setPending(null),
  })

  function act(action: StationAction) {
    if (pending) return
    if (action === 'page' && !pageArmed) {
      setPageArmed(true)
      return
    }
    setPageArmed(false)
    station.mutate(action)
  }

  const busy = pending !== null
  return (
    <div
      ref={ref}
      className={`border-b border-line px-4 py-3 ${child ? 'ml-4 border-l border-l-line pl-3' : ''} ${focused ? 'bg-raised' : ''}`}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`label !text-[10px] ${m.text}`}>{m.label}</span>
        {post.flagged && <Mark tone="text-escalate">Flagged</Mark>}
        {post.held && <Mark tone="text-investigate">Held</Mark>}
        {post.estimated && <Mark>Approx location</Mark>}
        {post.hearsay && <Mark>Hearsay</Mark>}
        {!open && <Mark>{post.status}</Mark>}
        {post.event_id != null && <Mark tone="text-sample">{`Alert ${post.event_status ?? ''}`.trim()}</Mark>}
      </div>
      <p className="mt-1 text-[12.5px] leading-snug break-words text-text">{post.body}</p>
      <p className="num mt-1 text-[10px] text-dim">
        {post.author ?? 'Unknown'} · {timeAgo(post.created_at)} · {post.confirms} confirms · {post.notes ?? 0} notes
      </p>

      {open && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button type="button" className="btn !h-11" disabled={busy} onClick={() => act('ack')}>
            {pending === 'ack' ? 'Working…' : ACTION_LABEL.ack}
          </button>
          {canSend && (
            <button type="button" className="btn !h-11" disabled={busy} onClick={() => act('send')}>
              {pending === 'send' ? 'Working…' : ACTION_LABEL.send}
            </button>
          )}
          {canSend && (
            <button type="button" className={`btn !h-11 ${pageArmed ? 'btn-danger' : ''}`} disabled={busy} onClick={() => act('page')}>
              {pending === 'page' ? 'Working…' : pageArmed ? 'Tap again to page' : ACTION_LABEL.page}
            </button>
          )}
          {post.category === 'hazard' && (
            <button type="button" className="btn !h-11" disabled={busy} onClick={() => act('resolve')}>
              {pending === 'resolve' ? 'Working…' : ACTION_LABEL.resolve}
            </button>
          )}
          <button type="button" className="btn !h-11" disabled={busy} onClick={() => act('dismiss')}>
            {pending === 'dismiss' ? 'Working…' : ACTION_LABEL.dismiss}
          </button>
        </div>
      )}
      {pageArmed && <p className="mt-2 text-[12px] text-escalate">This sends a page to the whole department.</p>}
      {note && (
        <p role="status" className={`mt-2 text-[12px] leading-snug ${note.bad ? 'text-escalate' : 'text-muted'}`}>
          {note.text}
        </p>
      )}
    </div>
  )
}

function parseCoord(v: string, lo: number, hi: number): number | null {
  if (v.trim() === '') return null
  const n = Number(v)
  return Number.isFinite(n) && n >= lo && n <= hi ? n : null
}

interface Issued {
  id: number
  name: string
  link: string | null
  texted: boolean
}

function IssuedRow({ item, onDone }: { item: Issued; onDone: () => void }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    if (!item.link) return
    try {
      await navigator.clipboard.writeText(item.link)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="border-b border-line px-4 py-3">
      <p className="text-[12.5px] text-text">{item.name} approved.</p>
      {item.texted || !item.link ? (
        <p className="mt-1 text-[12px] text-muted">Link texted.</p>
      ) : (
        <>
          <p className="num mt-1 text-[11px] break-all text-text">{item.link}</p>
          <p className="mt-1 text-[12px] text-escalate">Keep this link private.</p>
          <div className="mt-2 flex gap-2">
            <button type="button" className="btn !h-11" onClick={copy}>
              {copied ? 'Copied' : 'Copy link'}
            </button>
          </div>
        </>
      )}
      <button type="button" className="btn mt-2 !h-11" onClick={onDone}>
        Done
      </button>
    </div>
  )
}

function PendingRow({ m, onIssued }: { m: PendingMember; onIssued: (i: Issued) => void }) {
  const qc = useQueryClient()
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const approve = useMutation({
    mutationFn: ({ la, lo }: { la: number; lo: number }) => api.approveMember(m.id, la, lo),
    onSuccess: (r) => {
      onIssued({ id: m.id, name: m.name, link: r.link, texted: r.texted })
      qc.invalidateQueries({ queryKey: PENDING_KEY })
    },
    onError: (e: Error) => setErr(e.message),
  })
  const reject = useMutation({
    mutationFn: () => api.rejectMember(m.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: PENDING_KEY }),
    onError: (e: Error) => setErr(e.message),
  })
  const busy = approve.isPending || reject.isPending

  function submit() {
    const la = parseCoord(lat, -90, 90)
    const lo = parseCoord(lon, -180, 180)
    if (la == null || lo == null) {
      setErr('Enter latitude (-90 to 90) and longitude (-180 to 180).')
      return
    }
    setErr(null)
    approve.mutate({ la, lo })
  }

  return (
    <div className="border-b border-line px-4 py-3">
      <p className="text-[12.5px] text-text">{m.name}</p>
      <p className="num text-[10px] text-dim">{m.phone}</p>
      <div className="mt-2 flex gap-2">
        <input
          className="field !h-11 w-full min-w-0"
          inputMode="decimal"
          placeholder="Lat"
          aria-label={`Latitude for ${m.name}`}
          value={lat}
          onChange={(e) => setLat(e.target.value)}
        />
        <input
          className="field !h-11 w-full min-w-0"
          inputMode="decimal"
          placeholder="Lon"
          aria-label={`Longitude for ${m.name}`}
          value={lon}
          onChange={(e) => setLon(e.target.value)}
        />
      </div>
      <div className="mt-2 flex gap-2">
        <button type="button" className="btn !h-11" disabled={busy} onClick={submit}>
          {approve.isPending ? 'Approving…' : 'Approve'}
        </button>
        <button type="button" className="btn !h-11" disabled={busy} onClick={() => reject.mutate()}>
          {reject.isPending ? 'Rejecting…' : 'Reject'}
        </button>
      </div>
      {err && (
        <p role="status" className="mt-2 text-[12px] text-escalate">
          {err}
        </p>
      )}
    </div>
  )
}

function PendingSection() {
  const [issued, setIssued] = useState<Issued[]>([])
  const pending = useQuery({ queryKey: PENDING_KEY, queryFn: api.pendingMembers, refetchInterval: 10_000, retry: false })
  const list = pending.data ?? []
  if (list.length === 0 && issued.length === 0) return null
  return (
    <div>
      <div className="flex h-7 items-center border-b border-line px-4">
        <span className="label">Pending members ({list.length})</span>
      </div>
      {issued.map((i) => (
        <IssuedRow key={i.id} item={i} onDone={() => setIssued((xs) => xs.filter((x) => x.id !== i.id))} />
      ))}
      {list.map((m) => (
        <PendingRow key={m.id} m={m} onIssued={(i) => setIssued((xs) => [...xs, i])} />
      ))}
    </div>
  )
}

export function CommunityBoard({ focusId, onClose }: { focusId: number | null; onClose: () => void }) {
  const posts = useBoardPosts()

  const { roots, kids } = useMemo(() => {
    const data = posts.data ?? []
    const ids = new Set(data.map((p) => p.id))
    const kids = new Map<number, AdminPost[]>()
    const roots: AdminPost[] = []
    for (const p of data) {
      if (p.parent_id != null && ids.has(p.parent_id)) kids.set(p.parent_id, [...(kids.get(p.parent_id) ?? []), p])
      else roots.push(p)
    }
    return { roots, kids }
  }, [posts.data])

  return (
    <aside
      aria-label="Community board"
      className="absolute inset-0 z-20 flex w-full flex-col bg-panel md:static md:inset-auto md:z-auto md:w-[400px] md:shrink-0 md:border-l md:border-line"
    >
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line pr-2 pl-4">
        <span className="label !text-muted">Community board</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close community board"
          className="flex h-6 w-6 items-center justify-center text-dim hover:bg-raised hover:text-text"
        >
          <X size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <PendingSection />
        {posts.isPending ? (
          <p className="label p-4">Loading…</p>
        ) : posts.isError ? (
          <div className="p-4">
            <p className="text-[12px] text-escalate">Could not load posts: {posts.error.message}</p>
            <button type="button" className="btn mt-2 !h-11" onClick={() => posts.refetch()}>
              Retry
            </button>
          </div>
        ) : roots.length === 0 ? (
          <p className="p-4 text-[12px] text-muted">No community posts in the last 24 hours.</p>
        ) : (
          roots.map((p) => (
            <div key={p.id}>
              <PostRow post={p} focused={p.id === focusId} />
              {(kids.get(p.id) ?? []).map((c) => (
                <PostRow key={c.id} post={c} child focused={c.id === focusId} />
              ))}
            </div>
          ))
        )}
      </div>
    </aside>
  )
}
