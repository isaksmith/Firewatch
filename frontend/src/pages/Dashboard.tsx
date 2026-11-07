import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { SCENARIO, api } from '../api'
import { Attribution } from '../components/Attribution'
import { AlertDrawer } from '../components/AlertDrawer'
import { AlertList } from '../components/AlertList'
import { MapView } from '../components/MapView'
import { ScenarioStrip } from '../components/ScenarioStrip'
import { CommunityBoard } from '../components/CommunityBoard'
import { TopBar } from '../components/TopBar'
import { SUPPRESSION_LABEL } from '../lib/format'
import { filterQueue, type QueueTab } from '../lib/queue'

export function Dashboard() {
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
    queryKey: ['alerts'],
    queryFn: () => api.alerts(true),
    refetchInterval: running ? 1_500 : 5_000,
  })
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

  const all = alerts.data?.alerts ?? []
  const suppressed = alerts.data?.suppressed
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
        boardOpen={boardOpen}
        onToggleBoard={() => {
          if (!boardOpen && selectedId != null) navigate('/')
          setBoardPostId(null)
          setBoardOpen(!boardOpen)
        }}
      />
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
            navigate(`/alerts/${id}`)
          }}
          onHover={setHoveredId}
          onBoardPin={(post) => {
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
        {selectedId != null && <AlertDrawer id={selectedId} onClose={close} />}
        {boardOpen && selectedId == null && (
          <CommunityBoard focusId={boardPostId} onClose={() => setBoardOpen(false)} />
        )}
      </div>

      <footer className="num flex h-7 shrink-0 items-center gap-5 overflow-hidden border-t border-line bg-void px-4 text-[10px] tracking-[0.08em] whitespace-nowrap text-dim">
        {alerts.isError ? (
          <span className="text-escalate">BACKEND UNREACHABLE AT /API. IS UVICORN RUNNING ON 127.0.0.1:8000?</span>
        ) : (
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
        {alerts.data && <span className="ml-auto xl:ml-0">SYNC {alerts.data.generated_at.slice(11, 19)}Z</span>}
        <span className="ml-auto shrink-0 2xl:ml-0">
          <Attribution />
        </span>
      </footer>
    </div>
  )
}
