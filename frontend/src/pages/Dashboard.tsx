import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { AlertDrawer } from '../components/AlertDrawer'
import { AlertList } from '../components/AlertList'
import { MapView } from '../components/MapView'
import { TopBar } from '../components/TopBar'
import { SUPPRESSION_LABEL } from '../lib/format'

export function Dashboard() {
  const params = useParams()
  const navigate = useNavigate()
  const selectedId = params.id ? Number(params.id) : null
  const [hoveredId, setHoveredId] = useState<number | null>(null)
  const [minScore, setMinScore] = useState(40)
  const [showSuppressed, setShowSuppressed] = useState(false)

  const alerts = useQuery({
    queryKey: ['alerts', showSuppressed],
    queryFn: () => api.alerts(showSuppressed),
    refetchInterval: 5_000,
  })
  const list = alerts.data?.alerts ?? []
  const suppressed = alerts.data?.suppressed

  return (
    <div className="flex h-full flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <AlertList
          alerts={list}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onSelect={(id) => navigate(`/alerts/${id}`)}
          onHover={setHoveredId}
          minScore={minScore}
          setMinScore={setMinScore}
          showSuppressed={showSuppressed}
          setShowSuppressed={setShowSuppressed}
          suppressedTotal={suppressed?.total ?? 0}
        />
        <MapView
          alerts={list.filter((a) => a.score >= minScore || a.recommendation === 'monitor')}
          selectedId={selectedId}
          hoveredId={hoveredId}
          onSelect={(id) => navigate(`/alerts/${id}`)}
          onHover={setHoveredId}
        />
        {selectedId != null && <AlertDrawer id={selectedId} onClose={() => navigate('/')} />}
      </div>
      {suppressed && suppressed.total > 0 && (
        <button
          onClick={() => setShowSuppressed((s) => !s)}
          className="shrink-0 border-t border-line bg-panel px-4 py-2 text-left text-xs text-muted hover:text-text"
        >
          <b className="tabular text-text">{suppressed.total}</b> events suppressed:{' '}
          {(Object.keys(SUPPRESSION_LABEL) as (keyof typeof SUPPRESSION_LABEL)[])
            .filter((k) => suppressed[k] > 0)
            .map((k) => `${suppressed[k]} ${SUPPRESSION_LABEL[k]}${suppressed[k] > 1 && k !== 'low_signal' ? 's' : ''}`)
            .join(' · ')}
          <span className="ml-2 text-sample">{showSuppressed ? 'Hide' : 'Show'}</span>
        </button>
      )}
      {alerts.isError && (
        <div className="shrink-0 bg-escalate/20 px-4 py-2 text-xs text-red-200">
          Cannot reach the backend at /api. Is uvicorn running on port 8000?
        </div>
      )}
    </div>
  )
}
