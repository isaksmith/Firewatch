import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardList, Play, RefreshCw, Wifi } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type SourceHealth } from '../api'
import { setLowData, useLowData } from '../lib/lowData'
import { setOperator, useOperator } from '../lib/operator'
import { Mark } from './ui'

const SOURCE_LABELS: Record<string, string> = { firms: 'FIRMS', open_meteo: 'WX' }

const HEALTH_STYLE: Record<SourceHealth['status'], { dot: string; text: string }> = {
  ok: { dot: 'bg-ok', text: 'text-ok' },
  stale: { dot: 'bg-investigate', text: 'text-investigate' },
  down: { dot: 'bg-escalate blink', text: 'text-escalate' },
  sample: { dot: 'bg-sample', text: 'text-sample' },
}

function SourceStatus({ name, h }: { name: string; h: SourceHealth }) {
  const st = HEALTH_STYLE[h.status]
  const detail = h.status === 'sample' ? 'SAMPLE' : h.status === 'down' ? 'DOWN' : h.age_min != null ? `${h.age_min}M` : 'NO DATA'
  const title = h.last_error ? `Last error: ${h.last_error}` : h.last_ok ? `Last OK ${h.last_ok}` : ''
  return (
    <span className="flex items-center gap-2" title={title}>
      <span className="label">{SOURCE_LABELS[name] ?? name}</span>
      <span className={`h-1.5 w-1.5 ${st.dot}`} />
      <span className={`num text-[10px] tracking-[0.1em] ${st.text}`}>{detail}</span>
    </span>
  )
}

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const z = now.toISOString().slice(11, 19)
  const ct = now.toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'short' })
  return (
    <span className="num flex items-center gap-3 text-[11px]">
      <span className="text-text">{z}Z</span>
      <span className="hidden text-dim xl:inline">{ct}</span>
    </span>
  )
}

const Divider = () => <span className="h-4 w-px bg-line-2" />

export function TopBar({ burnOpen, onBurnLog }: { burnOpen: boolean; onBurnLog: () => void }) {
  const { on: lowData } = useLowData()
  const qc = useQueryClient()
  const operator = useOperator()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: lowData ? 60_000 : 15_000 })
  const replay = useMutation({
    mutationFn: api.replay,
    onSuccess: () => setTimeout(() => qc.invalidateQueries(), 500),
  })
  const ingest = useMutation({ mutationFn: api.ingest, onSuccess: () => qc.invalidateQueries() })
  const mode = health.data?.mode

  return (
    <header className="flex h-10 shrink-0 items-center gap-4 overflow-hidden border-b border-line bg-void px-4 whitespace-nowrap">
      <div className="flex items-center gap-2.5 text-text">
        <Mark size={16} />
        <span className="num text-[13px] font-semibold tracking-[0.28em]">FIREWATCH</span>
      </div>
      <Divider />
      <span className="label hidden 2xl:inline">Kansas AOI · Confirmation Layer</span>
      {mode === 'sample' && (
        <span className="num border border-sample/50 px-1.5 py-[1px] text-[10px] font-medium tracking-[0.14em] text-sample">
          SAMPLE REPLAY
        </span>
      )}
      {mode === 'live' && (
        <span className="num flex items-center gap-1.5 border border-ok/50 px-1.5 py-[1px] text-[10px] font-medium tracking-[0.14em] text-ok">
          <span className="blink h-1.5 w-1.5 bg-ok" /> LIVE
        </span>
      )}
      <Divider />
      <div className="hidden items-center gap-5 lg:flex">
        {health.data && Object.entries(health.data.sources).map(([k, v]) => <SourceStatus key={k} name={k} h={v} />)}
        {health.isError && <span className="num text-[10px] tracking-[0.12em] text-escalate">BACKEND UNREACHABLE</span>}
      </div>

      <div className="ml-auto flex items-center gap-4">
        <Clock />
        <Divider />
        <button onClick={onBurnLog} aria-pressed={burnOpen} className={`btn !h-6 ${burnOpen ? '!border-text' : ''}`}>
          <ClipboardList size={11} /> Burn log
        </button>
        <button
          role="switch"
          aria-checked={lowData}
          onClick={() => setLowData(!lowData)}
          className={`btn !h-6 ${lowData ? '!border-degraded !text-degraded' : ''}`}
          title="Use less data: no map pictures, slower updates"
        >
          <Wifi size={11} /> Low data {lowData ? 'on' : 'off'}
        </button>
        {lowData && (
          <a href="/lite" className="text-[11.5px] text-sample underline underline-offset-2">
            Open the one-bar page
          </a>
        )}
        <Divider />
        <label className="flex items-center gap-2">
          <span className="label">OP</span>
          <input value={operator} onChange={(e) => setOperator(e.target.value)} className="field w-28 !h-6 uppercase" aria-label="Operator name" />
        </label>
        {mode === 'sample' && (
          <button onClick={() => replay.mutate()} disabled={replay.isPending || health.data?.replay_running} className="btn !h-6">
            <Play size={11} /> {health.data?.replay_running ? 'Replaying' : 'Replay'}
          </button>
        )}
        {mode === 'live' && (
          <button onClick={() => ingest.mutate()} disabled={ingest.isPending} className="btn !h-6">
            <RefreshCw size={11} className={ingest.isPending ? 'animate-spin' : ''} /> Ingest
          </button>
        )}
      </div>
    </header>
  )
}
