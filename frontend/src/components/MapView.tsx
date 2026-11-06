import { useQuery } from '@tanstack/react-query'
import { Layers } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import Map, { Layer, Marker, NavigationControl, Source, type MapRef } from 'react-map-gl/maplibre'
import { api, type AlertSummary } from '../api'
import { REC_META } from '../lib/format'
import { BASEMAP_STYLE, KANSAS_VIEW } from '../lib/map'

interface Props {
  alerts: AlertSummary[]
  selectedId: number | null
  hoveredId: number | null
  onSelect: (id: number) => void
  onHover: (id: number | null) => void
}

const SIZE = { escalate: 22, investigate: 16, monitor: 10 }

export function MapView({ alerts, selectedId, hoveredId, onSelect, onHover }: Props) {
  const mapRef = useRef<MapRef>(null)
  const [layers, setLayers] = useState({ power_lines: true, static_sources: false, flint_hills: false })
  const [menuOpen, setMenuOpen] = useState(false)
  const lines = useQuery({ queryKey: ['layer', 'power_lines'], queryFn: () => api.layer('power_lines') })
  const statics = useQuery({ queryKey: ['layer', 'static_sources'], queryFn: () => api.layer('static_sources') })
  const flint = useQuery({ queryKey: ['layer', 'flint_hills'], queryFn: () => api.layer('flint_hills') })

  const selected = alerts.find((a) => a.id === selectedId)
  useEffect(() => {
    if (selected?.id) mapRef.current?.flyTo({ center: [selected.lon, selected.lat], zoom: 10, duration: 1200 })
  }, [selected?.id, selected?.lon, selected?.lat])

  return (
    <div className="relative flex-1">
      <Map ref={mapRef} initialViewState={KANSAS_VIEW} mapStyle={BASEMAP_STYLE} style={{ width: '100%', height: '100%' }}>
        <NavigationControl position="bottom-right" showCompass={false} />
        {layers.flint_hills && flint.data && (
          <Source id="flint" type="geojson" data={flint.data}>
            <Layer id="flint-fill" type="fill" paint={{ 'fill-color': '#38bdf8', 'fill-opacity': 0.06 }} />
            <Layer id="flint-line" type="line" paint={{ 'line-color': '#38bdf8', 'line-opacity': 0.4, 'line-dasharray': [2, 2] }} />
          </Source>
        )}
        {layers.power_lines && lines.data && (
          <Source id="lines" type="geojson" data={lines.data}>
            <Layer id="lines" type="line" paint={{ 'line-color': '#fbbf24', 'line-width': 1.5, 'line-opacity': 0.6 }} />
          </Source>
        )}
        {layers.static_sources && statics.data && (
          <Source id="statics" type="geojson" data={statics.data}>
            <Layer id="statics" type="circle" paint={{ 'circle-radius': 5, 'circle-color': '#64748b', 'circle-stroke-color': '#e6edf3', 'circle-stroke-width': 1 }} />
          </Source>
        )}
        {alerts.map((a) => {
          const size = SIZE[a.recommendation]
          const active = a.id === selectedId || a.id === hoveredId
          const pulse = a.recommendation === 'escalate' && a.status === 'new'
          return (
            <Marker key={a.id} longitude={a.lon} latitude={a.lat} anchor="center" onClick={(e) => { e.originalEvent.stopPropagation(); onSelect(a.id) }}>
              <div
                className="relative cursor-pointer"
                style={{ width: size, height: size }}
                onMouseEnter={() => onHover(a.id)}
                onMouseLeave={() => onHover(null)}
                title={`${a.score} · ${a.place_label}`}
              >
                {pulse && <span className="pulse-ring absolute inset-0 rounded-full" style={{ background: REC_META[a.recommendation].color }} />}
                <span
                  className="absolute inset-0 rounded-full border-2"
                  style={{
                    background: REC_META[a.recommendation].color,
                    borderColor: active ? '#ffffff' : 'rgba(0,0,0,0.5)',
                    transform: active ? 'scale(1.3)' : undefined,
                    transition: 'transform 120ms',
                  }}
                />
              </div>
            </Marker>
          )
        })}
      </Map>

      <div className="absolute right-3 top-3">
        <button
          onClick={() => setMenuOpen((o) => !o)}
          className="flex items-center gap-1.5 rounded border border-line bg-panel/90 px-3 py-1.5 text-xs backdrop-blur"
        >
          <Layers size={14} /> Layers
        </button>
        {menuOpen && (
          <div className="mt-1 space-y-1.5 rounded border border-line bg-panel/95 p-3 text-xs backdrop-blur">
            {(
              [
                ['power_lines', 'Transmission lines'],
                ['static_sources', 'Known heat sources'],
                ['flint_hills', 'Flint Hills'],
              ] as const
            ).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2">
                <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))} />
                {label}
              </label>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
