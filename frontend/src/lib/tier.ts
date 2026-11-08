import { useSyncExternalStore } from 'react'

/**
 * Which product tier the console shows. A view setting only: the server runs everything either way, and this
 * hides what a tier wouldn't have.
 *
 * - free: FireWatchOS with FireCast (ML score and expected-loss model) and FireWatch Mobile.
 * - paid: adds FireCast Plus (an LLM on top of the ML) and FireNode (FireSense sensors on the FireMesh network).
 * - offline: paid with the station's internet down. Cloud feeds, weather, map tiles and the LLM are gone; what's
 *   left is FireNode and the FireCast model running on the station computer.
 */
export type Tier = 'free' | 'paid' | 'offline'

export const TIERS: { key: Tier; label: string; title: string }[] = [
  { key: 'free', label: 'Free', title: 'Free tier: FireWatchOS, FireCast, FireWatch Mobile' },
  { key: 'paid', label: 'Paid', title: 'Paid tier: adds FireCast Plus (LLM reasoning) and FireNode (FireSense + FireMesh)' },
  { key: 'offline', label: 'Offline', title: 'Paid tier with the internet down: FireNode and the local FireCast model only' },
]

const KEY = 'fw.tier'
let memory: Tier | null = null

function read(): Tier {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'free' || v === 'paid' || v === 'offline') return v
  } catch {
    /* storage can be blocked */
  }
  return memory ?? 'paid'
}

let state: Tier = read()
const listeners = new Set<() => void>()

export function setTier(t: Tier) {
  memory = t
  try {
    localStorage.setItem(KEY, t)
  } catch {
    /* storage can be blocked; the in-memory choice is used */
  }
  state = t
  listeners.forEach((l) => l())
}

export interface TierView {
  tier: Tier
  /** FireNode: FireSense sensors and FireMesh relays and radios. */
  fireNode: boolean
  /** FireCast Plus: the LLM on top of FireCast. Cloud-hosted, so gone offline. */
  castPlus: boolean
  /** Internet-fed data: satellite and weather feeds, map tiles, the public board. */
  online: boolean
  castName: 'FireCast' | 'FireCast Plus'
}

export function useTier(): TierView {
  const tier = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => state,
  )
  const castPlus = tier === 'paid'
  return { tier, fireNode: tier !== 'free', castPlus, online: tier !== 'offline', castName: castPlus ? 'FireCast Plus' : 'FireCast' }
}

/** Evidence that reaches the station without the internet: FireSense smoke, and reports and replies over FireMesh. */
export const LOCAL_SIGNALS = ['sensor_smoke', 'report', 'neighbor_reply'] as const
