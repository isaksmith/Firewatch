import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Flame, Play, RefreshCw } from 'lucide-react'
import { api, type SourceHealth } from '../api'
import { setOperator, useOperator } from '../lib/operator'

const SOURCE_LABELS: Record<string, string> = { firms: 'FIRMS', open_meteo: 'Weather' }

function HealthChip({ name, h }: { name: string; h: SourceHealth }) {
  const color = {
    ok: 'text-emerald-400',
    stale: 'text-investigate',
    down: 'text-escalate',
    sample: 'text-sample',
  }[h.status]
  const detail = h.status === 'sample' ? 'sample data' : h.age_min != null ? `${h.age_min}m` : 'no data'
  const title = h.last_error ? `Last error: ${h.last_error}` : h.last_ok ? `Last OK ${h.last_ok}` : ''
  return (
    <span className="flex items-center gap-1.5 rounded bg-white/5 px-2 py-1 text-xs" title={title}>
      <span className={`text-[9px] ${color}`}>●</span>
      <span className="text-muted">{SOURCE_LABELS[name] ?? name}</span>
      <span className="tabular">{detail}</span>
    </span>
  )
}

export function TopBar() {
  const qc = useQueryClient()
  const operator = useOperator()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15_000 })
  const replay = useMutation({
    mutationFn: api.replay,
    onSuccess: () => setTimeout(() => qc.invalidateQueries(), 500),
  })
  const ingest = useMutation({ mutationFn: api.ingest, onSuccess: () => qc.invalidateQueries() })
  const mode = health.data?.mode

  return (
    <header className="flex h-12 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
      <div className="flex items-center gap-2 font-bold tracking-wide">
        <Flame size={18} className="text-escalate" />
        FIREWATCH
      </div>
      {mode === 'sample' && (
        <span className="rounded bg-sample/15 px-2 py-0.5 text-xs font-bold tracking-wider text-sample">SAMPLE</span>
      )}
      {mode === 'live' && (
        <span className="flex items-center gap-1.5 text-xs font-bold tracking-wider text-emerald-400">
          <span className="h-2 w-2 rounded-full bg-emerald-400" /> LIVE
        </span>
      )}
      <div className="flex items-center gap-2">
        {health.data && Object.entries(health.data.sources).map(([k, v]) => <HealthChip key={k} name={k} h={v} />)}
        {health.isError && <span className="text-xs text-escalate">Backend unreachable</span>}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {mode === 'sample' && (
          <button
            onClick={() => replay.mutate()}
            disabled={replay.isPending || health.data?.replay_running}
            className="flex items-center gap-1.5 rounded border border-sample/40 px-3 py-1 text-xs font-medium text-sample hover:bg-sample/10 disabled:opacity-50"
          >
            <Play size={13} /> {health.data?.replay_running ? 'Replaying…' : 'Replay sample'}
          </button>
        )}
        {mode === 'live' && (
          <button
            onClick={() => ingest.mutate()}
            disabled={ingest.isPending}
            className="flex items-center gap-1.5 rounded border border-line px-3 py-1 text-xs hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCw size={13} className={ingest.isPending ? 'animate-spin' : ''} /> Run ingest
          </button>
        )}
        <input
          value={operator}
          onChange={(e) => setOperator(e.target.value)}
          className="w-28 rounded border border-line bg-bg px-2 py-1 text-xs"
          aria-label="Operator name"
        />
      </div>
    </header>
  )
}
