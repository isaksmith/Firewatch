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
  if (isSample) return centralTime(iso, true)
  return Date.now() - new Date(iso).getTime() > 86_400_000 ? plainDate(iso) : timeAgo(iso)
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

/** "3:05 pm" in the district's own time. */
export function clock12(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase()
}

/** "Mar 17, 1:50 pm" in the district's own time. */
export function plainDate(iso: string): string {
  const day = new Date(iso).toLocaleDateString('en-US', { timeZone: 'America/Chicago', month: 'short', day: 'numeric' })
  return `${day}, ${clock12(iso)}`
}

const CENTRAL_PARTS = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Chicago',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

/** Minutes Central time is ahead of UTC at this instant (negative: -360 in winter, -300 in summer). */
function centralOffsetMin(ms: number): number {
  const g = (t: string) => Number(CENTRAL_PARTS.formatToParts(new Date(ms)).find((p) => p.type === t)?.value)
  const asUtc = Date.UTC(g('year'), g('month') - 1, g('day'), g('hour'), g('minute'), g('second'))
  return Math.round((asUtc - Math.floor(ms / 1000) * 1000) / 60000)
}

/** Value for a datetime-local input showing Central time. */
export function centralInput(d: Date): string {
  const off = centralOffsetMin(d.getTime())
  return new Date(d.getTime() + off * 60000).toISOString().slice(0, 16)
}

/** "2026-11-07T11:00" typed in a datetime-local box means 11:00 Central. Returns ISO with the offset, e.g. ...-06:00. */
export function centralToIso(local: string): string {
  const guess = Date.parse(`${local}:00Z`)
  let off = centralOffsetMin(guess)
  off = centralOffsetMin(guess - off * 60000)
  const sign = off < 0 ? '-' : '+'
  const a = Math.abs(off)
  const hh = String(Math.floor(a / 60)).padStart(2, '0')
  const mm = String(a % 60).padStart(2, '0')
  return `${local}:00${sign}${hh}:${mm}`
}
