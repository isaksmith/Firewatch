import { AlertTriangle, RotateCcw } from 'lucide-react'
import type { AlertSummary } from '../api'
import { REC_META, seenLabel } from '../lib/format'
import { RecLabel, ScoreBadge, Sparkline, StatusPill } from './ScoreBadge'

interface Props {
  alerts: AlertSummary[]
  selectedId: number | null
  hoveredId: number | null
  onSelect: (id: number) => void
  onHover: (id: number | null) => void
  minScore: number
  setMinScore: (n: number) => void
  showSuppressed: boolean
  setShowSuppressed: (b: boolean) => void
  suppressedTotal: number
}

export function AlertList(p: Props) {
  const visible = p.alerts.filter((a) => a.score >= p.minScore || a.recommendation === 'monitor')
  return (
    <aside className="flex w-[340px] shrink-0 flex-col border-r border-line bg-panel">
      <div className="space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold tracking-wide">
            ALERTS <span className="tabular text-muted">({visible.length})</span>
          </h2>
          <label className="flex items-center gap-2 text-xs text-muted">
            Score ≥
            <input
              type="number"
              min={0}
              max={100}
              step={10}
              value={p.minScore}
              onChange={(e) => p.setMinScore(Number(e.target.value))}
              className="tabular w-14 rounded border border-line bg-bg px-1.5 py-0.5 text-text"
            />
          </label>
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={p.showSuppressed} onChange={(e) => p.setShowSuppressed(e.target.checked)} />
          Show suppressed <span className="tabular">({p.suppressedTotal})</span>
        </label>
      </div>
      <ul className="flex-1 overflow-y-auto">
        {visible.map((a) => (
          <AlertCard
            key={a.id}
            a={a}
            selected={a.id === p.selectedId}
            hovered={a.id === p.hoveredId}
            onClick={() => p.onSelect(a.id)}
            onHover={p.onHover}
          />
        ))}
        {visible.length === 0 && <li className="p-6 text-center text-sm text-muted">No alerts match the filters.</li>}
      </ul>
    </aside>
  )
}

function AlertCard({ a, selected, hovered, onClick, onHover }: {
  a: AlertSummary
  selected: boolean
  hovered: boolean
  onClick: () => void
  onHover: (id: number | null) => void
}) {
  const meta = REC_META[a.recommendation]
  const sources = Object.entries(a.sources).map(([k, v]) => `${k}×${v}`).join(' ')
  return (
    <li
      onClick={onClick}
      onMouseEnter={() => onHover(a.id)}
      onMouseLeave={() => onHover(null)}
      className={`cursor-pointer border-b border-l-4 border-b-line p-3 transition-colors ${
        selected ? 'bg-panel-2' : hovered ? 'bg-white/[0.03]' : ''
      } ${a.recommendation === 'monitor' ? 'opacity-70' : ''}`}
      style={{ borderLeftColor: selected ? meta.color : 'transparent' }}
    >
      <div className="flex gap-3">
        <ScoreBadge score={a.score} rec={a.recommendation} />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <RecLabel rec={a.recommendation} />
            <div className="flex items-center gap-1.5">
              {a.degraded && (
                <span title="Missing inputs; scored in degraded mode" className="text-degraded">
                  <AlertTriangle size={13} />
                </span>
              )}
              {a.reraised && (
                <span title="Re-raised after dismissal" className="text-investigate">
                  <RotateCcw size={13} />
                </span>
              )}
              <StatusPill status={a.status} />
            </div>
          </div>
          <div className="truncate text-sm font-medium">{a.place_label}</div>
          <div className="flex items-center justify-between text-xs text-muted">
            <span className="tabular">{seenLabel(a.first_seen, a.is_sample)}</span>
            <Sparkline values={a.score_trend} color={meta.color} />
          </div>
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate text-muted">{sources}</span>
            {a.is_sample && <span className="text-[10px] font-semibold uppercase text-sample">sample</span>}
          </div>
          {a.top_reason && <div className="truncate text-xs text-text/80">↑ {a.top_reason}</div>}
        </div>
      </div>
    </li>
  )
}
