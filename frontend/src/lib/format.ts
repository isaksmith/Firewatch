import type { Recommendation } from '../api'

export const REC_META: Record<Recommendation, { label: string; color: string; text: string; bg: string; border: string }> = {
  escalate: { label: 'Escalate', color: '#ef4444', text: 'text-escalate', bg: 'bg-escalate', border: 'border-escalate' },
  investigate: { label: 'Investigate', color: '#f59e0b', text: 'text-investigate', bg: 'bg-investigate', border: 'border-investigate' },
  monitor: { label: 'Monitor', color: '#64748b', text: 'text-monitor', bg: 'bg-monitor', border: 'border-monitor' },
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

export const compass = (deg: number) => COMPASS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16]

export const kmhToMph = (kmh: number) => kmh / 1.609344

export function timeAgo(iso: string, now = Date.now()): string {
  const mins = Math.round((now - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

export function centralTime(iso: string, withDate = false): string {
  return new Date(iso).toLocaleString('en-US', {
    timeZone: 'America/Chicago',
    hour: 'numeric',
    minute: '2-digit',
    ...(withDate ? { month: 'short', day: 'numeric', year: 'numeric' } : {}),
  })
}

/** Sample events carry their historical timestamps, so show the date instead of "x days ago". */
export function seenLabel(iso: string, isSample: boolean): string {
  return isSample ? centralTime(iso, true) : timeAgo(iso)
}

export const SUPPRESSION_LABEL = {
  static_source: 'static heat source',
  likely_prescribed: 'likely prescribed burn',
  low_signal: 'low signal',
} as const
