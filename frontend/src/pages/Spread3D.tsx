import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowUp, Info, Pause, Play, RotateCcw } from 'lucide-react'
import type { GeoJSONSource } from 'maplibre-gl'
import { useEffect, useState } from 'react'
import Map, { Layer, Marker, Source, useMap } from 'react-map-gl/maplibre'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { ScoreBadge } from '../components/ScoreBadge'
import { compass } from '../lib/format'
import { IMAGERY_TERRAIN_STYLE } from '../lib/map'

const DURATION = 60
const PLAY_SECONDS_AT_1X = 15
const PARTICLES = 160

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function Spread3D() {
  const id = Number(useParams().id)
  const alert = useQuery({ queryKey: ['alert', id], queryFn: () => api.alert(id) })
  const [override, setOverride] = useState(false)
  const [wind, setWind] = useState<{ kmh: number; fromDeg: number } | null>(null)
  const debouncedWind = useDebounced(override ? wind : null, 250)
  const sim = useQuery({
    queryKey: ['simulate', id, debouncedWind],
    queryFn: () => api.simulate(id, debouncedWind ?? undefined),
    placeholderData: keepPreviousData,
  })
  const lines = useQuery({ queryKey: ['layer', 'power_lines'], queryFn: () => api.layer('power_lines') })
  const towns = useQuery({ queryKey: ['layer', 'towns'], queryFn: () => api.layer('towns') })
  const subs = useQuery({ queryKey: ['layer', 'substations'], queryFn: () => api.layer('substations') })

  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(1)

  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      setT((prev) => {
        const next = prev + (dt * DURATION * speed) / PLAY_SECONDS_AT_1X
        if (next >= DURATION) {
          setPlaying(false)
          return DURATION
        }
        return next
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed])

  const a = alert.data
  const s = sim.data
  const shownWind = wind ?? (s ? { kmh: s.observed_wind.kmh, fromDeg: s.observed_wind.from_deg } : null)
  const front = Math.max(5, Math.floor(t / 5) * 5)
  const activeWind = s?.wind_vector ?? { from_deg: 0, kmh: 0 }
  const downwind = (activeWind.from_deg + 180) % 360

  if (!a) {
    return <div className="flex h-full items-center justify-center text-muted">{alert.isError ? 'Alert not found.' : 'Loading…'}</div>
  }

  const impactedNow = new Set((s?.impacts ?? []).filter((i) => i.minutes <= t).map((i) => i.name))
  const area = s?.isochrones.features.filter((f) => f.properties.minutes <= Math.max(t, 5)).at(-1)?.properties.area_ha ?? 0

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel px-4">
        <Link to={`/alerts/${id}`} className="flex items-center gap-1 text-sm text-muted hover:text-text">
          <ArrowLeft size={16} /> Back to alert
        </Link>
        <ScoreBadge score={a.score} rec={a.recommendation} size={28} />
        <span className="font-semibold">{a.place_label}</span>
        <span className="ml-auto flex items-center gap-1.5 text-xs text-muted" title="Simplified grass-fire estimate for planning. Not an operational fire behavior prediction.">
          <Info size={14} /> Simplified grass-fire estimate — not an operational prediction
        </span>
      </header>

      <div className="flex min-h-0 flex-1">
        <div className="relative flex-1">
          <Map
            initialViewState={{
              longitude: a.lon,
              latitude: a.lat,
              zoom: 11.3,
              pitch: 62,
              bearing: ((a.weather.wind_dir_deg ?? 0) + 180) % 360,
            }}
            mapStyle={IMAGERY_TERRAIN_STYLE}
            maxPitch={80}
            style={{ width: '100%', height: '100%' }}
          >
            {s && (
              <Source id="iso" type="geojson" data={s.isochrones}>
                <Layer
                  id="iso-fill"
                  type="fill"
                  filter={['<=', ['get', 'minutes'], Math.max(t, 0.01)]}
                  paint={{
                    'fill-color': ['interpolate', ['linear'], ['get', 'minutes'], 5, '#fde68a', 30, '#f97316', 60, '#b91c1c'],
                    'fill-opacity': 0.22,
                  }}
                />
                <Layer
                  id="iso-line"
                  type="line"
                  filter={['<=', ['get', 'minutes'], Math.max(t, 0.01)]}
                  paint={{ 'line-color': '#fdba74', 'line-width': 1, 'line-opacity': 0.5 }}
                />
                <Layer
                  id="iso-front"
                  type="line"
                  filter={['==', ['get', 'minutes'], t >= 5 ? front : -1]}
                  paint={{ 'line-color': '#fef08a', 'line-width': 3, 'line-blur': 1 }}
                />
              </Source>
            )}
            {lines.data && (
              <Source id="lines" type="geojson" data={lines.data}>
                <Layer
                  id="lines"
                  type="line"
                  paint={{
                    'line-color': ['case', ['in', ['get', 'name'], ['literal', [...impactedNow]]], '#ef4444', '#fbbf24'],
                    'line-width': 3,
                  }}
                />
              </Source>
            )}
            <WindParticles lat={a.lat} lon={a.lon} fromDeg={activeWind.from_deg} kmh={activeWind.kmh} />
            {[...(towns.data?.features ?? []), ...(subs.data?.features ?? [])].map((f) => {
              const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates
              if (Math.abs(lat - a.lat) > 0.25 || Math.abs(lon - a.lon) > 0.3) return null
              const name = f.properties?.name as string
              const hit = impactedNow.has(name)
              return (
                <Marker key={name} longitude={lon} latitude={lat} anchor="bottom">
                  <div className={`rounded px-1.5 py-0.5 text-[11px] font-semibold shadow ${hit ? 'bg-escalate text-white' : 'bg-black/70 text-white'}`}>
                    ▲ {name}
                  </div>
                </Marker>
              )
            })}
            <Marker longitude={a.lon} latitude={a.lat} anchor="center" rotation={downwind} rotationAlignment="map" pitchAlignment="map">
              <div className="rounded-full bg-black/60 p-1.5">
                <ArrowUp size={22} className="text-sky-300" strokeWidth={3} />
              </div>
            </Marker>
          </Map>
        </div>

        <aside className="w-[280px] shrink-0 space-y-4 overflow-y-auto border-l border-line bg-panel p-4 text-sm">
          <section className="space-y-2">
            <h3 className="text-[11px] font-semibold tracking-widest text-muted">WIND</h3>
            {s && (
              <div>
                Observed {Math.round(s.observed_wind.kmh)} km/h from {s.observed_wind.from_deg}° ({compass(s.observed_wind.from_deg)})
              </div>
            )}
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Override
            </label>
            {shownWind && (
              <div className={`space-y-2 ${override ? '' : 'pointer-events-none opacity-40'}`}>
                <label className="block text-xs text-muted">
                  Speed <span className="tabular text-text">{Math.round(shownWind.kmh)} km/h</span>
                  <input
                    type="range"
                    min={0}
                    max={120}
                    value={shownWind.kmh}
                    onChange={(e) => setWind({ ...shownWind, kmh: Number(e.target.value) })}
                    className="w-full"
                  />
                </label>
                <label className="block text-xs text-muted">
                  From <span className="tabular text-text">{Math.round(shownWind.fromDeg)}° ({compass(shownWind.fromDeg)})</span>
                  <input
                    type="range"
                    min={0}
                    max={355}
                    step={5}
                    value={shownWind.fromDeg}
                    onChange={(e) => setWind({ ...shownWind, fromDeg: Number(e.target.value) })}
                    className="w-full"
                  />
                </label>
              </div>
            )}
            {sim.isFetching && <div className="text-xs text-muted">Recomputing…</div>}
          </section>

          <section className="space-y-2">
            <h3 className="text-[11px] font-semibold tracking-widest text-muted">IMPACTS (60 MIN)</h3>
            <ul className="space-y-1">
              {(s?.impacts ?? []).map((i) => (
                <li key={`${i.kind}-${i.name}`} className={`flex justify-between ${i.minutes <= t ? 'text-escalate' : ''}`}>
                  <span className="truncate pr-2">{i.name}</span>
                  <span className="tabular">{i.minutes} min</span>
                </li>
              ))}
              {s && s.impacts.length === 0 && <li className="text-muted">No towns, lines, or substations reached.</li>}
            </ul>
          </section>

          {s && (
            <section className="space-y-1 text-xs text-muted">
              <h3 className="text-[11px] font-semibold tracking-widest">ESTIMATE</h3>
              <div>
                Head spread <span className="tabular text-text">{s.head_ros_kmh} km/h</span>
              </div>
              <div>
                Area at {Math.round(Math.max(t, 5))} min <span className="tabular text-text">{area.toLocaleString()} ha</span>
              </div>
              <div>Terrain: {String(s.assumptions.terrain)}</div>
              <div>
                RH {s.assumptions.rh_pct}% · {s.assumptions.temp_c}°C · curing {s.assumptions.curing_pct}%
              </div>
            </section>
          )}
        </aside>
      </div>

      <footer className="flex h-14 shrink-0 items-center gap-4 border-t border-line bg-panel px-4">
        <button
          onClick={() => {
            if (t >= DURATION) setT(0)
            setPlaying((p) => !p)
          }}
          className="rounded-full bg-white/10 p-2 hover:bg-white/20"
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? <Pause size={16} /> : <Play size={16} />}
        </button>
        <span className="tabular w-14 text-sm">{Math.round(t)} min</span>
        <input
          type="range"
          min={0}
          max={DURATION}
          step={1}
          value={t}
          onChange={(e) => {
            setPlaying(false)
            setT(Number(e.target.value))
          }}
          className="flex-1"
          aria-label="Time"
        />
        <div className="flex gap-1">
          {[1, 4].map((x) => (
            <button
              key={x}
              onClick={() => setSpeed(x)}
              className={`rounded px-2 py-1 text-xs ${speed === x ? 'bg-white/15' : 'text-muted hover:bg-white/5'}`}
            >
              {x}×
            </button>
          ))}
        </div>
        <button
          onClick={() => {
            setOverride(false)
            setWind(null)
            setT(0)
            setPlaying(true)
          }}
          className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-white/5"
        >
          <RotateCcw size={13} /> Reset to observed
        </button>
      </footer>
    </div>
  )
}

/** Short wind streaks drifting downwind around the event, drawn into a GeoJSON source each frame. */
const EMPTY_FC: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const WIND_EXTENT_KM = 9

function WindParticles({ lat, lon, fromDeg, kmh }: { lat: number; lon: number; fromDeg: number; kmh: number }) {
  const { current: mapRef } = useMap()

  useEffect(() => {
    const map = mapRef?.getMap()
    if (!map) return
    const kx = 111.32 * Math.cos((lat * Math.PI) / 180)
    const ky = 110.57
    const extentKm = WIND_EXTENT_KM
    const particles = Array.from({ length: PARTICLES }, () => ({
      x: (Math.random() - 0.5) * 2 * extentKm,
      y: (Math.random() - 0.5) * 2 * extentKm,
      age: Math.random(),
    }))
    const rad = (((fromDeg + 180) % 360) * Math.PI) / 180
    const ux = Math.sin(rad)
    const uy = Math.cos(rad)
    const visualSpeed = 0.4 + kmh / 25 // km per second on screen, not physical
    let raf = 0
    let last = performance.now()
    const frame = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      const features = particles.map((p) => {
        p.x += ux * visualSpeed * dt
        p.y += uy * visualSpeed * dt
        p.age += dt / 3
        if (Math.abs(p.x) > extentKm || Math.abs(p.y) > extentKm || p.age > 1) {
          p.x = (Math.random() - 0.5) * 2 * extentKm
          p.y = (Math.random() - 0.5) * 2 * extentKm
          p.age = 0
        }
        const tail = 0.35 + kmh / 120
        return {
          type: 'Feature' as const,
          properties: { o: Math.sin(Math.PI * p.age) * 0.8 },
          geometry: {
            type: 'LineString' as const,
            coordinates: [
              [lon + (p.x - ux * tail) / kx, lat + (p.y - uy * tail) / ky],
              [lon + p.x / kx, lat + p.y / ky],
            ],
          },
        }
      })
      const src = map.getSource('wind') as GeoJSONSource | undefined
      src?.setData({ type: 'FeatureCollection', features })
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [mapRef, lat, lon, fromDeg, kmh])

  return (
    <Source id="wind" type="geojson" data={EMPTY_FC}>
      <Layer id="wind" type="line" paint={{ 'line-color': '#e0f2fe', 'line-width': 1.5, 'line-opacity': ['get', 'o'] }} />
    </Source>
  )
}
