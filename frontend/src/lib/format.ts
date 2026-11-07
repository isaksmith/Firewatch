import type { Recommendation } from '../api'

export const REC_META: Record<Recommendation, { label: string; short: string; color: string; text: string }> = {
  escalate: { label: 'Escalate', short: 'ESC', color: '#ff4b2b', text: 'text-escalate' },
  investigate: { label: 'Investigate', short: 'INV', color: '#ffb21a', text: 'text-investigate' },
  monitor: { label: 'Monitor', short: 'MON', color: '#6b7684', text: 'text-monitor' },
}

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

export const compass = (deg: number) => COMPASS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16]

export const kmhToMph = (kmh: number) => kmh / 1.609344

export const trackId = (id: number) => `FW-${String(id).padStart(4, '0')}`

export const pad3 = (deg: number) => String(Math.round(((deg % 360) + 360) % 360)).padStart(3, '0')

export function timeAgo(iso: string, now = Date.now()): string {
  const mins = Math.round((now - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'NOW'
  if (mins < 60) return `T+${mins}M`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `T+${hours}H`
  return `T+${Math.round(hours / 24)}D`
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

function centralParts(iso: string) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago',
    year: 'numeric',
    month: 'numeric',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZoneName: 'short',
  }).formatToParts(new Date(iso))
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? ''
  return { y: get('year'), m: MONTHS[Number(get('month')) - 1], d: get('day'), hh: get('hour'), mm: get('minute'), tz: get('timeZoneName') }
}

/** 24-hour Central time, e.g. "12:30 CST"; with a date, "06 MAR 2017 12:30 CST". */
export function centralTime(iso: string, withDate = false): string {
  const p = centralParts(iso)
  const time = `${p.hh}:${p.mm} ${p.tz}`
  return withDate ? `${p.d} ${p.m} ${p.y} ${time}` : time
}

/** Sample events carry their historical timestamps, so show the date instead of elapsed time. */
export function seenLabel(iso: string, isSample: boolean): string {
  return isSample ? centralTime(iso, true) : timeAgo(iso)
}

export function latLon(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(4)}°${lat >= 0 ? 'N' : 'S'} ${Math.abs(lon).toFixed(4)}°${lon >= 0 ? 'E' : 'W'}`
}

export const SUPPRESSION_LABEL = {
  static_source: 'static heat source',
  likely_prescribed: 'likely prescribed burn',
  registered_burn: 'registered burn',
  low_signal: 'low signal',
} as const

const SIGNAL_SHORT: Record<string, string> = { line_fault: 'line', report: 'report', neighbor_reply: 'nbr', camera_smoke: 'cam', sensor_smoke: 'smoke' }

/** Compact evidence count for list rows, e.g. "viirs×3 line×1 nbr×1". */
export function sourcesLabel(sources: Record<string, number>, signals: Record<string, number>): string {
  return [
    ...Object.entries(sources).map(([k, v]) => `${k}×${v}`),
    ...Object.entries(signals).map(([k, v]) => `${SIGNAL_SHORT[k] ?? k}×${v}`),
  ].join(' ')
}

/** "T+08" relative to a scenario start. */
export function tPlus(iso: string, t0: string): string {
  const m = Math.round((new Date(iso).getTime() - new Date(t0).getTime()) / 60000)
  return `T${m < 0 ? '−' : '+'}${String(Math.abs(m)).padStart(2, '0')}`
}
