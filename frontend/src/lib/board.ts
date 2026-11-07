import { useQuery } from '@tanstack/react-query'
import { api, BOARD_ADMIN_KEY, type AdminPost } from '../api'
import { timeAgo } from './format'

// Category styling reuses tokens already in the dashboard: fire is the escalate red,
// smoke the investigate amber, hazard the sample cyan, burn the ok green.
export const CAT_META: Record<string, { label: string; text: string; bg: string; border: string }> = {
  fire: { label: 'Fire', text: 'text-escalate', bg: 'bg-escalate', border: 'border-escalate' },
  smoke: { label: 'Smoke', text: 'text-investigate', bg: 'bg-investigate', border: 'border-investigate' },
  hazard: { label: 'Hazard', text: 'text-sample', bg: 'bg-sample', border: 'border-sample' },
  burn: { label: 'Burn', text: 'text-ok', bg: 'bg-ok', border: 'border-ok' },
  other: { label: 'Other', text: 'text-muted', bg: 'bg-muted', border: 'border-muted' },
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
