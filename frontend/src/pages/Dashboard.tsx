import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { SCENARIO, api } from '../api'
import { Attribution } from '../components/Attribution'
import { AlertDrawer } from '../components/AlertDrawer'
import { BurnLog } from '../components/BurnLog'
import { AlertList } from '../components/AlertList'
import { MapView } from '../components/MapView'
import { ScenarioStrip } from '../components/ScenarioStrip'
import { CommunityBoard } from '../components/CommunityBoard'
import { TopBar } from '../components/TopBar'
import { SUPPRESSION_LABEL, clock12 } from '../lib/format'
import { dismissAutoBanner, noteFetchFailure, noteFetchTime, setLowData, useLowData } from '../lib/lowData'
import { filterQueue, type QueueTab } from '../lib/queue'

const subscribeOnline = (cb: () => void) => {
  window.addEventListener('online', cb)
  window.addEventListener('offline', cb)
  return () => {
    window.removeEventListener('online', cb)
    window.removeEventListener('offline', cb)
  }
}

export function Dashboard() {
  const online = useSyncExternalStore(subscribeOnline, () => navigator.onLine)
  const { on: lowData, auto: autoLowData } = useLowData()
  const [burnOpen, setBurnOpen] = useState(false)
  const params = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const selectedId = params.id ? Number(params.id) : null
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [tab, setTab] = useState<QueueTab>('active')
  const [scenarioHidden, setScenarioHidden] = useState(false)
  const [slug, setSlug] = useState(SCENARIO)
  const [boardOpen, setBoardOpen] = useState(false)
  const [boardPostId, setBoardPostId] = useState<number | null>(null)

  const scenarios = useQuery({ queryKey: ['scenarios'], queryFn: api.scenarios, staleTime: Infinity })
  const scenario = useQuery({
    queryKey: ['scenario', slug],
    queryFn: () => api.scenario(slug),
    refetchInterval: (q) => (q.state.data?.running ? 1_000 : 10_000),
    retry: false,
  })
  const running = scenario.data?.running ?? false
  const alerts = useQuery({
    queryKey: ['alerts', lowData ? 'lite' : 'full'],
    queryFn: lowData
      ? api.liteAlerts
      : async () => {
          const t0 = performance.now()
          try {
            const r = await api.alerts(true)
            noteFetchTime(performance.now() - t0)
            return r
          } catch (e) {
            noteFetchFailure(performance.now() - t0)
            throw e
          }
        },
    placeholderData: keepPreviousData,
    // While the server is down, retry every 10 s so the list comes back quickly (not after a 60 s lite poll).
    refetchInterval: (q) => (q.state.status === 'error' ? 10_000 : lowData ? 60_000 : running ? 1_500 : 5_000),
  })
  // Keep the last good list in component state, whatever the query key does, so an outage or the
  // full/lite switch never empties the screen.
  const [last, setLast] = useState<{ at: number; data: NonNullable<typeof alerts.data> } | null>(null)
  if (alerts.data && !alerts.isPlaceholderData && alerts.dataUpdatedAt && alerts.dataUpdatedAt !== last?.at) {
    setLast({ at: alerts.dataUpdatedAt, data: alerts.data })
  }
  const shown = alerts.data ?? last?.data
  const offline = !online || alerts.isError
  const loading = shown == null && !alerts.isError
  // Follow the scenario's fire once it appears, so the drawer shows the texts as they go out.
  const autoSelected = useRef(false)
  const runScenario = useMutation({
    mutationFn: () => api.runScenario(slug),
    onSuccess: () => {
      setScenarioHidden(false)
      autoSelected.current = false
      navigate('/') // the open alert belongs to the replay just cleared
      setTimeout(() => qc.invalidateQueries(), 400)
    },
  })
  const fireId = scenario.data?.events[0]?.id
  useEffect(() => {
    if (running && fireId && !autoSelected.current) {
      autoSelected.current = true
      navigate(`/alerts/${fireId}`)
    }
  }, [running, fireId, navigate])

  const all = shown?.alerts ?? []
  const suppressed = shown?.suppressed
  const onMap = tab === 'suppressed' ? all : filterQueue(all, tab)
  const close = useCallback(() => navigate('/'), [navigate])
  const showStrip = !scenarioHidden && scenario.data && scenario.data.t_min != null

  const counts = {
    escalate: all.filter((a) => a.recommendation === 'escalate').length,
    investigate: all.filter((a) => a.recommendation === 'investigate').length,
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      <TopBar
        onRunScenario={() => runScenario.mutate()}
        scenarioRunning={running || runScenario.isPending}
        scenarios={scenarios.data}
        scenarioSlug={slug}
        onPickScenario={setSlug}
        threeDId={selectedId ?? onMap[0]?.id ?? null}
        threeDSelected={selectedId != null}
        burnOpen={burnOpen}
        onBurnLog={() => {
          setBoardOpen(false)
          setBurnOpen((o) => !o)
        }}
        boardOpen={boardOpen}
        onToggleBoard={() => {
          if (!boardOpen && selectedId != null) navigate('/')
          setBurnOpen(false)
          setBoardPostId(null)
          setBoardOpen(!boardOpen)
        }}
      />
      {offline && (
        <div role="status" className="flex shrink-0 items-center gap-3 border-b border-line bg-investigate/10 px-4 py-1.5 text-[12.5px] text-investigate">
          Offline. {last ? `Last updated ${clock12(new Date(last.at).toISOString())}` : 'No data yet'}
        </div>
      )}
      {lowData && autoLowData && (
        <div role="status" className="flex shrink-0 items-center gap-4 border-b border-line bg-degraded/10 px-4 py-1.5 text-[12.5px]">
          <span>Low data mode is on because your connection looks slow.</span>
          <button onClick={() => setLowData(false)} className="btn !h-7">
            Undo
          </button>
          <button onClick={dismissAutoBanner} className="text-dim hover:text-text">
            Keep it
          </button>
        </div>
      )}
      {showStrip && (
        <ScenarioStrip
          s={scenario.data!}
          onClose={() => setScenarioHidden(true)}
          onReplay={() => runScenario.mutate()}
          replaying={running || runScenario.isPending}
        />
      )}
      <div className="relative flex min-h-0 flex-1 flex-col md:flex-row">
        <AlertList
          alerts={all}
          tab={tab}
          setTab={setTab}
          suppressed={suppressed}
          lowData={lowData}
          loading={loading}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onSelect={(id) => navigate(`/alerts/${id}`)}
          onHover={setHoveredId}
        />
        <MapView
          alerts={onMap}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onSelect={(id) => {
            setBoardOpen(false)
            setBurnOpen(false)
            navigate(`/alerts/${id}`)
          }}
          onHover={setHoveredId}
          onBoardPin={(post) => {
            setBurnOpen(false)
            if (post.event_id != null) {
              setBoardOpen(false)
              navigate(`/alerts/${post.event_id}`)
            } else {
              if (selectedId != null) navigate('/')
              setBoardPostId(post.id)
              setBoardOpen(true)
            }
          }}
        />
        {burnOpen ? (
          <BurnLog onClose={() => setBurnOpen(false)} />
        ) : (
          selectedId != null && <AlertDrawer id={selectedId} onClose={close} />
        )}
        {boardOpen && !burnOpen && selectedId == null && (
          <CommunityBoard focusId={boardPostId} onClose={() => setBoardOpen(false)} />
        )}
      </div>

      <footer className="num flex h-7 shrink-0 items-center gap-5 overflow-hidden border-t border-line bg-void px-4 text-[10px] tracking-[0.08em] whitespace-nowrap text-dim">
        {alerts.isError && <span className="text-escalate">Can't reach the Firewatch server. Showing the last update.</span>}
        {shown && (
          <>
            <span>
              <span className="text-escalate">{String(counts.escalate).padStart(2, '0')}</span> ESC
            </span>
            <span>
              <span className="text-investigate">{String(counts.investigate).padStart(2, '0')}</span> INV
            </span>
            {suppressed && suppressed.total > 0 && (
              <button onClick={() => setTab(tab === 'suppressed' ? 'active' : 'suppressed')} className="min-w-0 truncate hover:text-muted">
                <span className="text-muted">{String(suppressed.total).padStart(2, '0')}</span> SUPPRESSED:{' '}
                {(Object.keys(SUPPRESSION_LABEL) as (keyof typeof SUPPRESSION_LABEL)[])
                  .filter((k) => suppressed[k] > 0)
                  .map((k) => `${suppressed[k]} ${SUPPRESSION_LABEL[k]}${suppressed[k] > 1 && k !== 'low_signal' ? 's' : ''}`)
                  .join(' · ')
                  .toUpperCase()}
              </button>
            )}
          </>
        )}
        <span className="ml-auto hidden 2xl:inline">
          KEYS <span className="text-muted">A</span> ACK · <span className="text-muted">E</span> ESCALATE ·{' '}
          <span className="text-muted">D</span> DISMISS · <span className="text-muted">V</span> 3D · <span className="text-muted">ESC</span> CLOSE
        </span>
        <span className="ml-auto hidden xl:inline 2xl:ml-0">PUBLIC DATA ONLY</span>
        {shown && <span className="ml-auto xl:ml-0">SYNC {shown.generated_at.slice(11, 19)}Z</span>}
        <span className="ml-auto shrink-0 2xl:ml-0">
          <Attribution />
        </span>
      </footer>
    </div>
  )
}
