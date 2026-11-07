import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, ClipboardList, Flame, MessageSquare, Play, RefreshCw, Square, Wifi } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { api, type ScenarioSummary, type SourceHealth } from '../api'
import { setLowData, useLowData } from '../lib/lowData'
import { setOperator, useOperator } from '../lib/operator'
import { TIERS, setTier, useTier, type Tier } from '../lib/tier'
import { Mark } from './ui'

const SOURCE_LABELS: Record<string, string> = { firms: 'FIRMS', open_meteo: 'WX', mesh: 'MESH' }

const HEALTH_STYLE: Record<SourceHealth['status'], { dot: string; text: string }> = {
  ok: { dot: 'bg-ok', text: 'text-ok' },
  stale: { dot: 'bg-investigate', text: 'text-investigate' },
  down: { dot: 'bg-escalate blink', text: 'text-escalate' },
  sample: { dot: 'bg-sample', text: 'text-sample' },
  skipped: { dot: 'bg-dim', text: 'text-dim' },
}

function SourceStatus({ name, h }: { name: string; h: SourceHealth }) {
  const st = HEALTH_STYLE[h.status]
  const detail = h.status === 'skipped' ? 'OFF' : h.status === 'sample' ? 'SAMPLE' : h.status === 'down' ? 'DOWN' : h.age_min != null ? `${h.age_min}M` : 'NO DATA'
  const title = h.last_error ? `Last error: ${h.last_error}` : h.last_ok ? `Last OK ${h.last_ok}` : ''
  return (
    <span className="flex items-center gap-2" title={title}>
      <span className="label">{SOURCE_LABELS[name] ?? name}</span>
      <span className={`h-1.5 w-1.5 ${st.dot}`} />
      <span className={`num text-[10px] tracking-[0.1em] ${st.text}`}>{detail}</span>
    </span>
  )
}

function SourceChips({ sources }: { sources: Record<string, SourceHealth> }) {
  const entries = Object.entries(sources)
  const working = entries.filter(([, h]) => h.status === 'ok' || h.status === 'sample').length
  const detail = entries.map(([k, h]) => `${k}: ${h.status}`).join('\n')
  return (
    <>
      <span className="hidden items-center gap-5 min-[1700px]:flex">
        {entries.filter(([k]) => k in SOURCE_LABELS).map(([k, h]) => <SourceStatus key={k} name={k} h={h} />)}
      </span>
      <span className="flex items-center gap-2" title={detail}>
        <span className="label">Feeds</span>
        <span className={`num text-[10px] tracking-[0.1em] ${working === entries.length ? 'text-ok' : 'text-investigate'}`}>
          {working}/{entries.length}
        </span>
      </span>
    </>
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

const SCENARIO_LABEL: Record<string, string> = {
  'cottonwood-creek': 'Demo fire',
  'cottonwood-creek-packet': 'Packet: line fault',
  'cottonwood-creek-packet-no-fault': 'Packet: no line fault',
  'cottonwood-creek-packet-ngfs': 'Packet: no fault, NGFS',
}

const Divider = () => <span className="h-4 w-px shrink-0 bg-line-2" />

export function TopBar({
  onRunScenario,
  onStopScenario,
  scenarioRunning,
  scenarioStopping,
  scenarios,
  scenarioSlug,
  onPickScenario,
  threeDId,
  threeDSelected,
  burnOpen,
  onBurnLog,
  boardOpen,
  onToggleBoard,
}: {
  onRunScenario?: () => void
  onStopScenario?: () => void
  scenarioRunning?: boolean
  scenarioStopping?: boolean
  scenarios?: ScenarioSummary[]
  scenarioSlug?: string
  onPickScenario?: (slug: string) => void
  threeDId?: number | null
  threeDSelected?: boolean
  burnOpen?: boolean
  onBurnLog?: () => void
  boardOpen?: boolean
  onToggleBoard?: () => void
}) {
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
  const { tier, online } = useTier()

  return (
    <header className="flex h-10 shrink-0 items-center gap-4 overflow-hidden border-b border-line bg-void px-4 whitespace-nowrap">
      <div className="flex min-w-0 flex-1 items-center gap-4 overflow-hidden">
      <div className="flex shrink-0 items-center gap-2.5 text-text">
        <Mark size={16} />
        <span className="num hidden text-[13px] font-semibold tracking-[0.28em] 2xl:inline">FIREWATCH</span>
      </div>
      <Divider />
      <nav className="flex shrink-0 items-center gap-1">
        {(
          [
            ['/', 'Console'],
            ['/planner', 'FireNode planner'],
            ...(online ? ([['/board', 'Board']] as const) : []),
          ] as const
        ).map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `num px-2 py-[2px] text-[10px] tracking-[0.14em] uppercase ${isActive ? 'bg-raised text-text' : 'text-dim hover:text-muted'}`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
      <TierSwitch tier={tier} />
      <Divider />
      {threeDId != null && (
        <Link
          to={`/alerts/${threeDId}/3d`}
          className="btn !h-6 shrink-0 !border-investigate/60 !text-investigate"
          title={threeDSelected ? 'Open the 3D spread view for the selected alert' : 'Open the 3D spread view for the top alert. Select another alert first to see its own.'}
        >
          <Box size={12} /> 3D view
          <span className="hidden text-[10px] font-normal tracking-normal text-muted min-[1900px]:inline">{threeDSelected ? 'selected alert' : 'top alert'}</span>
        </Link>
      )}
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
      <div className="hidden items-center gap-5 min-[1400px]:flex">
        <Divider />
        {health.data && online && <SourceChips sources={health.data.sources} />}
        {!online && <span className="num text-[10px] tracking-[0.12em] text-degraded">INTERNET DOWN · FIRENODE ONLY</span>}
        {health.isError && <span className="num text-[10px] tracking-[0.12em] text-escalate">Can't reach the Firewatch server. Showing the last update.</span>}
      </div>
      </div>

      <div className="flex shrink-0 items-center gap-4">
        <button
          role="switch"
          aria-checked={lowData}
          onClick={() => setLowData(!lowData)}
          className={`btn !h-6 ${lowData ? '!border-degraded !text-degraded' : ''}`}
          aria-label={`Low data ${lowData ? 'on' : 'off'}`}
          title={`Low data ${lowData ? 'on' : 'off'}. Use less data: no map pictures, slower updates`}
        >
          <Wifi size={11} /> <span className="hidden xl:inline">Low data {lowData ? 'on' : 'off'}</span>
        </button>
        {onBurnLog && (
          <button onClick={onBurnLog} aria-pressed={burnOpen} aria-label="Burn log" title="Burn log" className={`btn !h-6 ${burnOpen ? '!border-text' : ''}`}>
            <ClipboardList size={11} /> <span className="hidden 2xl:inline">Burn log</span>
          </button>
        )}
        <div className="hidden items-center gap-4 min-[1900px]:flex">
          <Clock />
          <Divider />
          <label className="flex items-center gap-2">
            <span className="label">OP</span>
            <input value={operator} onChange={(e) => setOperator(e.target.value)} className="field w-28 !h-6 uppercase" aria-label="Operator name" />
          </label>
        </div>
        {onToggleBoard && (
          <button
            type="button"
            onClick={onToggleBoard}
            aria-pressed={boardOpen}
            aria-label="Community board"
            title="Community board"
            className={`btn !h-6 ${boardOpen ? '!border-sample !text-sample' : ''}`}
          >
            <MessageSquare size={11} /> <span className="hidden 2xl:inline">Board</span>
          </button>
        )}
        {onRunScenario && scenarios && scenarios.length > 1 && (
          <select
            value={scenarioSlug}
            onChange={(e) => onPickScenario?.(e.target.value)}
            disabled={scenarioRunning}
            aria-label="Scenario to replay"
            title={scenarios.find((s) => s.slug === scenarioSlug)?.story}
            className="field hidden !h-6 max-w-44 xl:block"
          >
            {scenarios.map((s) => (
              <option key={s.slug} value={s.slug}>
                {SCENARIO_LABEL[s.slug] ?? s.title}
              </option>
            ))}
          </select>
        )}
        {onRunScenario && scenarioRunning && onStopScenario ? (
          <button
            onClick={onStopScenario}
            disabled={scenarioStopping}
            title="Stop the scenario where it is. Its alerts stay on screen; Run scenario starts it over."
            className="btn !h-8 !border-escalate !px-3.5 !text-[12.5px] !text-escalate"
          >
            <Square size={13} fill="currentColor" /> {scenarioStopping ? 'Stopping' : 'Stop scenario'}
          </button>
        ) : (
          onRunScenario && (
            <button
              onClick={onRunScenario}
              disabled={scenarioRunning}
              aria-label={scenarioRunning ? 'Scenario running' : 'Run scenario'}
              className="btn btn-danger !h-8 !px-3.5 !text-[12.5px]"
            >
              <Flame size={14} /> {scenarioRunning ? 'Scenario running' : 'Run scenario'}
            </button>
          )
        )}
        {mode === 'sample' && (
          <button
            onClick={() => replay.mutate()}
            disabled={replay.isPending || health.data?.replay_running}
            className="btn !h-8 !px-3.5 !text-[12.5px]"
          >
            <Play size={14} /> {health.data?.replay_running ? 'Satellite replay running' : 'Satellite replay'}
          </button>
        )}
        {mode === 'live' && online && (
          <button onClick={() => ingest.mutate()} disabled={ingest.isPending} className="btn hidden !h-6 md:inline-flex">
            <RefreshCw size={11} className={ingest.isPending ? 'animate-spin' : ''} /> Ingest
          </button>
        )}
      </div>
    </header>
  )
}

function TierSwitch({ tier }: { tier: Tier }) {
  return (
    <div role="radiogroup" aria-label="Tier to show" className="flex shrink-0 items-center border border-line">
      {TIERS.map((t) => (
        <button
          key={t.key}
          role="radio"
          aria-checked={tier === t.key}
          title={t.title}
          onClick={() => setTier(t.key)}
          className={`num px-2 py-[2px] text-[10px] tracking-[0.14em] uppercase ${
            tier === t.key ? (t.key === 'offline' ? 'bg-degraded/20 text-degraded' : 'bg-raised text-text') : 'text-dim hover:text-muted'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}
