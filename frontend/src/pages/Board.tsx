import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  boardApi,
  boardPhotoUrl,
  BoardError,
  type Burn,
  getDeviceToken,
  isWellFormedToken,
  setDeviceToken,
  type BoardCategory,
  type BoardPost,
  type ConfirmKind,
  type StationAction,
} from '../api'
import { Mark } from '../components/ui'
import { burnCoords, burnDistanceText, kmAndBearing, plainAge, threadLine } from '../lib/board'

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

const MAX_PHOTO_BYTES = 2 * 1024 * 1024
const MAX_VIDEO_SECONDS = 15

function canvasJpeg(bmp: ImageBitmap, longest: number, quality: number): Promise<Blob | null> {
  const scale = Math.min(1, longest / Math.max(bmp.width, bmp.height))
  const c = document.createElement('canvas')
  c.width = Math.max(1, Math.round(bmp.width * scale))
  c.height = Math.max(1, Math.round(bmp.height * scale))
  const ctx = c.getContext('2d')
  if (!ctx) return Promise.resolve(null)
  ctx.drawImage(bmp, 0, 0, c.width, c.height)
  return new Promise((resolve) => c.toBlob(resolve, 'image/jpeg', quality))
}

/** Shrink on the phone. Redrawing through a canvas also drops EXIF, including location. */
async function shrinkPhoto(file: File): Promise<Blob> {
  const bmp = await createImageBitmap(file)
  try {
    let out = await canvasJpeg(bmp, 1600, 0.75)
    if (out && out.size > MAX_PHOTO_BYTES) out = await canvasJpeg(bmp, 1280, 0.6)
    if (!out) throw new Error('no blob')
    return out
  } finally {
    bmp.close()
  }
}

function uploadMessage(e: unknown): { text: string; retry: boolean } {
  if (e instanceof BoardError) {
    if (e.status === 413) return { text: 'That photo is too large. Try again with a new one.', retry: false }
    if (e.status === 415) return { text: 'That file is not a photo we can use.', retry: false }
    if (e.status === 429) return { text: e.message, retry: true }
  }
  return { text: 'The photo did not send.', retry: true }
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

const BURN_NEAR_EXTRA_KM = 1

/** Open fire or smoke posts within the burn's radius plus 1 km (rounded points, same as the server's cue). */
function nearbyPostIds(burn: Burn, posts: BoardPost[] | null): number[] {
  return (posts ?? [])
    .filter(
      (p) =>
        p.status === 'open' &&
        (p.category === 'fire' || p.category === 'smoke') &&
        p.lat != null &&
        p.lon != null &&
        kmAndBearing(burn, { lat: p.lat, lon: p.lon }).km <= burn.radius_km + BURN_NEAR_EXTRA_KM,
    )
    .map((p) => p.id)
}

function BurnsToday({
  burns,
  posts,
  position,
  locState,
  onAskLocation,
}: {
  burns: Burn[]
  posts: BoardPost[] | null
  position: Position
  locState: 'idle' | 'asking' | 'off'
  onAskLocation: () => void
}) {
  const n = burns.length
  function jump(burn: Burn) {
    const ids = nearbyPostIds(burn, posts)
    if (!ids.length) return
    const el = document.getElementById(`post-${Math.max(...ids)}`)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  return (
    <section className="border border-line bg-panel p-4" aria-label="Burns today">
      <h2 className="label mb-2">Burns today ({n})</h2>
      {n === 0 && <p className="text-[13px] text-muted">No controlled burns registered today.</p>}
      {n > 0 && (
        <ul className="flex flex-col gap-2">
          {burns.map((b, i) => {
            const has = b.reports_nearby && nearbyPostIds(b, posts).length > 0
            const body = (
              <>
                <span className="block text-[15px] font-medium text-text">Controlled burn</span>
                <span className="block text-[13px] break-words text-muted">
                  {position ? burnDistanceText(position, b) : burnCoords(b)}
                </span>
                <span className="block text-[12px] text-muted">Registered {b.registered_at}</span>
                {b.reports_nearby && <span className="mt-1 block text-[13px] font-medium text-investigate">Reports nearby. Check the posts below.</span>}
              </>
            )
            return (
              <li key={`${b.lat},${b.lon},${i}`} className="border border-line-2 bg-void">
                {has ? (
                  <button type="button" onClick={() => jump(b)} className="block min-h-11 w-full p-3 text-left">
                    {body}
                  </button>
                ) : (
                  <div className="p-3">{body}</div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {n > 0 && !position && (
        <p className="mt-2 text-[13px]">
          {locState === 'off' ? (
            <span className="text-muted">Location is off. Distances need it.</span>
          ) : (
            <button type="button" className="min-h-11 text-text underline" disabled={locState === 'asking'} onClick={onAskLocation}>
              Show distance from me
            </button>
          )}
        </p>
      )}
      <p className="mt-2 text-[12px] text-muted">A registered burn can still escape. If it looks out of control, call 911.</p>
    </section>
  )
}

function NewPost({ onPosted, onVideoSaved }: { onPosted: () => void; onVideoSaved: (postId: number, url: string) => void }) {
  const [category, setCategory] = useState<BoardCategory>('fire')
  const [body, setBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [attach, setAttach] = useState(true)
  const [msg, setMsg] = useState<{ text: string; bad?: boolean } | null>(null)
  const [photo, setPhoto] = useState<{ blob: Blob; url: string } | null>(null)
  const [video, setVideo] = useState<string | null>(null)
  const [retry, setRetry] = useState<{ postId: number; blob: Blob; base: string } | null>(null)
  const photoInput = useRef<HTMLInputElement>(null)
  const videoInput = useRef<HTMLInputElement>(null)
  const live = useRef<{ photo: string | null; video: string | null }>({ photo: null, video: null })
  live.current = { photo: photo?.url ?? null, video }

  // Revoke blob URLs still held by the form when the page goes away.
  useEffect(
    () => () => {
      if (live.current.photo) URL.revokeObjectURL(live.current.photo)
      if (live.current.video) URL.revokeObjectURL(live.current.video)
    },
    [],
  )

  function clearPhoto() {
    if (photo) URL.revokeObjectURL(photo.url)
    setPhoto(null)
  }
  function clearVideo() {
    if (video) URL.revokeObjectURL(video)
    setVideo(null)
  }

  async function pickPhoto(file: File | undefined) {
    if (!file) return
    try {
      const blob = await shrinkPhoto(file)
      if (photo) URL.revokeObjectURL(photo.url)
      setPhoto({ blob, url: URL.createObjectURL(blob) })
      setMsg(null)
    } catch {
      setMsg({ text: 'Could not read that photo.', bad: true })
    }
  }

  function pickVideo(file: File | undefined) {
    if (!file) return
    const url = URL.createObjectURL(file)
    const probe = document.createElement('video')
    probe.preload = 'metadata'
    probe.onloadedmetadata = () => {
      if (!(probe.duration <= MAX_VIDEO_SECONDS)) {
        URL.revokeObjectURL(url)
        setMsg({ text: 'Keep videos under 15 seconds.', bad: true })
        return
      }
      if (video) URL.revokeObjectURL(video)
      setVideo(url)
      setMsg(null)
    }
    probe.onerror = () => {
      URL.revokeObjectURL(url)
      setMsg({ text: 'Could not read that video.', bad: true })
    }
    probe.src = url
  }

  async function sendPhoto(postId: number, blob: Blob, base: string) {
    setRetry(null)
    setMsg({ text: `${base} Sending photo...` })
    try {
      await boardApi.uploadPhoto(postId, blob)
      setMsg({ text: `${base} Photo sent.` })
      onPosted()
    } catch (e) {
      const m = uploadMessage(e)
      setMsg({ text: `${base} ${m.text}`, bad: true })
      if (m.retry) setRetry({ postId, blob, base })
    }
  }

  async function submit() {
    if (busy || !body.trim()) return
    setBusy(true)
    setMsg(null)
    setRetry(null)
    try {
      const pos = attach ? await getPosition() : null
      const r = await boardApi.post({ category, body: body.trim(), lat: pos?.lat ?? null, lon: pos?.lon ?? null, attach_location: attach })
      let text: string
      if (r.known) text = 'This one is already known and being watched.'
      else if (r.flagged && r.asked > 0) text = 'Posted. Neighbors nearby are being asked.'
      else if (r.flagged) text = 'Posted.'
      else if (r.alerted) text = 'Report received. The duty officer is being told.'
      else if (category === 'burn') text = 'Posted. To register a burn, text BURN.'
      else text = 'Posted to the board.'
      if (r.used_home) text += ' We could not get your location, so we used your home address on file.'
      else if (attach && !pos) text += ' This post has no location, because we could not get yours.'
      if (r.reissued) text += ' Your sign-in had expired, so this went in as a community post.'
      if (video) {
        text += ' Video saved on this phone. It sends when you have better signal.'
        // The blob URL now belongs to the board page, which shows it on the author's card.
        onVideoSaved(r.post_id, video)
        setVideo(null)
      }
      setMsg({ text })
      setBody('')
      onPosted()
      if (photo) {
        const sending = photo
        clearPhoto()
        await sendPhoto(r.post_id, sending.blob, text)
      }
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
      <div className="mt-3 grid grid-cols-2 gap-1.5">
        <button type="button" className="btn !h-11" disabled={busy} onClick={() => photoInput.current?.click()}>
          Add photo
        </button>
        <button type="button" className="btn !h-11" disabled={busy} onClick={() => videoInput.current?.click()}>
          Add video
        </button>
      </div>
      <input
        ref={photoInput}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        aria-label="Photo file"
        onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          void pickPhoto(f)
        }}
      />
      {/* The video upload is a mock on purpose: the file stays in page memory and nothing reaches the server. */}
      <input
        ref={videoInput}
        type="file"
        accept="video/*"
        capture="environment"
        className="hidden"
        aria-label="Video file"
        onChange={(e) => {
          const f = e.target.files?.[0]
          e.target.value = ''
          pickVideo(f)
        }}
      />
      {photo && (
        <div className="mt-3">
          <div className="relative inline-block max-w-full">
            <img src={photo.url} alt="Photo to send" className="block max-h-40 max-w-full border border-line" />
            <button type="button" aria-label="Remove photo" onClick={clearPhoto} className="btn absolute top-1 right-1 !h-11 !w-11 !px-0">
              x
            </button>
          </div>
          <p className="mt-1 text-[12px] text-muted">Location data is removed from photos.</p>
        </div>
      )}
      {video && (
        <div className="mt-3">
          <div className="relative inline-block max-w-full">
            <video src={video} muted playsInline controls className="block max-h-40 max-w-full border border-line" />
            <button type="button" aria-label="Remove video" onClick={clearVideo} className="btn absolute top-1 right-1 !h-11 !w-11 !px-0">
              x
            </button>
          </div>
          <p className="mt-1 text-[12px] text-muted">Video sends when you have better signal. For now it stays on this phone.</p>
        </div>
      )}
      <button type="button" onClick={submit} disabled={busy || !body.trim()} className="btn btn-primary mt-3 !h-11 w-full">
        {busy ? 'Posting' : 'Post'}
      </button>
      {msg && (
        <p role="status" className={`mt-3 text-[13px] leading-snug ${msg.bad ? 'text-escalate' : 'text-text'}`}>
          {msg.text}
        </p>
      )}
      {retry && (
        <button type="button" className="btn mt-2 !h-11" onClick={() => void sendPhoto(retry.postId, retry.blob, retry.base)}>
          Try again
        </button>
      )}
    </section>
  )
}

function PostCard({
  post,
  station,
  canPage,
  videoUrl,
  onChanged,
}: {
  post: BoardPost
  station: boolean
  canPage: boolean
  videoUrl?: string
  onChanged: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null)
  const [pageArmed, setPageArmed] = useState(false)
  const [zoom, setZoom] = useState(false)
  const open = post.status === 'open'

  useEffect(() => {
    if (!pageArmed) return
    const t = setTimeout(() => setPageArmed(false), 6000)
    return () => clearTimeout(t)
  }, [pageArmed])

  useEffect(() => {
    if (!zoom) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setZoom(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [zoom])

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
    <article id={`post-${post.id}`} className={`scroll-mt-20 border bg-panel p-4 ${post.flagged ? 'border-escalate/70' : 'border-line'}`}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`num border px-1.5 py-[1px] text-[10px] font-medium tracking-[0.14em] uppercase ${hot ? 'border-escalate/60 text-escalate' : 'border-line-2 text-muted'}`}>
          {cat}
        </span>
        {post.flagged && <span className="num bg-escalate px-1.5 py-[1px] text-[10px] font-semibold tracking-[0.14em] text-white uppercase">Flagged</span>}
        {post.unconfirmed && <span className="num border border-line-2 px-1.5 py-[1px] text-[10px] font-medium tracking-[0.14em] text-muted uppercase">Unconfirmed</span>}
        {post.estimated && <span className="num text-[10px] tracking-[0.14em] text-investigate uppercase">Estimated location</span>}
        {post.hearsay && <span className="num text-[10px] tracking-[0.14em] text-investigate uppercase">Secondhand</span>}
        {station && post.held && <span className="num text-[10px] tracking-[0.14em] text-degraded uppercase">Held</span>}
        {station && post.event_status && <span className="num text-[10px] tracking-[0.14em] text-sample uppercase">Event: {post.event_status}</span>}
      </div>

      {post.badge && (
        <p className="mt-2 border border-investigate/60 bg-investigate/10 px-2 py-1.5 text-[13px] leading-snug font-medium text-investigate">{post.badge}</p>
      )}

      <p className="mt-2 text-[15px] leading-snug break-words whitespace-pre-wrap text-text">{post.body}</p>

      {post.has_photo && (
        <button type="button" aria-label="Enlarge photo" onClick={() => setZoom(true)} className="mt-2 block min-h-11 w-full">
          <img src={boardPhotoUrl(post.id)} alt="Photo from the reporter" loading="lazy" className="block h-auto w-full border border-line" />
        </button>
      )}
      {zoom && (
        <button
          type="button"
          aria-label="Close photo"
          onClick={() => setZoom(false)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-void/90 p-2"
        >
          <img src={boardPhotoUrl(post.id)} alt="Photo from the reporter" className="max-h-full max-w-full object-contain" />
        </button>
      )}
      {videoUrl && (
        <div className="mt-2">
          <p className="label mb-1">Video waiting to send</p>
          <video src={videoUrl} muted playsInline controls className="block max-h-48 max-w-full border border-line" />
        </div>
      )}

      <p className="mt-2 text-[12px] text-muted">
        {post.author ?? 'A neighbor'} <span className="text-dim">·</span> {plainAge(post)} <span className="text-dim">·</span>{' '}
        <span className="text-text">{seeText(post.confirms)}</span>
      </p>

      {threadLine(post) && <p className="mt-2 text-[12px] text-muted">{threadLine(post)}</p>}

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
  const lastGood = useRef<BoardPost[] | null>(null)
  // Mock video: blob URLs for this phone's own posts, page memory only.
  const [videos, setVideos] = useState<Record<number, string>>({})
  const videosRef = useRef(videos)
  videosRef.current = videos
  useEffect(
    () => () => {
      Object.values(videosRef.current).forEach((u) => URL.revokeObjectURL(u))
    },
    [],
  )

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

  const burnsQ = useQuery({
    queryKey: ['board-burns'],
    queryFn: boardApi.burns,
    refetchInterval: 15_000,
  })
  const burnsGood = useRef<Burn[] | null>(null)
  if (burnsQ.data) burnsGood.current = burnsQ.data
  const burnList = burnsQ.data ?? burnsGood.current
  // Never asked on load: only the "Show distance from me" link sets this.
  const [position, setPosition] = useState<Position>(null)
  const [locState, setLocState] = useState<'idle' | 'asking' | 'off'>('idle')
  async function askLocation() {
    setLocState('asking')
    const p = await getPosition()
    if (p) {
      setPosition(p)
      setLocState('idle')
    } else setLocState('off')
  }

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

        <NewPost onPosted={refresh} onVideoSaved={(id, url) => setVideos((v) => ({ ...v, [id]: url }))} />

        {burnList && <BurnsToday burns={burnList} posts={list} position={position} locState={locState} onAskLocation={() => void askLocation()} />}

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
            <PostCard key={p.id} post={p} station={station} canPage={canPage} videoUrl={videos[p.id]} onChanged={refresh} />
          ))}
        </section>
      </main>
    </div>
  )
}
