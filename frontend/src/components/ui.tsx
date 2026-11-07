import type { ReactNode } from 'react'
import type { Recommendation, Status } from '../api'
import { REC_META } from '../lib/format'

/** Map/list symbol: filled diamond = escalate, open diamond = investigate, open square = monitor. */
export function TrackGlyph({ rec, size = 12, active = false }: { rec: Recommendation; size?: number; active?: boolean }) {
  const c = REC_META[rec].color
  const s = size
  const m = s / 2
  const stroke = active ? '#ffffff' : c
  if (rec === 'monitor') {
    const q = s * 0.3
    return (
      <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} aria-hidden>
        <rect x={q / 2} y={q / 2} width={s - q} height={s - q} fill="none" stroke={stroke} strokeWidth={1.5} />
      </svg>
    )
  }
  const pts = `${m},1 ${s - 1},${m} ${m},${s - 1} 1,${m}`
  return (
    <svg width={s} height={s} viewBox={`0 0 ${s} ${s}`} aria-hidden>
      {rec === 'escalate' ? (
        <polygon points={pts} fill={c} stroke={stroke} strokeWidth={active ? 1.5 : 0} />
      ) : (
        <>
          <polygon points={pts} fill="rgb(8 9 11 / 0.6)" stroke={stroke} strokeWidth={1.5} />
          <circle cx={m} cy={m} r={s * 0.1} fill={c} />
        </>
      )}
    </svg>
  )
}

export function ScoreReadout({ score, rec, size = 'md' }: { score: number; rec: Recommendation; size?: 'sm' | 'md' | 'lg' }) {
  const cls = { sm: 'text-[15px]', md: 'text-[22px]', lg: 'text-[44px]' }[size]
  return (
    <span className="num inline-flex items-baseline leading-none" aria-label={`Score ${score} of 100`}>
      <span className={`${cls} font-semibold tracking-tight`} style={{ color: REC_META[rec].color }}>
        {String(score).padStart(2, '0')}
      </span>
      {size === 'lg' && <span className="ml-1 text-[11px] text-dim">/100</span>}
    </span>
  )
}

export function RecTag({ rec }: { rec: Recommendation }) {
  const m = REC_META[rec]
  const solid = rec === 'escalate'
  return (
    <span
      className="num inline-flex h-[18px] items-center px-1.5 text-[10px] font-semibold tracking-[0.14em] uppercase"
      style={solid ? { background: m.color, color: '#fff' } : { boxShadow: `inset 0 0 0 1px ${m.color}`, color: m.color }}
    >
      {m.label}
    </span>
  )
}

const STATUS: Record<Status, { label: string; cls: string }> = {
  new: { label: 'NEW', cls: 'text-text' },
  acknowledged: { label: 'ACK', cls: 'text-sample' },
  escalated: { label: 'ESCALATED', cls: 'text-escalate' },
  dismissed: { label: 'DISMISSED', cls: 'text-dim line-through' },
  closed: { label: 'CLOSED', cls: 'text-dim' },
}

export function StatusTag({ status }: { status: Status }) {
  const s = STATUS[status]
  return (
    <span className={`num inline-flex items-center gap-1 text-[10px] font-medium tracking-[0.12em] ${s.cls}`}>
      {status === 'new' && <span className="blink inline-block h-1.5 w-1.5 bg-current" />}
      {s.label}
    </span>
  )
}

export function Sparkline({ values, color, w = 48, h = 16 }: { values: number[]; color: string; w?: number; h?: number }) {
  if (values.length < 2) return null
  const step = w / (values.length - 1)
  const y = (v: number) => h - 1 - (v / 100) * (h - 2)
  let d = `M0,${y(values[0])}`
  values.slice(1).forEach((v, i) => {
    d += ` H${(i + 1) * step} V${y(v)}`
  })
  const lastY = y(values[values.length - 1])
  return (
    <svg width={w} height={h} className="overflow-visible" aria-label={`Score trend ${values.join(' to ')}`}>
      <line x1={0} x2={w} y1={y(70)} y2={y(70)} stroke="#2a3038" strokeDasharray="1 2" />
      <path d={d} fill="none" stroke={color} strokeWidth={1.25} />
      <rect x={w - 2} y={lastY - 2} width={4} height={4} fill={color} />
    </svg>
  )
}

export function SectionHeader({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex h-8 items-center justify-between border-b border-line px-4">
      <span className="label">{children}</span>
      {right}
    </div>
  )
}

export function KV({ k, v, accent }: { k: string; v: ReactNode; accent?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-[3px]">
      <span className="label !text-[9.5px]">{k}</span>
      <span className="num text-[12px] text-text" style={accent ? { color: accent } : undefined}>
        {v}
      </span>
    </div>
  )
}

export function Mark({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden>
      <polygon points="8,1 15,8 8,15 1,8" fill="none" stroke="currentColor" strokeWidth={1.25} />
      <polygon points="8,4.5 11.5,8 8,11.5 4.5,8" fill="#ff4b2b" />
    </svg>
  )
}

/** A toast with one Undo button; the action runs when the countdown ends. */
export function UndoBar({ message, left, onUndo }: { message: string; left: number; onUndo: () => void }) {
  return (
    <div role="status" className="flex items-center justify-between gap-3 border border-line-2 border-l-2 border-l-ok bg-raised px-3 py-2 text-[12.5px]">
      <span>
        {message} <span className="num text-dim">{left}s</span>
      </span>
      <button onClick={onUndo} className="btn !h-9 shrink-0 !px-4">
        Undo
      </button>
    </div>
  )
}
