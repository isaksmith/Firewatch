import { useQuery } from '@tanstack/react-query'
import { api, BOARD_ADMIN_KEY, BOARD_BURNS_ADMIN_KEY, type AdminBurn, type AdminPost } from '../api'
import { timeAgo } from './format'

// Category styling reuses tokens already in the dashboard: fire is the escalate red,
// smoke the investigate amber, hazard the sample cyan, burn the ok green.
export const CAT_META: Record<string, { label: string; text: string; bg: string; border: string; tint: string }> = {
  fire: { label: 'Fire', text: 'text-escalate', bg: 'bg-escalate', border: 'border-escalate', tint: 'bg-escalate/10' },
  smoke: { label: 'Smoke', text: 'text-investigate', bg: 'bg-investigate', border: 'border-investigate', tint: 'bg-investigate/10' },
  hazard: { label: 'Hazard', text: 'text-sample', bg: 'bg-sample', border: 'border-sample', tint: 'bg-sample/10' },
  burn: { label: 'Burn', text: 'text-ok', bg: 'bg-ok', border: 'border-ok', tint: 'bg-ok/10' },
  other: { label: 'Other', text: 'text-muted', bg: 'bg-muted', border: 'border-muted', tint: 'bg-muted/10' },
}

export const catMeta = (c: string) => CAT_META[c] ?? CAT_META.other

// One poll shared by the panel and the map pins (same key, so react-query dedupes).
export function useBoardPosts() {
  return useQuery<AdminPost[]>({
    queryKey: BOARD_ADMIN_KEY,
    queryFn: api.boardAdminPosts,
    refetchInterval: 5_000,
    retry: false,
  })
}

export const isPinnable = (p: AdminPost) => p.status === 'open' && p.lat != null && p.lon != null

export const threadLine = (p: { thread_size?: number; badge?: string | null }) =>
  p.thread_size != null && p.thread_size > 1
    ? `Part of ${p.thread_size} reports in this area${p.badge ? '. The notice covers all of them.' : ''}`
    : null

export function ageMinutes(p: { age_min?: number; created_at: string }): number {
  if (p.age_min != null) return Math.max(0, Math.round(p.age_min))
  return Math.max(0, Math.round((Date.now() - Date.parse(p.created_at)) / 60_000))
}

/** Plain words for the public phone page, from the server's age_min when present. */
export function plainAge(p: { age_min?: number; created_at: string }): string {
  const mins = ageMinutes(p)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} hr ago`
  return `${Math.round(hours / 24)} days ago`
}

/** Server age_min when present (replay posts carry old timestamps), else the browser clock. */
export function postAge(p: { age_min?: number; created_at: string }): string {
  if (p.age_min == null) return timeAgo(p.created_at)
  const mins = Math.max(0, Math.round(p.age_min))
  if (mins < 1) return 'NOW'
  if (mins < 60) return `T+${mins}M`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `T+${hours}H`
  return `T+${Math.round(hours / 24)}D`
}

export function useBoardBurns() {
  return useQuery<AdminBurn[]>({
    queryKey: BOARD_BURNS_ADMIN_KEY,
    queryFn: api.boardAdminBurns,
    refetchInterval: 15_000,
    retry: false,
  })
}

const DIRECTIONS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest']

/** Straight-line km and compass bearing (degrees from north) from a to b. */
export function kmAndBearing(a: { lat: number; lon: number }, b: { lat: number; lon: number }): { km: number; deg: number } {
  const rad = Math.PI / 180
  const dy = (b.lat - a.lat) * 110.57
  const dx = (b.lon - a.lon) * 111.32 * Math.cos(((a.lat + b.lat) / 2) * rad)
  const deg = (Math.atan2(dx, dy) / rad + 360) % 360
  return { km: Math.hypot(dx, dy), deg }
}

/** "About 3 km northwest of you", from the phone to the burn's rounded point. */
export function burnDistanceText(me: { lat: number; lon: number }, burn: { lat: number; lon: number }): string {
  const { km, deg } = kmAndBearing(me, burn)
  if (km < 1) return 'Under 1 km from you'
  return `About ${Math.round(km)} km ${DIRECTIONS[Math.round(deg / 45) % 8]} of you`
}

export const burnCoords = (b: { lat: number; lon: number }) => `Near ${b.lat.toFixed(2)}, ${b.lon.toFixed(2)}`

/** "Sent 12 min late (no signal)", or null when the post went out on time. */
export const sentLateText = (min: number | null | undefined) => (min ? `Sent ${min} min late (no signal)` : null)
