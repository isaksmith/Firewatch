import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import Map, { Layer, Marker, NavigationControl, ScaleControl, Source, useMap, type MapRef } from 'react-map-gl/maplibre'
import { api, type AlertSummary, type MeshNode, type SensorReadings } from '../api'
import { REC_META, latLon, trackId } from '../lib/format'
import { AOI_BBOX, BASEMAP_STYLE, KANSAS_VIEW, ringPolygon } from '../lib/map'
import { FEEDS, LiveLayers, LiveToggles, useLiveFeeds, type FeedKey } from './LiveFeeds'
import { TrackGlyph } from './ui'

interface Props {
  alerts: AlertSummary[]
  selectedId: number | null
  hoveredId: number | null
  onSelect: (id: number) => void
  onHover: (id: number | null) => void
}

const SIZE = { escalate: 18, investigate: 14, monitor: 9 }
const RINGS_KM = [5, 10]

const AOI: GeoJSON.Feature = {
  type: 'Feature',
  properties: {},
  geometry: {
    type: 'LineString',
    coordinates: [
      [AOI_BBOX[0], AOI_BBOX[1]],
      [AOI_BBOX[2], AOI_BBOX[1]],
      [AOI_BBOX[2], AOI_BBOX[3]],
      [AOI_BBOX[0], AOI_BBOX[3]],
      [AOI_BBOX[0], AOI_BBOX[1]],
    ],
  },
}

type LayerKey = 'power_lines' | 'static_sources' | 'flint_hills' | 'aoi' | 'district' | 'distribution_lines' | 'dry_grid' | 'wind_lines' | 'mesh'

const SWATCH: Record<LayerKey, string> = {
  aoi: 'h-0 w-4 border-t border-dashed border-sample/70',
  district: 'h-2 w-4 border border-[#e6e8eb]/60',
  power_lines: 'h-px w-4 bg-[#c9d4e0]',
  static_sources: 'h-2 w-2 rounded-full border border-muted',
  flint_hills: 'h-2 w-4 border border-dashed border-ok/70',
  distribution_lines: 'h-px w-4 bg-[#8fa3b8]',
  dry_grid: 'h-2 w-2 rounded-full bg-[#ffb21a]',
  wind_lines: 'h-0.5 w-4 bg-[#ff5c5c]',
  mesh: 'h-2 w-2 rotate-45 bg-ok',
}

const MESH_FRESH_MIN = 30
const PM25_HIGH = 35

function sensorLine(s: SensorReadings | null): { text: string; high: boolean } | null {
  if (!s || Date.now() - Date.parse(s.reading_at) > MESH_FRESH_MIN * 60_000) return null
  const parts = [
    s.pm25 != null && `PM2.5 ${Math.round(s.pm25)}`,
    s.temp_c != null && `${Math.round(s.temp_c)}°C`,
    s.rh_pct != null && `RH ${Math.round(s.rh_pct)}%`,
  ].filter(Boolean)
  return parts.length ? { text: parts.join(' · '), high: (s.pm25 ?? 0) >= PM25_HIGH } : null
}

function MeshMarker({ n }: { n: MeshNode }) {
  const fresh = n.position_min_ago != null && n.position_min_ago <= MESH_FRESH_MIN
  const label = n.contact_name ?? n.long_name ?? n.short_name ?? n.node_id
  const age = n.position_min_ago == null ? '' : n.position_min_ago < 1 ? 'NOW' : `${n.position_min_ago}M`
  const reading = sensorLine(n.sensors)
  return (
    <Marker longitude={n.lon!} latitude={n.lat!} anchor="center">
      <div
        className="relative"
        title={`${label} · ${n.node_id}${n.battery_pct != null ? ` · battery ${n.battery_pct}%` : ''}${n.snr != null ? ` · SNR ${n.snr}` : ''}`}
      >
        <span className={`block h-2 w-2 rotate-45 ${fresh ? 'bg-ok' : 'border border-dim bg-void'}`} />
        <span
          className={`num pointer-events-none absolute top-1/2 left-full ml-2 -translate-y-1/2 bg-void/80 px-1 text-[10px] whitespace-nowrap ${
            fresh ? 'text-ok' : 'text-dim'
          }`}
        >
          {n.is_gateway ? 'STATION RADIO' : label.toUpperCase()} <span className="text-dim">{age}</span>
          {reading && (
            <span className={`block ${reading.high ? 'text-investigate' : 'text-muted'}`}>{reading.text}</span>
          )}
        </span>
      </div>
    </Marker>
  )
}

export function MapView({ alerts, selectedId, hoveredId, onSelect, onHover }: Props) {
  const mapRef = useRef<MapRef>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  // One side panel at a time: opening an alert closes the layers panel.
  useEffect(() => {
    if (selectedId != null) setPanelOpen(false)
  }, [selectedId])
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    power_lines: true,
    static_sources: true,
    flint_hills: false,
    aoi: true,
    district: true,
    distribution_lines: false,
    dry_grid: false,
    wind_lines: false,
    mesh: true,
  })
  const [liveOn, setLiveOn] = useState<Record<FeedKey, boolean>>(() => Object.fromEntries(FEEDS.map((f) => [f.key, false])) as Record<FeedKey, boolean>)
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
  const keyConfigured = !!health.data?.firms_key_configured
  const feeds = useLiveFeeds(liveOn, keyConfigured)
  const meshNodes = useQuery({ queryKey: ['mesh-nodes'], queryFn: api.meshNodes, refetchInterval: 10_000 })
  const placed = (meshNodes.data ?? []).filter((n) => n.lat != null && n.lon != null)
  const district = useQuery({ queryKey: ['district'], queryFn: api.district, retry: false })
  const lines = useQuery({ queryKey: ['layer', 'power_lines'], queryFn: () => api.layer('power_lines') })
  const statics = useQuery({ queryKey: ['layer', 'static_sources'], queryFn: () => api.layer('static_sources') })
  const dist = useQuery({ queryKey: ['layer', 'distribution_lines'], queryFn: () => api.layer('distribution_lines'), enabled: layers.distribution_lines })
  const grid = useQuery({ queryKey: ['risk', 'grid'], queryFn: () => api.riskGrid(), enabled: layers.dry_grid })
  const windLines = useQuery({ queryKey: ['risk', 'wind'], queryFn: () => api.linesUnderWind(), enabled: layers.wind_lines })
  const flint = useQuery({ queryKey: ['layer', 'flint_hills'], queryFn: () => api.layer('flint_hills') })

  const selected = alerts.find((a) => a.id === selectedId)
  const [mapReady, setMapReady] = useState(false)
  useEffect(() => {
    if (mapReady && selected?.id) mapRef.current?.flyTo({ center: [selected.lon, selected.lat], zoom: 10, duration: 1200 })
  }, [mapReady, selected?.id, selected?.lon, selected?.lat])

  const rings = useMemo<GeoJSON.FeatureCollection | null>(
    () =>
      selected
        ? { type: 'FeatureCollection', features: RINGS_KM.map((km) => ringPolygon(selected.lat, selected.lon, km)) }
        : null,
    [selected],
  )

  const rank = (a: AlertSummary) => ['monitor', 'investigate', 'escalate'].indexOf(a.recommendation) * 1000 + (a.score ?? 100)
  const ordered = [...alerts].sort((a, b) => (a.id === selectedId ? 1 : b.id === selectedId ? -1 : rank(a) - rank(b)))

  return (
    <div className="relative min-h-0 flex-1 bg-void">
      <Map
        ref={mapRef}
        initialViewState={{ bounds: [AOI_BBOX[0], AOI_BBOX[1], AOI_BBOX[2], AOI_BBOX[3]], fitBoundsOptions: { padding: 40 } }}
        mapStyle={BASEMAP_STYLE}
        style={{ width: '100%', height: '100%' }}
        attributionControl={{ compact: true }}
        onLoad={() => {
          if (import.meta.env.DEV) (window as unknown as { __map?: unknown }).__map = mapRef.current?.getMap()
          setMapReady(true)
        }}
      >
        <NavigationControl position="bottom-right" showCompass={false} />
        <ScaleControl position="bottom-left" unit="imperial" maxWidth={90} />
        {layers.aoi && (
          <Source id="aoi" type="geojson" data={AOI}>
            <Layer id="aoi" type="line" paint={{ 'line-color': '#5cc8ff', 'line-width': 1, 'line-opacity': 0.35, 'line-dasharray': [6, 4] }} />
          </Source>
        )}
        {layers.district && district.data && (
          <Source id="district" type="geojson" data={district.data.boundary}>
            <Layer id="district-fill" type="fill" paint={{ 'fill-color': '#e6e8eb', 'fill-opacity': 0.025 }} />
            <Layer id="district-line" type="line" paint={{ 'line-color': '#e6e8eb', 'line-opacity': 0.45, 'line-width': 1 }} />
          </Source>
        )}
        {layers.flint_hills && flint.data && (
          <Source id="flint" type="geojson" data={flint.data}>
            <Layer id="flint-fill" type="fill" paint={{ 'fill-color': '#3ddc97', 'fill-opacity': 0.05 }} />
            <Layer id="flint-line" type="line" paint={{ 'line-color': '#3ddc97', 'line-opacity': 0.5, 'line-width': 1, 'line-dasharray': [2, 3] }} />
          </Source>
        )}
        {layers.power_lines && lines.data && (
          <Source id="lines" type="geojson" data={lines.data}>
            <Layer id="lines-glow" type="line" paint={{ 'line-color': '#c9d4e0', 'line-width': 4, 'line-opacity': 0.06 }} />
            <Layer id="lines" type="line" paint={{ 'line-color': '#c9d4e0', 'line-width': 1, 'line-opacity': 0.7 }} />
          </Source>
        )}
        {layers.distribution_lines && dist.data && (
          <Source id="dist" type="geojson" data={dist.data}>
            <Layer id="dist" type="line" paint={{ 'line-color': '#8fa3b8', 'line-width': 0.8, 'line-opacity': 0.6 }} />
          </Source>
        )}
        {layers.dry_grid && grid.data && (
          <Source id="drygrid" type="geojson" data={grid.data}>
            <Layer id="drygrid" type="circle" paint={{ 'circle-radius': 6, 'circle-color': ['interpolate', ['linear'], ['coalesce', ['get', 'rh'], 100], 10, '#ff5c5c', 25, '#ffb21a', 50, '#3ddc97'], 'circle-opacity': 0.45 }} />
          </Source>
        )}
        {layers.wind_lines && windLines.data && (
          <Source id="windlines" type="geojson" data={windLines.data}>
            <Layer id="windlines" type="line" paint={{ 'line-color': '#ff5c5c', 'line-width': 2.5, 'line-opacity': 0.85 }} />
          </Source>
        )}
        {layers.static_sources && statics.data && (
          <Source id="statics" type="geojson" data={statics.data}>
            <Layer
              id="statics"
              type="circle"
              paint={{ 'circle-radius': 4, 'circle-color': 'transparent', 'circle-stroke-color': '#8b939d', 'circle-stroke-width': 1 }}
            />
          </Source>
        )}
        {rings && (
          <Source id="rings" type="geojson" data={rings}>
            <Layer id="rings" type="line" paint={{ 'line-color': '#e6e8eb', 'line-width': 1, 'line-opacity': 0.3, 'line-dasharray': [2, 3] }} />
          </Source>
        )}
        {selected &&
          RINGS_KM.map((km) => (
            <Marker key={km} longitude={selected.lon} latitude={selected.lat + km / 110.57} anchor="bottom">
              <span className="num pointer-events-none text-[9px] tracking-[0.12em] whitespace-nowrap text-muted">{km} KM</span>
            </Marker>
          ))}

        {ordered.map((a) => {
          const size = SIZE[a.recommendation]
          const isSel = a.id === selectedId
          const active = isSel || a.id === hoveredId
          const ping = a.recommendation === 'escalate' && a.status === 'new'
          const showLabel = a.recommendation !== 'monitor' || active
          return (
            <Marker
              key={a.id}
              longitude={a.lon}
              latitude={a.lat}
              anchor="center"
              onClick={(e) => {
                e.originalEvent.stopPropagation()
                onSelect(a.id)
              }}
            >
              <div
                className="relative cursor-pointer"
                style={{ width: size, height: size }}
                onMouseEnter={() => onHover(a.id)}
                onMouseLeave={() => onHover(null)}
              >
                {ping && <span className="ping-diamond absolute inset-0" style={{ border: `1px solid ${REC_META.escalate.color}` }} />}
                {isSel && (
                  <span className="reticle brackets absolute" style={{ inset: -12, ['--b' as string]: '#ffffff' }} />
                )}
                <TrackGlyph rec={a.recommendation} size={size} active={active} />
                {showLabel && (
                  <span
                    className={`num pointer-events-none absolute top-1/2 left-full ml-2 flex -translate-y-1/2 items-center gap-1.5 px-1 py-[1px] text-[10px] whitespace-nowrap ${
                      active ? 'bg-text text-void' : 'bg-void/80 text-muted'
                    }`}
                  >
                    <span>{trackId(a.id)}</span>
                    <span className="font-semibold" style={{ color: active ? undefined : REC_META[a.recommendation].color }}>
                      {a.score ?? REC_META[a.recommendation].short}
                    </span>
                  </span>
                )}
              </div>
            </Marker>
          )
        })}
        <LiveLayers feeds={feeds} />
        {layers.mesh && placed.map((n) => <MeshMarker key={n.node_id} n={n} />)}
        <CursorReadout />
      </Map>

      <div className="pointer-events-none absolute inset-3 brackets" style={{ ['--b' as string]: '#3a414b' }} />

      <div className="hud absolute top-4 right-4 flex max-h-[calc(100%-5rem)] w-[200px] flex-col overflow-y-auto">
        <button onClick={() => setPanelOpen((o) => !o)} className="flex h-7 w-full items-center justify-between px-3 hover:bg-raised">
          <span className="label whitespace-nowrap">
            Layers
            <span className="num ml-1.5 text-text">{Object.values(layers).filter(Boolean).length + Object.values(liveOn).filter(Boolean).length} on</span>
          </span>
          <ChevronDown size={12} className={`text-dim transition-transform ${panelOpen ? 'rotate-180' : ''}`} />
        </button>
        {panelOpen && (
          <>
            <div className="space-y-2 border-t border-line p-3">
              {(
                [
                  ['aoi', 'Kansas AOI'],
                  ['district', district.data?.settings.short_name ?? 'Fire district'],
                  ['power_lines', 'Transmission'],
                  ['static_sources', 'Known heat sources'],
                  ['flint_hills', 'Flint Hills'],
                  ['distribution_lines', 'Distribution (partial)'],
                  ['dry_grid', 'Dry air grid'],
                  ['wind_lines', 'Lines under wind'],
                  ...(placed.length > 0 ? ([['mesh', `Mesh radios (${placed.length})`]] as const) : []),
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="flex cursor-pointer items-center gap-2.5 text-[11.5px] text-muted hover:text-text">
                  <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))} />
                  <span className="flex-1">{label}</span>
                  <span className="flex w-4 items-center justify-center">
                    <span className={SWATCH[k]} />
                  </span>
                </label>
              ))}
            </div>
            <LiveToggles feeds={feeds} on={liveOn} setOn={(k, v) => setLiveOn((o) => ({ ...o, [k]: v }))} keyConfigured={keyConfigured} />
            <div className="flex h-7 items-center border-t border-b border-line px-3">
              <span className="label">Symbology</span>
            </div>
            <div className="space-y-1.5 p-3">
              {(['escalate', 'investigate', 'monitor'] as const).map((r) => (
                <div key={r} className="flex items-center gap-2.5 text-[11.5px] text-muted">
                  <span className="flex w-3 justify-center">
                    <TrackGlyph rec={r} size={r === 'monitor' ? 9 : 11} />
                  </span>
                  <span className="flex-1">{REC_META[r].label}</span>
                  <span className="num text-[10px] text-dim">{r === 'escalate' ? '2 SRC / ≥70' : r === 'investigate' ? '1 SRC / 40+' : '—'}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function CursorReadout() {
  const { current: map } = useMap()
  const [pos, setPos] = useState<{ lat: number; lon: number } | null>(null)
  const [zoom, setZoom] = useState(() => map?.getZoom() ?? KANSAS_VIEW.zoom)
  useEffect(() => {
    if (!map) return
    let raf = 0
    const move = (e: { lngLat: { lat: number; lng: number } }) => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setPos({ lat: e.lngLat.lat, lon: e.lngLat.lng }))
    }
    const out = () => setPos(null)
    const zoomed = () => setZoom(map.getZoom())
    map.on('mousemove', move)
    map.on('mouseout', out)
    map.on('zoom', zoomed)
    return () => {
      cancelAnimationFrame(raf)
      map.off('mousemove', move)
      map.off('mouseout', out)
      map.off('zoom', zoomed)
    }
  }, [map])
  return (
    <div className="hud num pointer-events-none absolute bottom-10 left-3 flex h-6 items-center gap-3 px-2 text-[10px] text-muted">
      <span className="text-dim">CURSOR</span>
      <span className="w-[170px] text-text">{pos ? latLon(pos.lat, pos.lon) : '—'}</span>
      <span className="text-dim">Z</span>
      <span className="text-text">{zoom.toFixed(1)}</span>
    </div>
  )
}
