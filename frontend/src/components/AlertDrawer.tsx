import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Box, ShieldAlert, X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type ActionName, type AlertDetail, type Message } from '../api'
import { REC_META, centralTime, compass, kmhToMph, latLon, pad3, seenLabel, trackId } from '../lib/format'
import { useOperator } from '../lib/operator'
import { EvidenceGlyph, KV, RecTag, ScoreReadout, SectionHeader, StatusTag } from './ui'

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
  const q = useQuery({ queryKey: ['alert', id], queryFn: () => api.alert(id), refetchInterval: 3_000 })

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !isTyping(e)) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <aside className="absolute inset-0 z-20 flex w-full flex-col bg-panel md:static md:inset-auto md:z-auto md:w-[400px] md:shrink-0 md:border-l md:border-line">
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
          {a.level_reason && <div className="mt-2 text-[12px] leading-snug text-muted">{a.level_reason}</div>}
          <div className="mt-3">
            <KV k="First seen" v={seenLabel(a.first_seen, a.is_sample)} />
            <KV k="Last seen" v={centralTime(a.last_seen, a.is_sample)} />
            <div className="grid grid-cols-2 gap-x-6">
              <KV k="Scorer" v={a.scorer ?? 'no satellite'} />
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

        {a.evidence.length > 0 && (
          <Section
            title="Evidence"
            right={<span className="num text-[10px] text-dim">2 SOURCES = ESCALATE</span>}
          >
            <ul className="space-y-2">
              {a.evidence.map((e, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className="pt-[3px]">
                    <EvidenceGlyph counts={e.counts} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`text-[12.5px] ${e.counts === 'no' ? 'text-muted' : 'text-text'}`}>{e.label}</span>
                    {e.note && <span className="block text-[11px] text-dim">{e.note}</span>}
                  </span>
                  <span className="num shrink-0 pt-[2px] text-[10px] text-dim">{centralTime(e.at)}</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        {a.response && <ResponseSection a={a} />}

        {a.messages.length > 0 && <TextsSection messages={a.messages} />}

        {a.reasons.length > 0 && (
          <Section title="Why this score" right={<span className="num text-[10px] text-dim">TREND {a.score_trend.join(' → ')}</span>}>
            <ul className="space-y-2">
              {a.reasons.slice(0, 6).map((r) => (
                <li key={r.feature} className="grid grid-cols-[36px_1fr_72px] items-center gap-3">
                  <span className={`num text-right text-[12px] font-semibold ${r.contribution >= 0 ? 'text-text' : 'text-ok'}`}>
                    {r.contribution > 0 ? '+' : ''}
                    {r.contribution}
                  </span>
                  <span className="truncate text-[12.5px] text-text">{r.label}</span>
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
        )}

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
                {w.dew_point_c != null && <KV k="Dew pt" v={`${Math.round(w.dew_point_c)}°C`} />}
                {w.pressure_hpa != null && <KV k="Pressure" v={`${Math.round(w.pressure_hpa)} HPA`} />}
                {w.vpd_kpa != null && <KV k="VPD" v={`${w.vpd_kpa.toFixed(1)} KPA`} />}
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
          {a.detections.length === 0 ? (
            <p className="text-[12px] text-dim">No satellite pass has seen this yet.</p>
          ) : (
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
          )}
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

const PURPOSE_LABEL: Record<string, string> = {
  ask_neighbor: 'Ask neighbor',
  duty_fyi: 'Duty FYI',
  duty_escalate: 'Duty: page?',
  ladder: 'Ladder',
  ladder_dispatch: 'Ladder: dispatch',
  page: 'Page',
  page_dispatch: 'Page dispatch',
  downwind: 'Downwind warning',
  helper: 'Ask for equipment',
  mutual_aid_draft: 'Mutual-aid draft',
  mutual_aid: 'Mutual aid',
  reply: 'Auto-reply',
}

function ResponseSection({ a }: { a: AlertDetail }) {
  const r = a.response!
  const t = (iso: string | null | undefined) => (iso ? centralTime(iso) : '—')
  return (
    <Section title="Response" right={<span className="num text-[10px] text-dim">{r.texts_sent} TEXTS OUT</span>}>
      {r.awaiting && !r.decision && (
        <div className="mb-3 flex items-center gap-2 border border-line border-l-2 border-l-investigate bg-investigate/5 px-3 py-2 text-[11.5px]">
          <span className="blink h-1.5 w-1.5 bg-investigate" />
          Waiting on <span className="font-semibold">{r.awaiting}</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-x-6">
        <KV k="Asked" v={t(r.investigate_at)} />
        <KV k="Confirmed" v={t(r.escalate_at)} />
        <KV k="Paged" v={r.page_at ? t(r.page_at) : r.decision === 'no' ? 'STOOD DOWN' : '—'} accent={r.page_at ? '#ff4b2b' : undefined} />
        <KV k="Responding" v={String(r.responders.length)} />
      </div>
      {r.decision_by && (
        <div className="num mt-1 text-[10.5px] text-dim">
          {r.decision?.toUpperCase()} BY {r.decision_by.toUpperCase()}
        </div>
      )}
      {r.plan && (
        <div className="mt-3 border border-line bg-void px-3 py-2 text-[11.5px]">
          <div className="flex justify-between">
            <span className="label">Next hour</span>
            <span className="num text-text">
              ~{r.plan.acres_60} AC · WIND {r.plan.wind.from} {r.plan.wind.mph} MPH
            </span>
          </div>
          {r.plan.downwind.length > 0 && (
            <ul className="mt-2 space-y-1">
              {r.plan.downwind.map((d) => (
                <li key={d.contact_id} className="flex justify-between">
                  <span>{d.name}</span>
                  <span className="num text-investigate">~{d.eta_min} MIN</span>
                </li>
              ))}
            </ul>
          )}
          {r.plan.helpers.length > 0 && (
            <div className="mt-2 text-[11px] text-muted">
              Equipment asked: {r.plan.helpers.map((h) => h.name).join(', ')}
            </div>
          )}
        </div>
      )}
      {r.crew.length > 0 && (
        <div className="mt-3 border border-line bg-void px-3 py-2 text-[11.5px]">
          <div className="flex justify-between">
            <span className="label">Crew on the mesh</span>
            <span className="num text-[10px] text-dim">LIVE GPS</span>
          </div>
          <ul className="mt-2 space-y-1">
            {r.crew.map((c) => {
              const responding = r.responders.some((x) => x.contact_id === c.contact_id)
              return (
                <li key={c.contact_id} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">
                    {c.name}
                    {responding && <span className="num ml-2 text-[10px] text-ok">RESPONDING</span>}
                  </span>
                  <span className="num shrink-0 text-text">
                    {c.mi} MI {c.from_fire} <span className="text-dim">{c.position_min_ago < 1 ? 'NOW' : `${c.position_min_ago}M`}</span>
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      {r.mutual_aid && (
        <div className="mt-3 text-[11.5px]">
          <span className="label mr-2">Mutual aid</span>
          {r.mutual_aid.sent_at ? (
            <span className="text-text">
              requested {t(r.mutual_aid.sent_at)} by {r.mutual_aid.sent_by}
            </span>
          ) : (
            <span className="text-investigate">drafted: {r.mutual_aid.reason}</span>
          )}
        </div>
      )}
    </Section>
  )
}

/** Collapse a page that went to 18 people into one row. */
function groupMessages(messages: Message[]) {
  const out: { m: Message; n: number; names: string[] }[] = []
  for (const m of messages) {
    const last = out[out.length - 1]
    if (
      last &&
      m.direction === 'out' &&
      last.m.direction === 'out' &&
      last.m.purpose === m.purpose &&
      last.m.body === m.body &&
      last.m.channel === m.channel
    ) {
      last.n += 1
      last.names.push(m.contact_name ?? m.phone ?? '?')
    } else {
      out.push({ m, n: 1, names: [m.contact_name ?? m.phone ?? '?'] })
    }
  }
  return out
}

const MESH_STATUS: Record<string, { label: string; cls: string }> = {
  delivered: { label: 'DELIVERED', cls: 'text-ok' },
  relayed: { label: 'RELAYED', cls: 'text-investigate' },
  failed: { label: 'NOT DELIVERED', cls: 'text-escalate' },
  sent: { label: 'SENT', cls: 'text-dim' },
}

function MeshTag({ m }: { m: Message }) {
  const st = m.direction === 'out' ? MESH_STATUS[m.status] : undefined
  return (
    <span className="flex gap-1.5">
      <span className="border border-ok/50 px-1 text-ok">MESH</span>
      {st && <span className={st.cls}>{st.label}</span>}
    </span>
  )
}

function TextsSection({ messages }: { messages: Message[] }) {
  const groups = groupMessages(messages)
  const anyMesh = messages.some((m) => m.channel === 'mesh')
  return (
    <Section title="Texts" right={<span className="num text-[10px] text-dim">{anyMesh ? 'SMS + MESH' : 'SMS'} · 160 CHAR</span>}>
      <ol className="space-y-2.5">
        {groups.map(({ m, n, names }) => {
          const inbound = m.direction === 'in'
          return (
            <li key={m.id} className={`flex flex-col ${inbound ? 'items-start' : 'items-end'}`}>
              <div className="num mb-0.5 flex gap-2 text-[9.5px] tracking-[0.06em] text-dim">
                <span>{centralTime(m.created_at)}</span>
                {m.channel === 'mesh' && <MeshTag m={m} />}
                <span className={inbound ? 'text-sample' : 'text-muted'}>
                  {inbound ? `FROM ${(m.contact_name ?? m.phone ?? '').toUpperCase()}` : `${(PURPOSE_LABEL[m.purpose ?? ''] ?? m.purpose ?? '').toUpperCase()} → ${n > 1 ? `${n} PEOPLE` : names[0].toUpperCase()}`}
                </span>
              </div>
              <div
                title={n > 1 ? names.join(', ') : undefined}
                className={`max-w-[92%] border px-2.5 py-1.5 text-[11.5px] leading-snug ${
                  inbound ? 'border-sample/40 bg-sample/5 text-text' : 'border-line-2 bg-void text-muted'
                }`}
              >
                {m.body}
              </div>
            </li>
          )
        })}
      </ol>
    </Section>
  )
}

function DecisionBar({ a }: { a: AlertDetail }) {
  const qc = useQueryClient()
  const operator = useOperator()
  const decide = useMutation({
    mutationFn: (action: 'page' | 'no' | 'send') => api.decide(a.id, action, operator),
    onSuccess: (data) => {
      qc.setQueryData(['alert', a.id], data)
      qc.invalidateQueries({ queryKey: ['alerts'] })
      qc.invalidateQueries({ queryKey: ['scenario'] })
    },
  })
  const r = a.response
  if (!r) return null
  const canPage = !r.decision
  const canSend = r.decision === 'page' && !r.mutual_aid?.sent_at
  if (!canPage && !canSend) return null
  return (
    <div className="space-y-1.5 border-b border-line p-3">
      {canPage && (
        <div className="grid grid-cols-[1.6fr_1fr] gap-1.5">
          <button disabled={decide.isPending} onClick={() => decide.mutate('page')} className="btn btn-danger !h-9">
            Page district
          </button>
          <button disabled={decide.isPending} onClick={() => decide.mutate('no')} className="btn !h-9 !text-muted">
            Stand down
          </button>
        </div>
      )}
      {canSend && (
        <button disabled={decide.isPending} onClick={() => decide.mutate('send')} className="btn !h-8 w-full">
          {r.mutual_aid ? 'Send mutual-aid request' : 'Request mutual aid'}
        </button>
      )}
      {decide.isError && <p className="num text-[10.5px] text-escalate">{(decide.error as Error).message}</p>}
    </div>
  )
}

function ActionBar({ a }: { a: AlertDetail }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
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
  const can = {
    acknowledge: open,
    escalate: open && a.status !== 'escalated',
    dismiss: open,
    reopen: !open,
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || act.isPending) return
      const key = e.key.toLowerCase()
      if (key === 'v') navigate(`/alerts/${a.id}/3d`)
      const map: Record<string, ActionName> = { a: 'acknowledge', e: 'escalate', d: 'dismiss', r: 'reopen' }
      const action = map[key]
      if (action && can[action]) act.mutate(action)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="shrink-0 border-t border-line-2 bg-void">
      <DecisionBar a={a} />
      <Link to={`/alerts/${a.id}/3d`} className="btn !h-9 w-full !border-x-0 !border-t-0 !border-b-line">
        <Box size={13} /> 3D spread preview <span className="kbd ml-1">V</span>
      </Link>
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
