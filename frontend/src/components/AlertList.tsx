import { AlertTriangle, PanelLeftClose, PanelLeftOpen, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import type { AlertSummary, AlertsResponse } from '../api'
import { REC_META, SUPPRESSION_LABEL, seenLabel, sourcesLabel, trackId } from '../lib/format'
import { filterQueue, type QueueTab } from '../lib/queue'
import { ScoreReadout, Sparkline, StatusTag, TrackGlyph } from './ui'

interface Props {
  alerts: AlertSummary[]
  tab: QueueTab
  setTab: (t: QueueTab) => void
  suppressed?: AlertsResponse['suppressed']
  lowData?: boolean
  loading?: boolean
  selectedId: number | null
  hoveredId: number | null
  onSelect: (id: number) => void
  onHover: (id: number | null) => void
}

const COLLAPSED_KEY = 'fw.queueCollapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

export function AlertList(p: Props) {
  const [collapsed, setCollapsedState] = useState(readCollapsed)
  const setCollapsed = (c: boolean) => {
    setCollapsedState(c)
    try {
      localStorage.setItem(COLLAPSED_KEY, c ? '1' : '0')
    } catch {
      /* storage can be blocked; the choice lasts until reload */
    }
  }
  if (collapsed) return <CollapsedQueue alerts={p.alerts} onExpand={() => setCollapsed(false)} />
  const visible = filterQueue(p.alerts, p.tab)
  const tabs: [QueueTab, string][] = [
    ['active', 'Active'],
    ['escalate', 'Escalate'],
    ['suppressed', 'Suppressed'],
  ]
  return (
    <aside className="flex max-h-[42%] w-full shrink-0 flex-col border-b border-line bg-panel md:max-h-none md:w-[360px] md:border-r md:border-b-0">
      <div className="flex h-9 items-center justify-between border-b border-line px-4">
        <span className="label !text-muted">Alert queue</span>
        <span className="flex items-center gap-3">
          <span className="num text-[10px] text-dim">SORT: LEVEL ▸ SCORE</span>
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            aria-expanded
            aria-label="Collapse the alert queue"
            title="Collapse the alert queue"
            className="text-dim hover:text-text"
          >
            <PanelLeftClose size={14} />
          </button>
        </span>
      </div>
      <div className="grid grid-cols-3 border-b border-line">
        {tabs.map(([k, label]) => {
          const n = k === 'suppressed' && p.lowData && p.suppressed ? p.suppressed.total : filterQueue(p.alerts, k).length
          const on = p.tab === k
          return (
            <button
              key={k}
              onClick={() => p.setTab(k)}
              className={`num relative flex h-9 items-center justify-center gap-2 text-[10px] tracking-[0.14em] uppercase transition-colors ${
                on ? 'text-text' : 'text-dim hover:text-muted'
              }`}
            >
              {label}
              <span className={on && k !== 'suppressed' && n > 0 ? 'text-escalate' : ''}>{String(n).padStart(2, '0')}</span>
              {on && <span className="absolute inset-x-3 bottom-0 h-[2px] bg-text" />}
            </button>
          )
        })}
      </div>
      <ul className="flex-1 overflow-y-auto">
        {p.tab === 'suppressed' && p.lowData && p.suppressed && (
          <li className="px-4 py-3">
            {(Object.keys(SUPPRESSION_LABEL) as (keyof typeof SUPPRESSION_LABEL)[]).map((k) => (
              <div key={k} className="flex justify-between border-b border-line py-2 text-[12.5px]">
                <span className="capitalize">{SUPPRESSION_LABEL[k]}</span>
                <span className="num text-muted">{p.suppressed![k]}</span>
              </div>
            ))}
            <p className="mt-3 text-[12px] text-dim">The details load when you turn Low data off.</p>
          </li>
        )}
        {!(p.tab === 'suppressed' && p.lowData) && visible.map((a) => (
          <AlertRow
            key={a.id}
            a={a}
            selected={a.id === p.selectedId}
            hovered={a.id === p.hoveredId}
            onClick={() => p.onSelect(a.id)}
            onHover={p.onHover}
          />
        ))}
        {p.loading && (
          <li className="flex flex-col items-center gap-2 px-6 py-12 text-center">
            <span className="label">Loading…</span>
          </li>
        )}
        {!p.loading && visible.length === 0 && !(p.tab === 'suppressed' && p.lowData) && (
          <li className="flex flex-col items-center gap-2 px-6 py-12 text-center">
            <span className="label">No tracks</span>
            <span className="text-[12px] text-dim">Nothing in this queue right now.</span>
          </li>
        )}
      </ul>
    </aside>
  )
}

/** The queue folded away: a thin rail beside the map (a short strip on phones) that still shows the counts. */
function CollapsedQueue({ alerts, onExpand }: { alerts: AlertSummary[]; onExpand: () => void }) {
  const esc = alerts.filter((a) => a.recommendation === 'escalate').length
  const inv = alerts.filter((a) => a.recommendation === 'investigate').length
  return (
    <aside className="flex w-full shrink-0 border-b border-line bg-panel md:w-9 md:border-r md:border-b-0">
      <button
        type="button"
        onClick={onExpand}
        aria-expanded={false}
        aria-label={`Show the alert queue: ${esc} escalate, ${inv} investigate`}
        title="Show the alert queue"
        className="flex h-9 w-full items-center gap-3 px-4 text-dim hover:bg-raised hover:text-text md:h-full md:flex-col md:gap-4 md:px-0 md:py-3"
      >
        <PanelLeftOpen size={14} className="shrink-0" />
        <span className="label !text-muted md:[writing-mode:vertical-rl]">Alert queue</span>
        <span className="num flex items-center gap-3 text-[10px] md:flex-col md:gap-2">
          <span title="Escalate" style={{ color: esc ? REC_META.escalate.color : undefined }}>{String(esc).padStart(2, '0')}</span>
          <span title="Investigate" style={{ color: inv ? REC_META.investigate.color : undefined }}>{String(inv).padStart(2, '0')}</span>
        </span>
      </button>
    </aside>
  )
}

function AlertRow({ a, selected, hovered, onClick, onHover }: {
  a: AlertSummary
  selected: boolean
  hovered: boolean
  onClick: () => void
  onHover: (id: number | null) => void
}) {
  const meta = REC_META[a.recommendation]
  const sources = sourcesLabel(a.sources, a.signals)
  const sub =
    a.recommendation === 'monitor' && a.suppression
      ? `Suppressed: ${SUPPRESSION_LABEL[a.suppression]}`
      : (a.level_reason?.replace(/^\w+: /, '') ?? a.top_reason)
  const awaiting = a.response?.awaiting
  return (
    <li
      onClick={onClick}
      onMouseEnter={() => onHover(a.id)}
      onMouseLeave={() => onHover(null)}
      className={`relative cursor-pointer border-b border-line py-3 pr-4 pl-5 transition-colors ${
        selected ? 'bg-raised' : hovered ? 'bg-panel-2' : ''
      }`}
    >
      <span
        className="absolute top-0 bottom-0 left-0 w-[3px]"
        style={{ background: a.recommendation === 'monitor' ? 'transparent' : meta.color, opacity: selected ? 1 : 0.7 }}
      />
      {selected && <span className="pointer-events-none absolute inset-0 shadow-[inset_0_0_0_1px_#2a3038]" />}
      <div className="flex gap-3.5">
        <div className="flex w-9 shrink-0 flex-col items-start gap-1.5 pt-0.5">
          <ScoreReadout score={a.score} rec={a.recommendation} />
          <Sparkline values={a.score_trend} color={meta.color} w={34} h={12} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <TrackGlyph rec={a.recommendation} size={10} />
            <span className="num text-[10px] font-medium tracking-[0.12em]" style={{ color: meta.color }}>
              {meta.short}
            </span>
            <span className="num text-[10px] tracking-[0.08em] text-dim">{trackId(a.id)}</span>
            <span className="ml-auto flex items-center gap-2">
              {a.degraded && (
                <span title="Missing inputs; scored in degraded mode" className="text-degraded">
                  <AlertTriangle size={11} />
                </span>
              )}
              {a.reraised && (
                <span title="Re-raised after dismissal" className="text-investigate">
                  <RotateCcw size={11} />
                </span>
              )}
              <StatusTag status={a.status} />
            </span>
          </div>
          <div className={`mt-1 truncate text-[13px] font-medium ${a.recommendation === 'monitor' ? 'text-muted' : 'text-text'}`}>
            {a.place_label}
          </div>
          <div className="num mt-1 flex items-center justify-between gap-2 text-[10.5px] text-dim">
            <span>{seenLabel(a.first_seen, a.is_sample)}</span>
            <span className="truncate">{sources}</span>
          </div>
          {sub && <div className="mt-1.5 truncate text-[11.5px] text-muted">{sub}</div>}
          {a.response && (
            <div className="num mt-1.5 flex items-center gap-2 text-[10px] tracking-[0.06em]">
              {a.response.decision === 'page' ? (
                <span className="text-escalate">PAGED{a.response.decision_by ? ` · ${a.response.decision_by.split(' (')[0].toUpperCase()}` : ''}</span>
              ) : a.response.decision === 'no' ? (
                <span className="text-dim">STOOD DOWN</span>
              ) : (
                awaiting && <span className="blink text-investigate">AWAITING {awaiting.split(' (')[0].toUpperCase()}</span>
              )}
              <span className="ml-auto text-dim">{a.response.texts_sent} TEXTS</span>
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
