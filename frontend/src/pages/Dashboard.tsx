import { useQuery } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { AlertDrawer } from '../components/AlertDrawer'
import { AlertList } from '../components/AlertList'
import { MapView } from '../components/MapView'
import { TopBar } from '../components/TopBar'
import { SUPPRESSION_LABEL } from '../lib/format'
import { filterQueue, type QueueTab } from '../lib/queue'

export function Dashboard() {
  const params = useParams()
  const navigate = useNavigate()
  const selectedId = params.id ? Number(params.id) : null
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [tab, setTab] = useState<QueueTab>('active')

  const alerts = useQuery({
    queryKey: ['alerts'],
    queryFn: () => api.alerts(true),
    refetchInterval: 5_000,
  })
  const all = alerts.data?.alerts ?? []
  const suppressed = alerts.data?.suppressed
  const onMap = tab === 'suppressed' ? all : filterQueue(all, tab)
  const close = useCallback(() => navigate('/'), [navigate])

  const counts = {
    escalate: all.filter((a) => a.recommendation === 'escalate').length,
    investigate: all.filter((a) => a.recommendation === 'investigate').length,
  }

  return (
    <div className="flex h-full flex-col bg-bg">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <AlertList
          alerts={all}
          tab={tab}
          setTab={setTab}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onSelect={(id) => navigate(`/alerts/${id}`)}
          onHover={setHoveredId}
        />
        <MapView alerts={onMap} selectedId={selectedId} hoveredId={hoveredId} onSelect={(id) => navigate(`/alerts/${id}`)} onHover={setHoveredId} />
        {selectedId != null && <AlertDrawer id={selectedId} onClose={close} />}
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
