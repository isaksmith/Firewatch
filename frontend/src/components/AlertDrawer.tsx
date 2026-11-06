import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Box, ShieldAlert, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type ActionName, type AlertDetail } from '../api'
import { REC_META, centralTime, compass, kmhToMph, seenLabel } from '../lib/format'
import { useOperator } from '../lib/operator'
import { RecLabel, ScoreBadge, StatusPill } from './ScoreBadge'

const QUICK_NOTES = ['Paged VFD', 'Known prescribed burn', 'Industrial site', 'Called landowner']

export function AlertDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ['alert', id], queryFn: () => api.alert(id), refetchInterval: 15_000 })
  if (q.isLoading) return <DrawerShell onClose={onClose}><p className="p-4 text-sm text-muted">Loading…</p></DrawerShell>
  if (q.isError || !q.data) return <DrawerShell onClose={onClose}><p className="p-4 text-sm text-escalate">Could not load alert.</p></DrawerShell>
  return <DrawerShell onClose={onClose}><DrawerBody a={q.data} /></DrawerShell>
}

function DrawerShell({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  return (
    <aside className="relative flex w-[420px] shrink-0 flex-col overflow-y-auto border-l border-line bg-panel">
      <button onClick={onClose} className="absolute right-3 top-3 text-muted hover:text-text" aria-label="Close">
        <X size={18} />
      </button>
      {children}
    </aside>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2 border-b border-line px-4 py-3">
      <h3 className="text-[11px] font-semibold tracking-widest text-muted">{title}</h3>
      {children}
    </section>
  )
}

function DrawerBody({ a }: { a: AlertDetail }) {
  const w = a.weather
  const maxAbs = Math.max(1, ...a.reasons.map((r) => Math.abs(r.contribution)))
  return (
    <>
      {a.degraded && (
        <div className="flex items-center gap-2 bg-degraded/15 px-4 py-2 text-xs text-degraded">
          <AlertTriangle size={14} /> Weather inputs missing — scored in degraded mode.
        </div>
      )}
      <div className="space-y-2 border-b border-line p-4 pr-10">
        <div className="flex items-center gap-3">
          <ScoreBadge score={a.score} rec={a.recommendation} size={48} />
          <div>
            <RecLabel rec={a.recommendation} />
            <div className="font-semibold">{a.place_label}</div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="tabular">First seen {seenLabel(a.first_seen, a.is_sample)}</span>
          <span>·</span>
          <span className="tabular">Last {centralTime(a.last_seen)}</span>
          <StatusPill status={a.status} />
          {a.is_sample && <span className="text-[10px] font-semibold uppercase text-sample">sample</span>}
        </div>
        {a.guardrail && (
          <div className="flex items-start gap-2 rounded bg-white/5 p-2 text-xs">
            <ShieldAlert size={14} className="mt-0.5 shrink-0 text-investigate" /> {a.guardrail}
          </div>
        )}
      </div>

      <Section title="WHY THIS SCORE">
        <ul className="space-y-1.5">
          {a.reasons.slice(0, 5).map((r) => (
            <li key={r.feature} className="flex items-center gap-2 text-sm">
              <span className={`tabular w-9 text-right font-semibold ${r.contribution >= 0 ? 'text-text' : 'text-emerald-400'}`}>
                {r.contribution > 0 ? '+' : ''}
                {r.contribution}
              </span>
              <span className="flex-1 truncate">{r.label}</span>
              <span className="h-1.5 w-20 rounded bg-white/5">
                <span
                  className="block h-full rounded"
                  style={{
                    width: `${(Math.abs(r.contribution) / maxAbs) * 100}%`,
                    background: r.contribution >= 0 ? REC_META[a.recommendation].color : '#34d399',
                  }}
                />
              </span>
            </li>
          ))}
        </ul>
        <div className="tabular text-xs text-muted">
          Score trend {a.score_trend.join(' → ')} · {a.scorer}
        </div>
      </Section>

      <Section title="CONDITIONS">
        {w.wind_kmh != null ? (
          <div className="grid grid-cols-2 gap-y-1 text-sm">
            <span>
              Wind {Math.round(w.wind_kmh)} km/h from {compass(w.wind_dir_deg ?? 0)}
            </span>
            <span>Gusts {Math.round(kmhToMph(w.gust_kmh ?? 0))} mph</span>
            <span>Humidity {Math.round(w.rh_pct ?? 0)}%</span>
            <span>Temp {Math.round(w.temp_c ?? 0)}°C</span>
            <span>
              Fire danger <b>{w.gfdi_band}</b> ({w.gfdi})
            </span>
            <span>Rain 72 h: {w.precip_72h_mm ?? 0} mm</span>
          </div>
        ) : (
          <p className="text-sm text-muted">No weather available.</p>
        )}
        {w.source && <div className="text-[11px] text-muted">Source: {w.source}</div>}
      </Section>

      <Section title="NEARBY">
        <ul className="space-y-1 text-sm">
          {a.nearest_assets.map((n) => (
            <li key={`${n.kind}-${n.name}`} className="flex justify-between">
              <span>
                {n.name} <span className="text-xs text-muted">({n.kind.replace('_', ' ')})</span>
              </span>
              <span className="tabular text-muted">{n.distance_km.toFixed(1)} km</span>
            </li>
          ))}
          {a.nearest_assets.length === 0 && <li className="text-muted">Nothing within 30 km.</li>}
        </ul>
      </Section>

      <Section title="DETECTIONS">
        <ul className="space-y-1 text-xs">
          {a.detections.map((d) => (
            <li key={d.id} className="tabular flex justify-between">
              <span>
                {d.satellite} <span className="text-muted">{d.source.split('_')[0]}</span>
              </span>
              <span className="text-muted">{centralTime(d.acq_time)}</span>
              <span>{d.frp_mw?.toFixed(0) ?? '–'} MW</span>
              <span className="w-14 text-right text-muted">{d.confidence}</span>
            </li>
          ))}
        </ul>
      </Section>

      <div className="border-b border-line p-4">
        <Link
          to={`/alerts/${a.id}/3d`}
          className="flex w-full items-center justify-center gap-2 rounded bg-white/10 py-2 text-sm font-semibold hover:bg-white/15"
        >
          <Box size={16} /> Open 3D spread preview
        </Link>
      </div>

      <ActionBar a={a} />

      <Section title="HISTORY">
        <ul className="space-y-1 text-xs">
          {a.actions.map((x, i) => (
            <li key={i}>
              <span className="tabular text-muted">{centralTime(x.created_at)}</span> {x.operator} <b>{x.action}d</b>
              {x.note && <span className="text-muted"> — {x.note}</span>}
            </li>
          ))}
          {a.actions.length === 0 && <li className="text-muted">No actions yet.</li>}
        </ul>
      </Section>
    </>
  )
}

function ActionBar({ a }: { a: AlertDetail }) {
  const qc = useQueryClient()
  const operator = useOperator()
  const [note, setNote] = useState('')
  const act = useMutation({
    mutationFn: (action: ActionName) => api.act(a.id, action, operator, note),
    onSuccess: (data) => {
      qc.setQueryData(['alert', a.id], data)
      qc.invalidateQueries({ queryKey: ['alerts'] })
      setNote('')
    },
  })
  const open = ['new', 'acknowledged', 'escalated'].includes(a.status)
  return (
    <section className="space-y-2 border-b border-line p-4">
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Note (optional)"
        className="w-full rounded border border-line bg-bg px-2 py-1.5 text-sm"
      />
      <div className="flex flex-wrap gap-1">
        {QUICK_NOTES.map((n) => (
          <button key={n} onClick={() => setNote(n)} className="rounded bg-white/5 px-2 py-0.5 text-[11px] text-muted hover:text-text">
            {n}
          </button>
        ))}
      </div>
      {open ? (
        <div className="grid grid-cols-3 gap-2">
          <button
            disabled={a.status !== 'new' || act.isPending}
            onClick={() => act.mutate('acknowledge')}
            className="rounded border border-line py-2 text-sm hover:bg-white/5 disabled:opacity-40"
          >
            Acknowledge
          </button>
          <button
            disabled={a.status === 'escalated' || act.isPending}
            onClick={() => act.mutate('escalate')}
            className="rounded bg-escalate py-2 text-sm font-semibold text-white hover:bg-red-500 disabled:opacity-40"
          >
            Escalate
          </button>
          <button
            disabled={act.isPending}
            onClick={() => act.mutate('dismiss')}
            className="rounded border border-line py-2 text-sm text-muted hover:bg-white/5 disabled:opacity-40"
          >
            Dismiss
          </button>
        </div>
      ) : (
        <button onClick={() => act.mutate('reopen')} className="w-full rounded border border-line py-2 text-sm hover:bg-white/5">
          Reopen
        </button>
      )}
      {act.isError && <p className="text-xs text-escalate">{(act.error as Error).message}</p>}
    </section>
  )
}
