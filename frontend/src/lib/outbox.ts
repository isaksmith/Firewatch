import { boardApi, BoardError, type BoardCategory, type NewPostBody } from '../api'

// Posts made with no signal. Records and their shrunk photos live in IndexedDB; if that is
// unavailable they live in page memory and are lost when the page closes.

/** The page does not know the district's text number yet. Set it when an API gives one. */
export const DISTRICT_TEXT_NUMBER: string | null = null

export const MAX_AGE_MS = 2 * 60 * 60 * 1000
const DB_NAME = 'firewatch-outbox'
const STORE = 'posts'

export interface Saved {
  key: string
  category: BoardCategory
  body: string
  lat: number | null
  lon: number | null
  attach: boolean
  bearing?: number
  miles?: number
  compass?: boolean
  savedAt: number
  photo: Blob | null
  textSent: boolean
  postId: number | null
}

export type RowMode = 'waiting' | 'limited' | 'rejected' | 'expired'
export interface RowState {
  mode: RowMode
  text?: string
}

const memory = new Map<string, Saved>()
let dbPromise: Promise<IDBDatabase | null> | null = null

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve) => {
    try {
      if (typeof indexedDB === 'undefined') return resolve(null)
      const req = indexedDB.open(DB_NAME, 1)
      req.onupgradeneeded = () => {
        req.result.createObjectStore(STORE, { keyPath: 'key' })
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => resolve(null)
      req.onblocked = () => resolve(null)
    } catch {
      resolve(null)
    }
  })
  return dbPromise
}

function run<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T | undefined> {
  return openDb().then(
    (db) =>
      new Promise<T | undefined>((resolve, reject) => {
        if (!db) return reject(new Error('no storage'))
        try {
          const tx = db.transaction(STORE, mode)
          const req = fn(tx.objectStore(STORE))
          tx.oncomplete = () => resolve(req.result)
          tx.onerror = () => reject(tx.error)
          tx.onabort = () => reject(tx.error)
        } catch (e) {
          reject(e)
        }
      }),
  )
}

/** True when the record reached IndexedDB; false when it is only in page memory. */
export async function saveRecord(r: Saved): Promise<boolean> {
  try {
    await run('readwrite', (s) => s.put(r))
    memory.delete(r.key)
    return true
  } catch {
    memory.set(r.key, r)
    return false
  }
}

export async function removeRecord(key: string): Promise<void> {
  memory.delete(key)
  try {
    await run('readwrite', (s) => s.delete(key))
  } catch {
    /* storage unavailable: nothing more to remove */
  }
}

export async function listRecords(): Promise<Saved[]> {
  let stored: Saved[] = []
  try {
    stored = ((await run('readonly', (s) => s.getAll())) as Saved[] | undefined) ?? []
  } catch {
    stored = []
  }
  const seen = new Set(stored.map((r) => r.key))
  const all = [...stored, ...[...memory.values()].filter((r) => !seen.has(r.key))]
  return all.sort((a, b) => a.savedAt - b.savedAt)
}

export function newClientKey(): string {
  const bytes = new Uint8Array(16)
  try {
    crypto.getRandomValues(bytes)
  } catch {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export const savedAtText = (ms: number) => {
  const d = new Date(ms)
  return `Saved ${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${d.getHours() < 12 ? 'AM' : 'PM'}`
}

export const firstLine = (body: string) => {
  const line = body.split('\n').find((l) => l.trim()) ?? body
  return line.length > 80 ? `${line.slice(0, 77)}...` : line
}

/** Post ids that came from this phone's compass flow, so its card can say how the spot was found. */
const COMPASS_KEY = 'fw-compass-posts'
export function compassPostIds(): number[] {
  try {
    const v = JSON.parse(localStorage.getItem(COMPASS_KEY) ?? '[]')
    return Array.isArray(v) ? v.filter((n) => typeof n === 'number') : []
  } catch {
    return []
  }
}
export function rememberCompassPost(id: number) {
  try {
    localStorage.setItem(COMPASS_KEY, JSON.stringify([...compassPostIds(), id].slice(-50)))
  } catch {
    /* per-viewer convenience only */
  }
}

export function bodyFor(r: Saved, now: number): NewPostBody {
  const b: NewPostBody = {
    category: r.category,
    body: r.body,
    lat: r.lat,
    lon: r.lon,
    attach_location: r.attach,
    client_key: r.key,
    queued_min: Math.max(0, Math.min(120, Math.round((now - r.savedAt) / 60000))),
  }
  if (r.attach && r.lat != null && r.lon != null && r.bearing != null && r.miles != null) {
    b.bearing = r.bearing
    b.miles = r.miles
  }
  return b
}

type Outcome = 'sent' | 'stay' | 'network' | RowState

function classify(e: unknown): Outcome {
  if (!(e instanceof BoardError)) return 'network'
  if (e.status === 429) return { mode: 'limited', text: e.message }
  if (e.status >= 500) return 'stay'
  if (e.status >= 400) return { mode: 'rejected', text: e.message }
  return 'stay'
}

// ---- the single-flight sender ----

let running = false
let again: string | null | undefined
const states = new Map<string, RowState>()
export const rowState = (key: string): RowState => states.get(key) ?? { mode: 'waiting' }

export interface DrainHooks {
  /** A post text reached the server (or was already there). */
  onTextSent: (r: Saved, postId: number) => void
  /** A row finished completely and should show "Sent." */
  onDone: (r: Saved) => void
  /** Row states or the stored list changed. */
  onChange: () => void
}

/**
 * Send waiting posts oldest first, one at a time. `only` is a row the person tapped Send now on.
 * Calls made while a round runs are folded into one more round after it, so the same row is never in flight twice.
 */
export async function drain(hooks: DrainHooks, only?: string): Promise<void> {
  if (running) {
    again = only === undefined ? (again ?? null) : only
    return
  }
  running = true
  try {
    let next: string | null | undefined = only ?? null
    do {
      again = undefined
      await round(hooks, next)
      next = again
    } while (next !== undefined)
  } finally {
    running = false
  }
}

async function round(hooks: DrainHooks, manual: string | null) {
  const rows = await listRecords()
  for (const r of rows) {
    if (manual !== null && r.key !== manual) continue
    const st = rowState(r.key)
    const isManual = manual === r.key
    if (!isManual && st.mode !== 'waiting') continue
    if (isManual && (st.mode === 'rejected' || st.mode === 'expired')) continue
    if (!isManual && navigator.onLine === false) return
    if (!r.textSent && Date.now() - r.savedAt > MAX_AGE_MS) {
      states.set(r.key, { mode: 'expired' })
      hooks.onChange()
      continue
    }
    states.set(r.key, { mode: 'waiting' })
    let rec = r
    if (!r.textSent) {
      try {
        const res = await boardApi.post(bodyFor(r, Date.now()))
        rec = { ...r, textSent: true, postId: res.post_id }
        if (r.compass) rememberCompassPost(res.post_id)
        hooks.onTextSent(rec, res.post_id)
        if (!r.photo) {
          await removeRecord(r.key)
          hooks.onDone(rec)
          continue
        }
        await saveRecord({ ...rec })
        hooks.onDone(rec)
      } catch (e) {
        const o = classify(e)
        if (o === 'network') {
          hooks.onChange()
          return
        }
        if (typeof o === 'object') states.set(r.key, o)
        hooks.onChange()
        continue
      }
    }
    if (rec.photo && rec.postId != null) {
      try {
        await boardApi.uploadPhoto(rec.postId, rec.photo)
        await removeRecord(rec.key)
        hooks.onChange()
      } catch (e) {
        if (e instanceof BoardError && e.status === 409) {
          await removeRecord(rec.key)
          hooks.onChange()
          continue
        }
        const o = classify(e)
        if (o === 'network') {
          hooks.onChange()
          return
        }
        if (typeof o === 'object') states.set(rec.key, o)
        hooks.onChange()
      }
    }
  }
}

export async function deleteRow(key: string) {
  states.delete(key)
  await removeRecord(key)
}
