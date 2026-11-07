import { useSyncExternalStore } from 'react'

const KEY = 'fw.lowData'
const SLOW_MS = 2000
const SLOW_TYPES = ['slow-2g', '2g', '3g']

interface State {
  on: boolean
  /** True when the app switched itself on, so the banner can offer Undo. */
  auto: boolean
}

function read(): '1' | '0' | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === '1' || v === '0' ? v : null
  } catch {
    return null
  }
}

function write(v: '1' | '0') {
  try {
    localStorage.setItem(KEY, v)
  } catch {
    /* storage can be blocked; the choice just lasts until reload */
  }
}

function slowConnection(): boolean {
  const c = (navigator as Navigator & { connection?: { saveData?: boolean; effectiveType?: string } }).connection
  return !!c && (c.saveData === true || SLOW_TYPES.includes(c.effectiveType ?? ''))
}

function initial(): State {
  const saved = read()
  if (saved) return { on: saved === '1', auto: false }
  if (slowConnection()) {
    write('1')
    return { on: true, auto: true }
  }
  return { on: false, auto: false }
}

let state: State = initial()
let slowStreak = 0
const listeners = new Set<() => void>()

function set(next: State) {
  state = next
  listeners.forEach((l) => l())
}

export function setLowData(on: boolean) {
  write(on ? '1' : '0')
  slowStreak = 0
  set({ on, auto: false })
}

/** Called with how long each alerts fetch took; two slow ones in a row switch low-data mode on. */
export function noteFetchTime(ms: number) {
  slowStreak = ms > SLOW_MS ? slowStreak + 1 : 0
  if (slowStreak >= 2 && !state.on && read() !== '0') {
    write('1')
    set({ on: true, auto: true })
  }
}

/** A failed alerts fetch counts toward the same streak as a slow one. Offline is not slow, so it is ignored. */
export function noteFetchFailure() {
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return
  noteFetchTime(Infinity)
}

export function dismissAutoBanner() {
  set({ ...state, auto: false })
}

export function useLowData(): State {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => state,
  )
}
