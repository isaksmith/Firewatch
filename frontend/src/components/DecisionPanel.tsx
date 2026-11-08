import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronRight, CircleDot } from 'lucide-react'
import { useState } from 'react'
import { api, type Playbook, type PlaybookOption } from '../api'
import { useOperator } from '../lib/operator'
import { useTier } from '../lib/tier'
import { LastData } from './LastData'

const pct = (p: number) => (p >= 0.995 ? '>99%' : p < 0.01 ? '<1%' : `${Math.round(p * 100)}%`)
const pColor = (p: number) => (p >= 0.5 ? 'text-escalate' : p >= 0.15 ? 'text-investigate' : 'text-muted')

function Header({ p }: { p: Playbook }) {
  const [open, setOpen] = useState<'chain' | 'model' | null>(null)
  const pr = p.probability
  return (
    <div className="px-4 pt-3">
      <div className="flex items-baseline gap-2">
        <span
          className="text-[12.5px] text-muted"
          title="FireCast's estimate: starts from how common a wildfire is for the first signal, then multiplies the odds by each piece of evidence. Built on stated assumptions, so read it as a ranking until outcomes are logged."
        >
          Chance it's a real fire
        </span>
        <span className={`text-[20px] font-semibold ${pColor(pr.p)}`}>{pct(pr.p)}</span>
        <button onClick={() => setOpen(open === 'chain' ? null : 'chain')} className="ml-auto inline-flex items-center gap-0.5 text-[11px] text-dim hover:text-text">
          {open === 'chain' ? <ChevronDown size={12} /> : <ChevronRight size={12} />} how we got here
        </button>
      </div>
      {open === 'chain' && (
        <ol className="mt-1.5 space-y-1 border-l border-line-2 pl-3 text-[11.5px] leading-snug">
          {pr.steps.map((s, i) => (
            <li key={i} className="flex gap-2">
              <span className="w-10 shrink-0 text-right text-dim">{s.factor != null ? `x${s.factor}` : 'base'}</span>
              <span className="min-w-0 flex-1 text-text/85">{s.text}</span>
              <span className={`shrink-0 font-semibold ${pColor(s.p)}`}>{pct(s.p)}</span>
            </li>
          ))}
        </ol>
      )}
      <div className="mt-1.5 flex flex-wrap gap-1">
        {p.risk.map((r) => <span key={r} className="rounded-sm bg-void px-1.5 py-0.5 text-[10.5px] text-text/75">{r}</span>)}
      </div>
      <button onClick={() => setOpen(open === 'model' ? null : 'model')} className="mt-1.5 inline-flex items-center gap-0.5 text-[11px] text-dim hover:text-text">
        {open === 'model' ? <ChevronDown size={12} /> : <ChevronRight size={12} />} How this is decided
      </button>
      {open === 'model' && (
        <div className="mt-1 text-[11px] leading-snug">
          <p className="mb-1.5 text-text/80">
            Each option's expected loss = chance it's a fire × acres burned before enough help is there + chance it isn't × what the false alarm
            costs, in acres we'd trade to avoid it. Lowest wins. The weights below are planning assumptions until outcomes are logged.
          </p>
          <dl className="max-h-48 space-y-1 overflow-y-auto">
            {p.model.map((m) => (
              <div key={m.key} className="grid grid-cols-[1fr_auto] gap-x-2">
                <dt className="text-text/80">{m.key.replaceAll('_', ' ')}</dt>
                <dd className="text-right font-semibold">{typeof m.value === 'object' ? Object.entries(m.value).map(([k, v]) => `${k} x${v}`).join(', ') : m.value}</dd>
                <dd className="col-span-2 text-dim">{m.source}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}

const KEY_METRICS = ["If it's a fire", "If it's not", 'Expected loss']

function Option({ o, selected, onSelect, onConfirm, busy }: {
  o: PlaybookOption
  selected: boolean
  onSelect: () => void
  onConfirm: () => void
  busy: boolean
}) {
  return (
    <li
      className={`border px-3 py-2.5 transition-colors ${o.done ? '' : 'cursor-pointer'} ${
        selected ? 'border-text bg-raised' : o.recommended ? 'border-ok/60 bg-ok/5 hover:border-ok' : 'border-line-2 hover:border-muted'
      }`}
      onClick={o.done ? undefined : onSelect}
    >
      <div className="flex items-start gap-2">
        {o.done ? (
          <Check size={14} className="mt-[2px] shrink-0 text-ok" />
        ) : (
          <CircleDot size={14} className={`mt-[2px] shrink-0 ${selected ? 'text-text' : 'text-dim'}`} />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13.5px] leading-snug font-semibold">{o.title}</span>
            {o.recommended && <span className="rounded-sm bg-ok px-1.5 py-[1px] text-[10.5px] font-semibold text-void">Recommended</span>}
            {o.done && <span className="text-[11px] text-ok">Done {o.done}</span>}
          </div>
          {o.why && !o.done && <p className="mt-1 text-[12px] leading-snug text-text/80">{o.why}</p>}
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11.5px]">
            {o.metrics.filter((m) => selected || KEY_METRICS.includes(m.label)).map((m) => (
              <div key={m.label} className="contents">
                <dt className="text-dim">{m.label}</dt>
                <dd className={m.label === 'Expected loss' ? 'font-semibold text-text' : 'text-text/85'}>{m.value}</dd>
              </div>
            ))}
          </dl>
          {selected && (
            <div className="mt-3 border-t border-line-2 pt-2">
              <div className="mb-1 text-[11px] font-semibold text-muted">This will:</div>
              <ul className="space-y-1 text-[12px] leading-snug text-text/90">
                {o.effects.map((e) => <li key={e}>→ {e}</li>)}
              </ul>
              <button
                disabled={busy}
                onClick={(e) => {
                  e.stopPropagation()
                  onConfirm()
                }}
                className={`mt-3 h-8 w-full text-[12px] font-semibold disabled:opacity-40 ${
                  o.recommended ? 'bg-ok text-void hover:brightness-110' : 'bg-text text-void hover:bg-white'
                }`}
              >
                {busy ? 'Working…' : `Do this${o.recommended ? '' : ' instead'}`}
              </button>
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

function Receipts({ p }: { p: Playbook }) {
  if (p.receipts.length === 0) return null
  return (
    <div className="px-4 pb-3">
      <div className="mb-1.5 text-[11px] font-semibold text-muted">Done so far</div>
      <ol className="space-y-2">
        {p.receipts.map((r, i) => (
          <li key={i} className="flex gap-2 text-[12px] leading-snug">
            <Check size={13} className="mt-[2px] shrink-0 text-ok" />
            <div className="min-w-0">
              <div>
                <span className="font-semibold">{r.title}</span>
                <span className="text-dim"> · {r.clock} · {r.by}</span>
                {r.followed_recommendation === false && <span className="ml-1 text-investigate">(overrode the recommendation)</span>}
              </div>
              <div className="text-text/75">{r.results.join(' · ')}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

/** Which engine produced this panel. The LLM in FireCast Plus words texted answers and FireMesh channel updates;
 *  the probability and expected-loss figures here are the FireCast model in every tier. */
function CastBrand({ eventId }: { eventId: number }) {
  const { castName, castPlus, online } = useTier()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
  const llmOff = castPlus && health.data && !health.data.llm_configured
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-4 pt-2.5">
      <span className="label !text-text">{castName}</span>
      <span className="text-[10.5px] text-dim">
        {castPlus ? 'ML model; the LLM answers texted questions and posts channel updates' : online ? 'ML score and expected-loss model' : 'ML model on the station computer'}
      </span>
      {llmOff && <span className="ml-auto text-[10.5px] text-degraded" title="Set OPENROUTER_API_KEY on the server">LLM not configured</span>}
      {!online && <LastData eventId={eventId} className="basis-full text-[10.5px] leading-snug" />}
    </div>
  )
}

export function DecisionPanel({ eventId }: { eventId: number }) {
  const qc = useQueryClient()
  const operator = useOperator()
  const q = useQuery({ queryKey: ['options', eventId], queryFn: () => api.options(eventId), refetchInterval: 3_000 })
  const [picked, setPicked] = useState<string | null>(null)
  const choose = useMutation({
    mutationFn: (optionId: string) => api.chooseOption(eventId, optionId, operator),
    onSuccess: (p) => {
      qc.setQueryData(['options', eventId], p)
      setPicked(null)
      qc.invalidateQueries({ queryKey: ['alert', eventId] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
      qc.invalidateQueries({ queryKey: ['scenario'] })
    },
  })
  const p = q.data
  if (!p) return q.isLoading ? <div className="border-b border-line px-4 py-3 text-[12px] text-dim">Working out the options…</div> : null
  const d = p.decision
  const selected = picked && d?.options.some((o) => o.id === picked && !o.done) ? picked : null
  const waiting = d?.options.some((o) => o.done)

  return (
    <section className="border-b border-line bg-panel-2">
      <CastBrand eventId={eventId} />
      <Header p={p} />
      {d ? (
        <div className="px-4 pt-3 pb-3">
          <div className="mb-2 flex items-baseline justify-between">
            <h3 className="text-[15px] font-semibold">{d.question}</h3>
            <span className="text-[11px] text-dim">as of {p.clock}</span>
          </div>
          {waiting ? (
            <p className="mb-2 text-[12px] text-muted">Done; waiting for the next signal. The options update when it arrives.</p>
          ) : (
            <p className="mb-2 text-[12px] text-muted">Click an option to see exactly what it does.</p>
          )}
          <ul className="space-y-2">
            {d.options.map((o) => (
              <Option key={o.id} o={o} selected={selected === o.id} busy={choose.isPending}
                onSelect={() => setPicked(o.id)} onConfirm={() => choose.mutate(o.id)} />
            ))}
          </ul>
          {choose.isError && <p className="mt-2 text-[11.5px] text-escalate">{(choose.error as Error).message}</p>}
        </div>
      ) : (
        <p className="px-4 pt-3 pb-3 text-[12.5px] text-muted">No decision waiting. Everything below has been done.</p>
      )}
      <Receipts p={p} />
    </section>
  )
}
