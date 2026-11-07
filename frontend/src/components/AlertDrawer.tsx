import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Box, Download, ShieldAlert, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BASE, api, type ActionName, type AlertDetail, type DataAge, type InPathPlace } from '../api'
import { REC_META, agoLabel, centralTime, compass, kmhToMph, latLon, pad3, seenLabel, trackId } from '../lib/format'
import { useLowData } from '../lib/lowData'
import { useOperator } from '../lib/operator'
import { useUndoable } from '../lib/undoable'
import { KV, RecTag, ScoreReadout, SectionHeader, StatusTag, UndoBar } from './ui'

const QUICK_NOTES = ['Paged VFD', 'Known Rx burn', 'Industrial site', 'Called landowner']

const DANGER_COLOR: Record<string, string> = {
  'Low-Moderate': '#3ddc97',
  High: '#ffd166',
  'Very High': '#ffb21a',
  Severe: '#ff7a2b',
  Extreme: '#ff4b2b',
}

const isTyping = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

export function AlertDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { on: lowData } = useLowData()
  const q = useQuery({ queryKey: ['alert', id], queryFn: () => api.alert(id), refetchInterval: lowData ? false : 15_000 })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isTyping(e)) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside className="flex w-[400px] shrink-0 flex-col border-l border-line bg-panel">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line pr-2 pl-4">
        <span className="label !text-muted">
          Track <span className="text-text">{trackId(id)}</span>
        </span>
        <button onClick={onClose} className="flex h-6 w-6 items-center justify-center text-dim hover:bg-raised hover:text-text" aria-label="Close">
          <X size={14} />
        </button>
      </div>
      {q.isLoading && <p className="label p-4">Loading…</p>}
      {(q.isError || (!q.isLoading && !q.data)) && <p className="p-4 text-[12px] text-escalate">Could not load alert.</p>}
      {q.data && <DrawerBody a={q.data} />}
    </aside>
  )
}

function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-line">
      <SectionHeader right={right}>{title}</SectionHeader>
      <div className="px-4 py-3">{children}</div>
    </section>
  )
}

const EXPECTED_MIN: Record<string, number> = { Satellite: 15, Weather: 90 }
const expectedFor = (label: string) => EXPECTED_MIN[label.split(' (')[0]]

function DataAgeSection({ a }: { a: AlertDetail }) {
  const rows: DataAge[] = a.data_age ?? []
  const path = useQuery({ queryKey: ['in-path', a.id], queryFn: () => api.inPath(a.id) })
  // Sample alerts carry a scenario clock; the server tells us what "now" is.
  const [wall, setWall] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setWall(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  const now = a.is_sample && path.data ? new Date(path.data.now).getTime() : wall
  if (rows.length === 0) return null
  return (
    <Section title="How fresh is the data">
      <ul className="space-y-1.5">
        {rows.map((r) => {
          const mins = r.last_seen ? (now - new Date(r.last_seen).getTime()) / 60000 : null
          const limit = expectedFor(r.label)
          const gap = r.last_seen == null || (limit != null && mins != null && mins > limit)
          return (
            <li key={`${r.label}-${r.source}`} className="flex items-baseline justify-between gap-3 text-[12.5px]">
              <span className="min-w-0">{r.label}</span>
              <span className={`num shrink-0 text-[12px] ${gap ? 'text-degraded' : 'text-ok'}`}>
                {r.last_seen ? agoLabel(r.last_seen, now) : 'no time on record'}
                {gap && r.last_seen && <span className="ml-1.5 border border-degraded/60 px-1 text-[9.5px]">GAP</span>}
              </span>
            </li>
          )
        })}
      </ul>
    </Section>
  )
}

function whenLabel(p: InPathPlace): string {
  if (p.status === 'reached') return `reached at ${p.reached_local ?? p.eta_local ?? ''}`
  if (p.eta_min != null) return `in ${p.eta_min} min (${p.eta_local ?? p.arrival_local ?? ''})`
  return p.arrival_local ? `about ${p.arrival_local}` : 'not expected soon'
}

function PathSection({ id }: { id: number }) {
  const q = useQuery({ queryKey: ['in-path', id], queryFn: () => api.inPath(id) })
  if (q.isLoading) return null
  const places = q.data?.places ?? []
  return (
    <Section title="Who is in the path">
      {q.isError && <p className="text-[12px] text-dim">Could not load the path.</p>}
      {q.data && places.length === 0 && <p className="text-[12px] text-dim">Nothing known in the path yet.</p>}
      <ul className="space-y-2">
        {places.map((p) => (
          <li key={p.id} className="flex items-baseline justify-between gap-3 text-[12.5px]">
            <span className="min-w-0">{p.label}</span>
            <span className={`num shrink-0 text-[12px] ${p.status === 'reached' ? 'text-escalate' : 'text-investigate'}`}>{whenLabel(p)}</span>
          </li>
        ))}
      </ul>
    </Section>
  )
}

const CHANNEL_LABEL: Record<string, string> = { push: 'App push', sms: 'Text message', pager: 'County pager', mesh: 'Mesh radio' }

function Count({ text }: { text: string }) {
  return <span className={`num text-[10.5px] ${text.length > 160 ? 'text-escalate' : 'text-dim'}`}>{text.length} of 160 characters</span>
}

function SendSection({ id }: { id: number }) {
  const msgs = useQuery({ queryKey: ['messages', id], queryFn: () => api.messages(id) })
  const undoable = useUndoable(5)
  const send = useMutation({ mutationFn: () => api.notify(id) })
  const m = msgs.data
  const live = send.data?.live === true
  return (
    <Section title="Messages">
      {msgs.isError && <p className="text-[12px] text-dim">Could not load the messages.</p>}
      {m && (
        <div className="space-y-3">
          <div>
            <div className="label mb-1">{m.escalated ? 'Text to the chief' : 'Quiet notice to the chief'}</div>
            <p className="border border-line bg-void px-3 py-2 text-[12.5px] leading-snug">{m.escalated ? m.chief : m.quiet}</p>
            <Count text={m.escalated ? m.chief : m.quiet} />
          </div>
          {m.escalated &&
            m.landowners.map((l) => (
              <div key={l.id}>
                <div className="label mb-1">Text to {l.name}</div>
                <p className="border border-line bg-void px-3 py-2 text-[12.5px] leading-snug">{l.text}</p>
                <Count text={l.text} />
              </div>
            ))}
          {m.escalated && m.landowners.length === 0 && <p className="text-[12px] text-dim">No landowners to text right now.</p>}
        </div>
      )}
      <div className="mt-4 space-y-2">
        {undoable.left !== null ? (
          <UndoBar message="Sending the practice alerts." left={undoable.left} onUndo={undoable.undo} />
        ) : (
          <button disabled={!m || send.isPending} onClick={() => undoable.start(() => send.mutate())} className="btn !h-11 w-full !text-[12px]">
            {send.data ? (live ? 'Send alerts again' : 'Send alerts again (practice)') : 'Send alerts (practice)'}
          </button>
        )}
        {send.isError && <p className="text-[12px] text-escalate">Could not send: {(send.error as Error).message}</p>}
        {send.data && (
          <div role="status">
            <p className={`mb-1 text-[12px] ${live ? 'text-escalate' : 'text-sample'}`}>
              {live ? 'These alerts were really sent.' : 'Practice only. Nothing was sent to anyone.'}
            </p>
            <ul className="space-y-1">
              {send.data.results.map((r, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 border-t border-line py-1 text-[12px]">
                  <span>
                    {CHANNEL_LABEL[r.channel] ?? r.channel} <span className="text-dim">to {r.to}</span>
                  </span>
                  <span className={`num shrink-0 ${r.error ? 'text-escalate' : r.status === 'dry_run' ? 'text-sample' : 'text-ok'}`}>
                    {r.error ? `failed: ${r.error}` : r.status === 'dry_run' ? 'practice' : r.status}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <a href={`${BASE}/alerts/${id}/cap.xml`} download className="flex h-9 items-center gap-2 text-[12.5px] text-sample underline underline-offset-2">
          <Download size={13} /> Download CAP file
        </a>
      </div>
    </Section>
  )
}

function DrawerBody({ a }: { a: AlertDetail }) {
  const w = a.weather
  const meta = REC_META[a.recommendation]
  const maxAbs = Math.max(1, ...a.reasons.map((r) => Math.abs(r.contribution)))
  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {a.degraded && (
          <div className="flex items-center gap-2 border-b border-line border-l-2 border-l-degraded bg-degraded/10 px-4 py-2 text-[11.5px] text-degraded">
            <AlertTriangle size={13} /> Weather inputs missing. Scored in degraded mode.
          </div>
        )}

        <div className="scanlines relative border-b border-line px-4 pt-4 pb-4">
          <span className="absolute top-0 bottom-0 left-0 w-[3px]" style={{ background: meta.color }} />
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-end gap-3">
              <ScoreReadout score={a.score} rec={a.recommendation} size="lg" />
            </div>
            <div className="flex flex-col items-end gap-2 pt-1">
              <RecTag rec={a.recommendation} />
              <StatusTag status={a.status} />
            </div>
          </div>
          <div className="mt-3 text-[16px] leading-snug font-semibold">{a.place_label}</div>
          <div className="num mt-1 text-[10.5px] tracking-[0.04em] text-dim">{latLon(a.lat, a.lon)}</div>
          <div className="mt-3">
            <KV k="First seen" v={seenLabel(a.first_seen, a.is_sample)} />
            <KV k="Last seen" v={centralTime(a.last_seen, a.is_sample)} />
            <div className="grid grid-cols-2 gap-x-6">
              <KV k="Scorer" v={a.scorer ?? '—'} />
              <KV k="Data" v={a.is_sample ? 'SAMPLE' : 'LIVE'} accent={a.is_sample ? '#5cc8ff' : '#3ddc97'} />
            </div>
          </div>
          {a.guardrail && (
            <div className="mt-3 flex items-start gap-2 border border-line border-l-2 border-l-investigate bg-investigate/5 px-3 py-2 text-[11.5px] text-text">
              <ShieldAlert size={13} className="mt-[1px] shrink-0 text-investigate" />
              <span>
                <span className="label !text-investigate mr-2">Guardrail</span>
                {a.guardrail}
              </span>
            </div>
          )}
        </div>

        <Section title="Why this score" right={<span className="num text-[10px] text-dim">TREND {a.score_trend.join(' → ')}</span>}>
          <ul className="space-y-2">
            {a.reasons.slice(0, 6).map((r) => (
              <li key={r.feature} className="grid grid-cols-[36px_1fr_72px] items-center gap-3">
                <span className={`num text-right text-[12px] font-semibold ${r.contribution >= 0 ? 'text-text' : 'text-ok'}`}>
                  {r.contribution > 0 ? '+' : ''}
                  {r.contribution}
                </span>
                <span className="text-[12.5px] leading-snug text-text">{r.label}</span>
                <span className="relative h-[6px] bg-line">
                  <span
                    className="absolute inset-y-0 left-0"
                    style={{
                      width: `${(Math.abs(r.contribution) / maxAbs) * 100}%`,
                      background: r.contribution >= 0 ? meta.color : '#3ddc97',
                    }}
                  />
                </span>
              </li>
            ))}
          </ul>
        </Section>

        <DataAgeSection a={a} />
        <PathSection id={a.id} />
        <SendSection id={a.id} />

        <Section title="Conditions" right={w.source ? <span className="num text-[10px] text-dim">{w.source.toUpperCase()}</span> : undefined}>
          {w.wind_kmh != null ? (
            <>
              <div className="mb-3 flex items-center justify-between border border-line bg-void px-3 py-2">
                <span className="label">Fire danger</span>
                <span className="num text-[12px] font-semibold" style={{ color: DANGER_COLOR[w.gfdi_band ?? ''] ?? '#e6e8eb' }}>
                  {w.gfdi_band?.toUpperCase()} <span className="font-normal text-dim">GFDI {w.gfdi}</span>
                </span>
              </div>
              <div className="grid grid-cols-2 gap-x-6">
                <KV k="Wind" v={`${Math.round(w.wind_kmh)} KM/H`} />
                <KV k="From" v={`${pad3(w.wind_dir_deg ?? 0)}° ${compass(w.wind_dir_deg ?? 0)}`} />
                <KV k="Gust" v={`${Math.round(kmhToMph(w.gust_kmh ?? 0))} MPH`} />
                <KV k="RH" v={`${Math.round(w.rh_pct ?? 0)}%`} accent={(w.rh_pct ?? 100) < 25 ? '#ffb21a' : undefined} />
                <KV k="Temp" v={`${Math.round(w.temp_c ?? 0)}°C`} />
                <KV k="Rain 72H" v={`${w.precip_72h_mm ?? 0} MM`} />
              </div>
            </>
          ) : (
            <p className="text-[12px] text-dim">No weather available.</p>
          )}
        </Section>

        <Section title="Nearby assets">
          <ul className="space-y-1.5">
            {a.nearest_assets.map((n) => (
              <li key={`${n.kind}-${n.name}`} className="flex items-center justify-between gap-3">
                <span className="min-w-0 truncate text-[12.5px]">{n.name}</span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="label !text-[9px]">{n.kind.replace('_', ' ')}</span>
                  <span className={`num w-14 text-right text-[12px] ${n.distance_km < 5 ? 'text-investigate' : 'text-text'}`}>
                    {n.distance_km.toFixed(1)} KM
                  </span>
                </span>
              </li>
            ))}
            {a.nearest_assets.length === 0 && <li className="text-[12px] text-dim">Nothing within 30 km.</li>}
          </ul>
        </Section>

        <Section title="Detections" right={<span className="num text-[10px] text-dim">{a.detections.length} HITS</span>}>
          <table className="num w-full text-[11px]">
            <thead>
              <tr className="text-left">
                {['Sat', 'Sensor', 'Time', 'FRP', 'Conf'].map((h, i) => (
                  <th key={h} className={`label !text-[9px] pb-1.5 font-medium ${i >= 3 ? 'text-right' : ''}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {a.detections.map((d) => (
                <tr key={d.id} className="border-t border-line">
                  <td className="py-1 text-text">{d.satellite}</td>
                  <td className="text-muted">{d.source.split('_')[0]}</td>
                  <td className="text-muted">{centralTime(d.acq_time)}</td>
                  <td className="text-right text-text">{d.frp_mw?.toFixed(0) ?? '–'} MW</td>
                  <td className={`text-right uppercase ${d.confidence === 'high' ? 'text-text' : 'text-dim'}`}>{d.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        <Section title="Log">
          <ol className="relative space-y-2 border-l border-line-2 pl-4">
            {a.actions.map((x, i) => (
              <li key={i} className="relative text-[11.5px]">
                <span className="absolute top-[5px] -left-[19.5px] h-[7px] w-[7px] border border-muted bg-panel" />
                <div className="num text-[10px] text-dim">{centralTime(x.created_at, true)}</div>
                <div>
                  <span className="num text-muted uppercase">{x.operator}</span>{' '}
                  <span className="font-medium">{`${x.action}${x.action.endsWith('e') ? 'd' : 'ed'}`}</span>
                  {x.note && <span className="text-muted">: {x.note}</span>}
                </div>
              </li>
            ))}
            <li className="relative text-[11.5px]">
              <span className="absolute top-[5px] -left-[19.5px] h-[7px] w-[7px] bg-muted" />
              <div className="num text-[10px] text-dim">{centralTime(a.first_seen, true)}</div>
              <div className="text-muted">Track opened by pipeline</div>
            </li>
          </ol>
        </Section>
      </div>

      <ActionBar a={a} />
    </>
  )
}

function ActionBar({ a }: { a: AlertDetail }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const operator = useOperator()
  const { on: lowData } = useLowData()
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
  const can = {
    acknowledge: open && a.status === 'new',
    escalate: open && a.status !== 'escalated',
    dismiss: open,
    reopen: !open,
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || act.isPending) return
      const key = e.key.toLowerCase()
      if (key === 'v' && !lowData) navigate(`/alerts/${a.id}/3d`)
      const map: Record<string, ActionName> = { a: 'acknowledge', e: 'escalate', d: 'dismiss', r: 'reopen' }
      const action = map[key]
      if (action && can[action]) act.mutate(action)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="shrink-0 border-t border-line-2 bg-void">
      {lowData ? (
        <div className="num flex h-9 w-full items-center justify-center gap-2 border-b border-line text-[11px] text-dim">
          <Box size={13} /> Not available in low-data mode
        </div>
      ) : (
        <Link to={`/alerts/${a.id}/3d`} className="btn !h-9 w-full !border-x-0 !border-t-0 !border-b-line">
          <Box size={13} /> 3D spread preview <span className="kbd ml-1">V</span>
        </Link>
      )}
      <div className="space-y-2 p-3">
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="ADD NOTE…" className="field w-full" />
        <div className="flex flex-wrap gap-1">
          {QUICK_NOTES.map((n) => (
            <button
              key={n}
              onClick={() => setNote(n)}
              className={`num h-5 border px-1.5 text-[10px] ${note === n ? 'border-text text-text' : 'border-line-2 text-dim hover:text-muted'}`}
            >
              {n}
            </button>
          ))}
        </div>
        {open ? (
          <div className="grid grid-cols-[1fr_1.3fr_1fr] gap-1.5">
            <button disabled={!can.acknowledge || act.isPending} onClick={() => act.mutate('acknowledge')} className="btn !h-9">
              Ack <span className="kbd">A</span>
            </button>
            <button disabled={!can.escalate || act.isPending} onClick={() => act.mutate('escalate')} className="btn btn-danger !h-9">
              Escalate <span className="kbd">E</span>
            </button>
            <button disabled={act.isPending} onClick={() => act.mutate('dismiss')} className="btn !h-9 !text-muted">
              Dismiss <span className="kbd">D</span>
            </button>
          </div>
        ) : (
          <button onClick={() => act.mutate('reopen')} disabled={act.isPending} className="btn !h-9 w-full">
            Reopen <span className="kbd">R</span>
          </button>
        )}
        {act.isError && <p className="num text-[10.5px] text-escalate">{(act.error as Error).message}</p>}
      </div>
    </div>
  )
}
