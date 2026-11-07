import { Layer, Marker, Source } from 'react-map-gl/maplibre'
import type { AlertForecast } from '../api'

const STEP_MIN = 15
const KMH_PER_MPH = 1.609344

type Step = AlertForecast['steps'][number]

function stepAt(fire: AlertForecast, aheadMin: number): Step | undefined {
  return fire.steps.find((s) => s.ahead_min === aheadMin) ?? fire.steps.at(-1)
}

/** A small arrow pointing where the wind blows the fire (the forecast's wind at the fire, this hour). */
function WindArrow({ step, size = 14 }: { step: Step; size?: number }) {
  const to = (step.wind.from_deg + 180) % 360
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" style={{ transform: `rotate(${to}deg)` }} aria-hidden>
      <path d="M7 1 L11 8 L7.9 7 L7.9 13 L6.1 13 L6.1 7 L3 8 Z" fill="currentColor" />
    </svg>
  )
}

function windText(step: Step): string {
  return `${step.wind.compass} ${Math.round(step.wind.kmh / KMH_PER_MPH)} mph`
}

export function FireForecastLayer({ fire, aheadMin, lat, lon }: { fire: AlertForecast; aheadMin: number; lat: number; lon: number }) {
  const step = stepAt(fire, aheadMin)
  if (!step) return null
  return (
    <>
      <Source id="fc-worst" type="geojson" data={{ type: 'Feature', properties: {}, geometry: step.worst }}>
        <Layer id="fc-worst" type="line" paint={{ 'line-color': '#ff4b2b', 'line-width': 1.2, 'line-opacity': 0.8, 'line-dasharray': [3, 2] }} />
      </Source>
      <Source id="fc-likely" type="geojson" data={{ type: 'Feature', properties: {}, geometry: step.likely }}>
        <Layer id="fc-likely-fill" type="fill" paint={{ 'fill-color': '#ff7a1a', 'fill-opacity': 0.35 }} />
        <Layer id="fc-likely-line" type="line" paint={{ 'line-color': '#ffb21a', 'line-width': 1.5 }} />
      </Source>
      <Marker longitude={lon} latitude={lat} anchor="bottom" offset={[0, -16]}>
        <div className="pointer-events-none flex items-center gap-1 bg-void/80 px-1 py-[1px] text-[10px] whitespace-nowrap text-[#ffd166]" title="Forecast wind at the fire">
          <WindArrow step={step} size={11} />
          {windText(step)}
        </div>
      </Marker>
    </>
  )
}

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', { timeZone: 'America/Chicago', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
}

export function ForecastSlider({ fire, aheadMin, setAheadMin, loading }: {
  fire?: AlertForecast
  aheadMin: number
  setAheadMin: (m: number) => void
  loading: boolean
}) {
  const step = fire ? stepAt(fire, aheadMin) : undefined
  return (
    <div className="hud absolute bottom-10 left-1/2 w-[min(520px,calc(100%-2rem))] -translate-x-1/2 px-4 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-semibold text-text">
          Fire forecast {aheadMin === 0 ? 'now' : `+${Math.floor(aheadMin / 60)}:${String(aheadMin % 60).padStart(2, '0')}`}
          {step && <span className="ml-2 font-normal text-muted">{clock(step.at)}</span>}
        </span>
        {step ? (
          <span className="flex items-center gap-1 text-[11px] text-[#ffd166]" title="Forecast wind at the fire">
            <WindArrow step={step} size={12} /> Wind {windText(step)}
          </span>
        ) : (
          <span className="text-[11px] text-dim">{loading ? 'Forecasting the fire…' : ''}</span>
        )}
      </div>
      <input
        type="range"
        min={0}
        max={fire?.steps.at(-1)?.ahead_min ?? 0}
        step={STEP_MIN}
        value={aheadMin}
        disabled={!fire}
        onChange={(e) => setAheadMin(Number(e.target.value))}
        className="mt-1 w-full"
        aria-label="Forecast time"
      />
      <div className="mt-0.5 text-[10.5px] text-dim">Likely (filled) · worst case (dashed) · {fire ? `${fire.members} forecast runs` : '…'}</div>
    </div>
  )
}
