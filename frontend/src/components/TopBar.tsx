import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, ClipboardList, Flame, MessageCircleQuestion, MessageSquare, Play, RefreshCw, Square, Wifi } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
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
      <span className="flex items-center gap-5">
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
      <span className="text-dim">{ct}</span>
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

/** The mark and the pages: the start of every page's header, the public board's included. */
export function BrandNav() {
  const { online } = useTier()
  const pages: [string, string][] = [
    ['/', 'Console'],
    ['/planner', 'FireNode planner'],
    ['/design', 'FireNode design'],
    ...(online ? ([['/board', 'Board']] as [string, string][]) : []),
  ]
  // On a phone the links run past the edge; bring the current page's into view.
  const navRef = useRef<HTMLElement>(null)
  useEffect(() => {
    navRef.current?.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [])
  return (
    <>
      <div className="flex shrink-0 items-center gap-2.5 text-text">
        <Mark size={16} />
        <span className="num hidden text-[13px] font-semibold tracking-[0.28em] min-[1320px]:inline">FIREWATCH</span>
      </div>
      <Divider />
      <nav ref={navRef} className="flex shrink-0 items-center gap-1">
        {pages.map(([to, label]) => (
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
    </>
  )
}

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
  askOpen,
  onToggleAsk,
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
  askOpen?: boolean
  onToggleAsk?: () => void
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
    <header className="shrink-0 border-b border-line bg-void whitespace-nowrap">
      {/* Top row, always visible: the mark, the pages, and the main actions. */}
      <div className="flex h-12 items-center gap-4 overflow-hidden px-4">
        <BrandNav />

        <div className="ml-auto flex shrink-0 items-center gap-3">
          {onToggleAsk && (
            <button
              type="button"
              onClick={onToggleAsk}
              aria-pressed={askOpen}
              aria-label="Ask Firewatch"
              title="Ask Firewatch a question, as a resident would by text"
              className={`btn !h-8 !px-3.5 !text-[12.5px] !border-sample ${askOpen ? '!bg-sample !text-void' : '!text-sample'}`}
            >
              <MessageCircleQuestion size={14} /> Ask Firewatch
            </button>
          )}
          {onToggleBoard && (
            <button
              type="button"
              onClick={onToggleBoard}
              aria-pressed={boardOpen}
              aria-label="Community board"
              title="Community board"
              className={`btn !h-8 !px-3.5 !text-[12.5px] ${boardOpen ? '!border-sample !text-sample' : ''}`}
            >
              <MessageSquare size={14} /> Board
            </button>
          )}
          {(onToggleAsk || onToggleBoard) && (onRunScenario || mode) && <Divider />}
          {onRunScenario && scenarios && scenarios.length > 1 && (
            <select
              value={scenarioSlug}
              onChange={(e) => onPickScenario?.(e.target.value)}
              disabled={scenarioRunning}
              aria-label="Scenario to replay"
              title={scenarios.find((s) => s.slug === scenarioSlug)?.story}
              className="field !h-8 max-w-44"
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
              aria-label={health.data?.replay_running ? 'Satellite replay running' : 'Satellite replay'}
              title="Replay past satellite detections"
              className="btn !h-8 !px-3.5 !text-[12.5px]"
            >
              <Play size={14} />
              <span className="hidden min-[1320px]:inline">{health.data?.replay_running ? 'Satellite replay running' : 'Satellite replay'}</span>
            </button>
          )}
          {mode === 'live' && online && (
            <button onClick={() => ingest.mutate()} disabled={ingest.isPending} className="btn !h-8 !px-3.5 !text-[12.5px]">
              <RefreshCw size={14} className={ingest.isPending ? 'animate-spin' : ''} /> Ingest
            </button>
          )}
        </div>
      </div>

      {/* Second row: views, data status and settings. It scrolls sideways when the window is too narrow; a mouse
          wheel scrolls it too. */}
      <div
        className="topbar-scroll flex h-9 items-center gap-4 overflow-x-auto overflow-y-hidden border-t border-line px-4 [&>*]:shrink-0"
        onWheel={(e) => {
          if (e.deltaX === 0 && e.deltaY !== 0) e.currentTarget.scrollLeft += e.deltaY
        }}
      >
        <TierSwitch tier={tier} />
        <Divider />
        {threeDId != null && (
          <Link
            to={`/alerts/${threeDId}/3d`}
            className="btn !h-6 shrink-0 !border-investigate/60 !text-investigate"
            title={threeDSelected ? 'Open the 3D spread view for the selected alert' : 'Open the 3D spread view for the top alert. Select another alert first to see its own.'}
          >
            <Box size={12} /> 3D view
            <span className="text-[10px] font-normal tracking-normal text-muted">{threeDSelected ? 'selected alert' : 'top alert'}</span>
          </Link>
        )}
        <span className="label">Kansas AOI · Confirmation Layer</span>
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
        <div className="flex items-center gap-5">
          <Divider />
          {health.data && online && <SourceChips sources={health.data.sources} />}
          {!online && <span className="num text-[10px] tracking-[0.12em] text-degraded">INTERNET DOWN · FIRENODE ONLY</span>}
          {health.isError && <span className="num text-[10px] tracking-[0.12em] text-escalate">Can't reach the Firewatch server. Showing the last update.</span>}
        </div>

        <div className="ml-auto flex items-center gap-4 pl-4">
          <button
            role="switch"
            aria-checked={lowData}
            onClick={() => setLowData(!lowData)}
            className={`btn !h-6 ${lowData ? '!border-degraded !text-degraded' : ''}`}
            aria-label={`Low data ${lowData ? 'on' : 'off'}`}
            title={`Low data ${lowData ? 'on' : 'off'}. Use less data: no map pictures, slower updates`}
          >
            <Wifi size={11} /> <span>Low data {lowData ? 'on' : 'off'}</span>
          </button>
          {onBurnLog && (
            <button onClick={onBurnLog} aria-pressed={burnOpen} aria-label="Burn log" title="Burn log" className={`btn !h-6 ${burnOpen ? '!border-text' : ''}`}>
              <ClipboardList size={11} /> <span>Burn log</span>
            </button>
          )}
          <Clock />
          <Divider />
          <label className="flex items-center gap-2">
            <span className="label">OP</span>
            <input value={operator} onChange={(e) => setOperator(e.target.value)} className="field w-28 !h-6 uppercase" aria-label="Operator name" />
          </label>
        </div>
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
