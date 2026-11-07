import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Layer, Popup, Source, useMap, type MapLayerMouseEvent } from 'react-map-gl/maplibre'
import { api, type FeedResponse } from '../api'

export type FeedKey = 'nws_alerts' | 'lsr' | 'wfigs_incidents' | 'wfigs_perimeters' | 'metar' | 'spc' | 'hms' | 'landsat_nrt'

interface FeedDef {
  key: FeedKey
  label: string
  /** Refetch interval in seconds, matching the backend poll interval. */
  every: number
  color: string
  kind: 'polygon' | 'point'
  list: string
}

export const FEEDS: FeedDef[] = [
  { key: 'nws_alerts', label: 'NWS alerts', every: 60, color: '#ff8a3d', kind: 'polygon', list: 'alerts' },
  { key: 'lsr', label: 'Storm reports', every: 300, color: '#5cc8ff', kind: 'point', list: 'reports' },
  { key: 'wfigs_incidents', label: 'Fire incidents', every: 300, color: '#ff5c5c', kind: 'point', list: 'items' },
  { key: 'wfigs_perimeters', label: 'Fire perimeters', every: 900, color: '#ff5c5c', kind: 'polygon', list: 'items' },
  { key: 'metar', label: 'Weather stations (METAR)', every: 300, color: '#3ddc97', kind: 'point', list: 'stations' },
  { key: 'spc', label: 'SPC fire outlook', every: 1800, color: '#ffd23d', kind: 'polygon', list: 'areas' },
  { key: 'hms', label: 'HMS fire points', every: 1800, color: '#ff9f1a', kind: 'point', list: 'points' },
  { key: 'landsat_nrt', label: 'Landsat', every: 300, color: '#c58bff', kind: 'point', list: 'points' },
]

export const FEED_SWATCH: Record<FeedKey, string> = Object.fromEntries(
  FEEDS.map((f) => [f.key, f.kind === 'polygon' ? 'h-2 w-4 border' : 'h-2 w-2 rounded-full']),
) as Record<FeedKey, string>

type Item = Record<string, unknown>

function toGeo(def: FeedDef, items: Item[]): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = []
  for (const it of items) {
    const { geometry, ...props } = it as Item & { geometry?: GeoJSON.Geometry | null }
    let g: GeoJSON.Geometry | null = null
    if (def.kind === 'polygon') g = geometry ?? null
    else if (geometry) g = geometry
    else if (typeof it.lon === 'number' && typeof it.lat === 'number') g = { type: 'Point', coordinates: [it.lon, it.lat] }
    if (g) features.push({ type: 'Feature', geometry: g, properties: { ...props, _flag: it.fire || it.downed_line ? 1 : 0 } })
  }
  return { type: 'FeatureCollection', features }
}

export interface FeedState {
  def: FeedDef
  on: boolean
  loading: boolean
  error: boolean
  res: FeedResponse | undefined
  count: number
  geo: GeoJSON.FeatureCollection
  /** Features with no geometry (NWS), listed in the panel instead of drawn. */
  undrawn: Item[]
}

export function useLiveFeeds(on: Record<FeedKey, boolean>, keyConfigured: boolean): FeedState[] {
  const q = FEEDS.map((def) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useQuery({
      queryKey: ['feed', def.key],
      queryFn: () => api.feed(def.key),
      enabled: on[def.key] && (def.key !== 'landsat_nrt' || keyConfigured),
      refetchInterval: def.every * 1000,
      retry: false,
    }),
  )
  return FEEDS.map((def, i) => {
    const res = q[i].data
    const items: Item[] = res?.data?.[def.list] ?? []
    const geo = toGeo(def, items)
    return {
      def,
      on: on[def.key],
      loading: q[i].isLoading,
      error: q[i].isError,
      res,
      count: items.length,
      geo,
      undrawn: def.kind === 'polygon' ? items.filter((it) => !it.geometry) : [],
    }
  })
}

function age(iso: string | null): string {
  if (!iso) return ''
  const m = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60000))
  return m < 1 ? 'just now' : m < 120 ? `${m} min ago` : `${Math.round(m / 60)} h ago`
}

export function feedStatus(f: FeedState, keyConfigured: boolean): string {
  if (f.def.key === 'landsat_nrt' && !keyConfigured) return 'needs FIRMS key'
  if (!f.on) return ''
  if (f.loading) return 'loading'
  if (f.error) return 'unavailable'
  if (f.res?.fixture) return `${f.count} · sample data`
  if (f.count === 0) return '0 active'
  return `${f.count}, ${age(f.res?.fetched_at ?? null)}`
}

export function LiveToggles({ feeds, on, setOn, keyConfigured }: {
  feeds: FeedState[]
  on: Record<FeedKey, boolean>
  setOn: (k: FeedKey, v: boolean) => void
  keyConfigured: boolean
}) {
  return (
    <div className="space-y-2 border-t border-line p-3" data-testid="live-group">
      <div className="label">Live data</div>
      {feeds.map((f) => {
        const disabled = f.def.key === 'landsat_nrt' && !keyConfigured
        const status = feedStatus(f, keyConfigured)
        return (
          <div key={f.def.key}>
            <label className={`flex items-center gap-2.5 text-[11.5px] ${disabled ? 'cursor-not-allowed text-dim' : 'cursor-pointer text-muted hover:text-text'}`}>
              <input type="checkbox" disabled={disabled} checked={on[f.def.key] && !disabled} onChange={(e) => setOn(f.def.key, e.target.checked)} data-feed={f.def.key} />
              <span className="flex-1">{f.def.label}</span>
              <span className={FEED_SWATCH[f.def.key]} style={{ background: f.def.kind === 'point' ? f.def.color : 'transparent', borderColor: f.def.color }} />
            </label>
            {status && (
              <div className="num pl-6 text-[10px] text-dim" data-status={f.def.key}>
                {status}
              </div>
            )}
            {f.on && f.undrawn.length > 0 && (
              <ul className="num mt-1 space-y-0.5 pl-6 text-[10px] text-muted" data-undrawn={f.def.key}>
                <li className="text-dim">{f.undrawn.length} without map shape:</li>
                {f.undrawn.map((a, i) => (
                  <li key={i}>{String(a.headline ?? a.event ?? 'Alert')}</li>
                ))}
              </ul>
            )}
          </div>
        )
      })}
    </div>
  )
}

const POPUP_FIELDS: Record<FeedKey, string[]> = {
  nws_alerts: ['event', 'headline', 'area'],
  lsr: ['type', 'remark', 'county', 'time'],
  wfigs_incidents: ['name', 'type', 'acres', 'county'],
  wfigs_perimeters: ['name', 'acres'],
  metar: ['id', 'rh_pct', 'pressure_hpa', 'temp_c', 'gust_kmh'],
  spc: ['label', 'outlook'],
  hms: ['satellite', 'frp', 'time'],
  landsat_nrt: ['acq_date', 'frp'],
}

export function LiveLayers({ feeds }: { feeds: FeedState[] }) {
  const { current: map } = useMap()
  const [pop, setPop] = useState<{ lon: number; lat: number; feed: FeedKey; props: Record<string, unknown> } | null>(null)
  const active = feeds.filter((f) => f.on && f.res)
  const ids = useMemo(() => active.flatMap((f) => [`live-${f.def.key}-fill`, `live-${f.def.key}-pt`]), [active])
  useEffect(() => {
    if (!map) return
    const click = (e: MapLayerMouseEvent) => {
      const layers = ids.filter((id) => map.getLayer(id))
      const hit = layers.length ? map.queryRenderedFeatures(e.point, { layers }) : []
      if (!hit.length) return setPop(null)
      const feed = hit[0].layer.id.split('-')[1] as FeedKey
      const key = FEEDS.find((f) => hit[0].layer.id.startsWith(`live-${f.key}-`))?.key ?? feed
      setPop({ lon: e.lngLat.lng, lat: e.lngLat.lat, feed: key, props: hit[0].properties ?? {} })
    }
    map.on('click', click)
    return () => void map.off('click', click)
  }, [map, ids])
  useEffect(() => {
    if (pop && !feeds.find((f) => f.def.key === pop.feed)?.on) setPop(null)
  }, [feeds, pop])
  return (
    <>
      {active.map((f) => {
        const k = f.def.key
        const c = f.def.color
        return (
          <Source key={k} id={`live-${k}`} type="geojson" data={f.geo}>
            {f.def.kind === 'polygon' ? (
              <>
                <Layer id={`live-${k}-fill`} type="fill" filter={['==', ['geometry-type'], 'Polygon']} paint={{ 'fill-color': c, 'fill-opacity': 0.18 }} />
                <Layer id={`live-${k}-line`} type="line" paint={{ 'line-color': c, 'line-width': 1.5, 'line-opacity': 0.9 }} />
              </>
            ) : (
              <Layer
                id={`live-${k}-pt`}
                type="circle"
                paint={{
                  'circle-radius': k === 'lsr' ? ['case', ['==', ['get', '_flag'], 1], 9, 4] : 6,
                  'circle-color': k === 'lsr' ? ['case', ['==', ['get', '_flag'], 1], '#ff3d3d', c] : c,
                  'circle-opacity': 0.9,
                  'circle-stroke-color': k === 'lsr' ? ['case', ['==', ['get', '_flag'], 1], '#ffffff', '#0b0d10'] : '#0b0d10',
                  'circle-stroke-width': k === 'lsr' ? ['case', ['==', ['get', '_flag'], 1], 2, 1] : 1,
                }}
              />
            )}
          </Source>
        )
      })}
      {pop && (
        <Popup longitude={pop.lon} latitude={pop.lat} closeButton={false} onClose={() => setPop(null)} maxWidth="240px">
          <div className="num space-y-0.5 text-[10.5px] text-void">
            <div className="font-semibold">{FEEDS.find((f) => f.key === pop.feed)?.label}</div>
            {POPUP_FIELDS[pop.feed]
              .filter((k) => pop.props[k] != null && pop.props[k] !== '')
              .map((k) => (
                <div key={k}>
                  {k}: {String(pop.props[k])}
                </div>
              ))}
          </div>
        </Popup>
      )}
    </>
  )
}
