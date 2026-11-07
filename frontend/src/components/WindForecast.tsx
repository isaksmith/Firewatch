import { useMemo } from 'react'
import { Layer, Source } from 'react-map-gl/maplibre'
import type { AlertForecast, WindField } from '../api'

/** Arrow colour by wind speed (km/h); the legend shows mph. */
const SPEED_STOPS: [number, string][] = [
  [0, '#5cc8ff'],
  [24, '#3ddc97'],
  [40, '#ffd166'],
  [56, '#ff8a3d'],
  [72, '#ff4b2b'],
]
const KMH_PER_MPH = 1.609344
const STEP_MIN = 15
const AHEAD_MAX_MIN = 360

function spacingKm(field: WindField): number {
  const lats = [...new Set(field.cells.map((c) => c.lat))].sort((a, b) => a - b)
  return lats.length > 1 ? (lats[1] - lats[0]) * 110.57 : 30
}

/** One arrow per grid cell, pointing where the wind blows to, longer and hotter when stronger. */
function arrows(field: WindField, hour: number): GeoJSON.FeatureCollection<GeoJSON.LineString> {
  const spacing = spacingKm(field)
  const features: GeoJSON.Feature<GeoJSON.LineString>[] = []
  for (const c of field.cells) {
    const kmh = c.wind_kmh[hour]
    const from = c.from_deg[hour]
    if (kmh == null || from == null) continue
    const to = ((from + 180) * Math.PI) / 180
    const len = spacing * (0.25 + 0.55 * Math.min(1, kmh / 70))
    const kx = 111.32 * Math.cos((c.lat * Math.PI) / 180)
    const ky = 110.57
    const pt = (dist: number, ang: number): [number, number] => [c.lon + (dist * Math.sin(ang)) / kx, c.lat + (dist * Math.cos(ang)) / ky]
    const tail = pt(-len / 2, to)
    const tip = pt(len / 2, to)
    const head = len * 0.32
    const left: [number, number] = [tip[0] + (head * Math.sin(to + Math.PI * 0.82)) / kx, tip[1] + (head * Math.cos(to + Math.PI * 0.82)) / ky]
    const right: [number, number] = [tip[0] + (head * Math.sin(to - Math.PI * 0.82)) / kx, tip[1] + (head * Math.cos(to - Math.PI * 0.82)) / ky]
    const props = { kmh, gust: c.gust_kmh[hour] }
    features.push({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: [tail, tip] } })
    features.push({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: [left, tip, right] } })
  }
  return { type: 'FeatureCollection', features }
}

/** Index of the wind hour shown for a slider position (the field starts at the top of the current hour). */
function windHour(field: WindField, now: string, aheadMin: number): number {
  const offset = (Date.parse(now) - Date.parse(field.start)) / 60_000 + aheadMin
  return Math.max(0, Math.min(field.hours - 1, Math.round(offset / 60)))
}

export function WindLayers({ wind, fire, now, aheadMin }: { wind?: WindField; fire?: AlertForecast; now: string; aheadMin: number }) {
  const hour = wind ? windHour(wind, now, aheadMin) : 0
  const arrowData = useMemo(() => (wind ? arrows(wind, hour) : null), [wind, hour])
  const step = fire?.steps.find((s) => s.ahead_min === aheadMin) ?? fire?.steps.at(-1)
  const color = ['interpolate', ['linear'], ['get', 'kmh'], ...SPEED_STOPS.flat()] as never
  return (
    <>
      {step && (
        <>
          <Source id="fc-worst" type="geojson" data={{ type: 'Feature', properties: {}, geometry: step.worst }}>
            <Layer id="fc-worst" type="line" paint={{ 'line-color': '#ff4b2b', 'line-width': 1.2, 'line-opacity': 0.8, 'line-dasharray': [3, 2] }} />
          </Source>
          <Source id="fc-likely" type="geojson" data={{ type: 'Feature', properties: {}, geometry: step.likely }}>
            <Layer id="fc-likely-fill" type="fill" paint={{ 'fill-color': '#ff7a1a', 'fill-opacity': 0.35 }} />
            <Layer id="fc-likely-line" type="line" paint={{ 'line-color': '#ffb21a', 'line-width': 1.5 }} />
          </Source>
        </>
      )}
      {arrowData && (
        <Source id="wind-arrows" type="geojson" data={arrowData}>
          <Layer id="wind-arrows-halo" type="line" paint={{ 'line-color': '#000', 'line-width': 3.5, 'line-opacity': 0.5 }} layout={{ 'line-cap': 'round', 'line-join': 'round' }} />
          <Layer id="wind-arrows" type="line" paint={{ 'line-color': color, 'line-width': 1.8 }} layout={{ 'line-cap': 'round', 'line-join': 'round' }} />
        </Source>
      )}
    </>
  )
}

const KIND_LABEL: Record<WindField['kind'], string> = {
  forecast: 'forecast',
  archive: 'what the wind actually did (archive)',
  simulated: 'scenario weather (simulated)',
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

export function ForecastSlider({ wind, fire, now, aheadMin, setAheadMin, loadingFire }: {
  wind?: WindField
  fire?: AlertForecast
  now: string
  aheadMin: number
  setAheadMin: (m: number) => void
  loadingFire: boolean
}) {
  const at = new Date(Date.parse(now) + aheadMin * 60_000).toISOString()
  const hour = wind ? windHour(wind, now, aheadMin) : null
  const fireMax = fire?.steps.at(-1)?.ahead_min ?? AHEAD_MAX_MIN
  return (
    <div className="hud absolute bottom-10 left-1/2 w-[min(560px,calc(100%-2rem))] -translate-x-1/2 px-4 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-semibold text-text">
          {aheadMin === 0 ? 'Now' : `+${Math.floor(aheadMin / 60)}:${String(aheadMin % 60).padStart(2, '0')}`}
          <span className="ml-2 font-normal text-muted">{clock(at)}</span>
        </span>
        <span className="truncate text-[11px] text-dim">
          {fire ? 'Fire: likely (filled) · worst case (dashed)' : loadingFire ? 'Forecasting the fire…' : 'Select an alert to see its fire forecast'}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={Math.min(AHEAD_MAX_MIN, fireMax)}
        step={STEP_MIN}
        value={aheadMin}
        onChange={(e) => setAheadMin(Number(e.target.value))}
        className="mt-1 w-full"
        aria-label="Forecast time"
      />
      <div className="mt-1 flex items-center justify-between gap-3 text-[10.5px] text-muted">
        <span className="flex items-center gap-2">
          <span>Wind</span>
          {SPEED_STOPS.map(([kmh, c]) => (
            <span key={kmh} className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-3" style={{ background: c }} />
              {Math.round(kmh / KMH_PER_MPH)}
            </span>
          ))}
          <span>mph</span>
        </span>
        {wind && (
          <span className="truncate text-dim" title={wind.source}>
            {KIND_LABEL[wind.kind]}
            {hour != null && hour === wind.hours - 1 && aheadMin > 0 ? ' · last hour available' : ''}
          </span>
        )}
      </div>
    </div>
  )
}
