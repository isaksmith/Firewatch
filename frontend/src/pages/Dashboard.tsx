import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useCallback, useState, useSyncExternalStore } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { AlertDrawer } from '../components/AlertDrawer'
import { AlertList } from '../components/AlertList'
import { MapView } from '../components/MapView'
import { BurnLog } from '../components/BurnLog'
import { TopBar } from '../components/TopBar'
import { dismissAutoBanner, noteFetchFailure, noteFetchTime, setLowData, useLowData } from '../lib/lowData'
import { SUPPRESSION_LABEL, clock12 } from '../lib/format'
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
  const params = useParams()
  const navigate = useNavigate()
  const selectedId = params.id ? Number(params.id) : null
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [tab, setTab] = useState<QueueTab>('active')

  const { on: lowData, auto: autoLowData } = useLowData()
  const [burnOpen, setBurnOpen] = useState(false)

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
            noteFetchFailure()
            throw e
          }
        },
    placeholderData: keepPreviousData,
    // While the server is down, retry every 10 s so the list comes back quickly (not after a 60 s lite poll).
    refetchInterval: (q) => (q.state.status === 'error' ? 10_000 : lowData ? 60_000 : 5_000),
  })
  // Keep the last good list, even across the full/lite switch, so a server outage never empties the screen.
  const [lastGood, setLastGood] = useState<number | null>(null)
  const [lastData, setLastData] = useState<typeof alerts.data>()
  if (alerts.data && !alerts.isPlaceholderData && alerts.dataUpdatedAt && alerts.dataUpdatedAt !== lastGood) {
    setLastGood(alerts.dataUpdatedAt)
    setLastData(alerts.data)
  }
  const shown = alerts.data ?? lastData
  const offline = !online || alerts.isError
  const loading = shown == null && !alerts.isError
  const all = shown?.alerts ?? []
  const suppressed = shown?.suppressed
  const onMap = tab === 'suppressed' ? all : filterQueue(all, tab)
  const close = useCallback(() => navigate('/'), [navigate])

  const counts = {
    escalate: all.filter((a) => a.recommendation === 'escalate').length,
    investigate: all.filter((a) => a.recommendation === 'investigate').length,
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      <TopBar burnOpen={burnOpen} onBurnLog={() => setBurnOpen((o) => !o)} />
      {offline && (
        <div role="status" className="flex shrink-0 items-center gap-3 border-b border-line bg-investigate/10 px-4 py-1.5 text-[12.5px] text-investigate">
          Offline. {lastGood ? `Last updated ${clock12(new Date(lastGood).toISOString())}` : 'No data yet'}
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
      <div className="flex min-h-0 flex-1">
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
        <MapView alerts={onMap} selectedId={selectedId} hoveredId={hoveredId} onSelect={(id) => navigate(`/alerts/${id}`)} onHover={setHoveredId} />
        {burnOpen ? <BurnLog onClose={() => setBurnOpen(false)} /> : selectedId != null && <AlertDrawer id={selectedId} onClose={close} />}
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
      </footer>
    </div>
  )
}
