import { useQuery } from '@tanstack/react-query'
import { api, BOARD_ADMIN_KEY, type AdminPost } from '../api'

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
