import { Circle, Eye, Flame } from 'lucide-react'
import type { Recommendation } from '../api'
import { REC_META } from '../lib/format'

const ICONS = { escalate: Flame, investigate: Eye, monitor: Circle }

export function ScoreBadge({ score, rec, size = 40 }: { score: number; rec: Recommendation; size?: number }) {
  return (
    <div
      className="tabular flex shrink-0 items-center justify-center rounded-full font-bold text-white"
      style={{ width: size, height: size, background: REC_META[rec].color, fontSize: size * 0.4 }}
      aria-label={`Score ${score}, ${REC_META[rec].label}`}
    >
      {score}
    </div>
  )
}

export function RecLabel({ rec, className = '' }: { rec: Recommendation; className?: string }) {
  const Icon = ICONS[rec]
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide ${REC_META[rec].text} ${className}`}>
      <Icon size={13} strokeWidth={2.5} />
      {REC_META[rec].label}
    </span>
  )
}

export function StatusPill({ status }: { status: string }) {
  const styles: Record<string, string> = {
    new: 'bg-white/10 text-text',
    acknowledged: 'bg-sky-500/15 text-sky-300',
    escalated: 'bg-escalate/20 text-red-300',
    dismissed: 'bg-white/5 text-muted line-through',
    closed: 'bg-white/5 text-muted',
  }
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${styles[status] ?? ''}`}>
      {status === 'acknowledged' ? 'ack' : status}
    </span>
  )
}

export function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return null
  const w = 44
  const h = 14
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - (v / 100) * h}`)
    .join(' ')
  return (
    <svg width={w} height={h} className="overflow-visible" aria-label={`Score trend ${values.join(' to ')}`}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}
