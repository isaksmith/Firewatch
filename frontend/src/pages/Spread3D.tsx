import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Attribution } from '../components/Attribution'
import { ArrowUp, ChevronLeft, Pause, Play, RotateCcw } from 'lucide-react'
import type { GeoJSONSource } from 'maplibre-gl'
import { useEffect, useRef, useState } from 'react'
import Map, { Layer, Marker, Source, useMap } from 'react-map-gl/maplibre'
import { Link, useParams } from 'react-router-dom'
import { api, type SimulationResult } from '../api'
import { KV, RecTag, ScoreReadout } from '../components/ui'
import { compass, pad3, trackId } from '../lib/format'
import { setLowData, useLowData } from '../lib/lowData'
import { BLANK_STYLE, IMAGERY_TERRAIN_STYLE } from '../lib/map'

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
  const { on: lowData } = useLowData()
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
  const activeWind = (s?.overridden ? s.wind_vector : s?.observed_wind) ?? { from_deg: 0, kmh: 0 }
  const downwind = (activeWind.from_deg + 180) % 360

  if (!a) {
    return <div className="label flex h-full items-center justify-center">{alert.isError ? 'Alert not found' : 'Loading…'}</div>
  }

  const impactedNow = new Set((s?.impacts ?? []).filter((i) => i.minutes <= t).map((i) => i.id))
  const area = s?.isochrones.features.filter((f) => f.properties.minutes <= Math.max(t, 5)).at(-1)?.properties.area_ha ?? 0
  const togglePlay = () => {
    if (t >= DURATION) setT(0)
    setPlaying((p) => !p)
  }

  return (
    <div className="flex h-full flex-col bg-void">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-line bg-void px-3 sm:gap-4">
        <Link to={`/alerts/${id}`} className="btn !h-6 !px-2">
          <ChevronLeft size={12} /> Back to map
        </Link>
        <span className="num border border-investigate/60 px-1.5 py-[1px] text-[10px] font-medium tracking-[0.14em] text-investigate">3D VIEW</span>
        <span className="label hidden !text-muted sm:inline">
          FireCast spread preview · <span className="text-text">{trackId(id)}</span>
        </span>
        <span className="hidden h-4 w-px bg-line-2 sm:block" />
        <ScoreReadout score={a.score} rec={a.recommendation} size="sm" />
        <span className="hidden text-[13px] font-medium sm:inline">{a.place_label}</span>
        <RecTag rec={a.recommendation} />
        <span
          className="num ml-auto min-w-0 border border-investigate/40 px-1.5 py-[1px] text-[10px] tracking-[0.12em] text-investigate"
          title="Simplified grass-fire estimate for planning. Not an operational fire behavior prediction."
        >
          ESTIMATE · NOT AN OPERATIONAL PREDICTION
        </span>
        <Attribution placement="header" />
      </header>

      <div className="relative min-h-0 flex-1">
        <Map
          initialViewState={{
            longitude: a.lon,
            latitude: a.lat,
            zoom: 11.3,
            pitch: 62,
            bearing: ((a.weather.wind_dir_deg ?? 0) + 180) % 360,
          }}
          mapStyle={lowData ? BLANK_STYLE : IMAGERY_TERRAIN_STYLE}
          maxPitch={80}
          style={{ width: '100%', height: '100%' }}
          attributionControl={false}
        >
          {s && (
            <Source id="iso" type="geojson" data={s.isochrones}>
              <Layer
                id="iso-fill"
                type="fill"
                filter={['<=', ['get', 'minutes'], Math.max(t, 0.01)]}
                paint={{
                  'fill-color': ['interpolate', ['linear'], ['get', 'minutes'], 5, '#ffd166', 30, '#ff7a2b', 60, '#c81e1e'],
                  'fill-opacity': 0.2,
                }}
              />
              <Layer
                id="iso-line"
                type="line"
                filter={['<=', ['get', 'minutes'], Math.max(t, 0.01)]}
                paint={{ 'line-color': '#ffb48a', 'line-width': 0.75, 'line-opacity': 0.45 }}
              />
              <Layer
                id="iso-front"
                type="line"
                filter={['==', ['get', 'minutes'], t >= 5 ? front : -1]}
                paint={{ 'line-color': '#fff1c2', 'line-width': 2.5, 'line-blur': 0.5 }}
              />
            </Source>
          )}
          {lines.data && (
            <Source id="lines" type="geojson" data={lines.data}>
              <Layer
                id="lines"
                type="line"
                paint={{
                  'line-color': ['case', ['in', ['get', 'id'], ['literal', [...impactedNow]]], '#ff4b2b', '#e6e8eb'],
                  'line-width': ['case', ['in', ['get', 'id'], ['literal', [...impactedNow]]], 3, 1.5],
                }}
              />
            </Source>
          )}
          <WindParticles lat={a.lat} lon={a.lon} fromDeg={activeWind.from_deg} kmh={activeWind.kmh} />
          {[...(towns.data?.features ?? []), ...(subs.data?.features ?? [])].map((f) => {
            const [lon, lat] = (f.geometry as GeoJSON.Point).coordinates
            if (Math.abs(lat - a.lat) > 0.25 || Math.abs(lon - a.lon) > 0.3) return null
            const name = f.properties?.name as string
            const fid = (f.properties?.id as string | undefined) ?? name
            const hit = impactedNow.has(fid)
            return (
              <Marker key={fid} longitude={lon} latitude={lat} anchor="bottom">
                <div className="flex flex-col items-center">
                  <div
                    className={`num px-1.5 py-[2px] text-[10px] tracking-[0.1em] uppercase ${hit ? 'bg-escalate text-white' : 'hud text-text'}`}
                  >
                    {name}
                  </div>
                  <span className={`h-3 w-px ${hit ? 'bg-escalate' : 'bg-text/60'}`} />
                </div>
              </Marker>
            )
          })}
          <Marker longitude={a.lon} latitude={a.lat} anchor="center" rotation={downwind} rotationAlignment="map" pitchAlignment="map">
            <div className="flex h-7 w-7 items-center justify-center border border-text bg-void/70">
              <ArrowUp size={16} className="text-text" strokeWidth={2.5} />
            </div>
          </Marker>
        </Map>

        <div className="pointer-events-none absolute inset-3 brackets" style={{ ['--b' as string]: '#e6e8eb66' }} />

        {lowData && (
          <div role="status" className="hud absolute bottom-28 left-1/2 flex -translate-x-1/2 items-center gap-3 px-4 py-2 text-[12.5px]">
            <span className="text-degraded">Low data mode is on, so the 3D view skips aerial imagery and terrain.</span>
            <button onClick={() => setLowData(false)} className="btn !h-7">
              Turn off
            </button>
          </div>
        )}

        <div className="hud pointer-events-none absolute top-6 left-6 px-4 py-3">
          <div className="label">Elapsed</div>
          <div className="num text-[32px] leading-none font-semibold text-text">
            T+{String(Math.round(t)).padStart(2, '0')}
            <span className="ml-1 text-[12px] font-normal text-dim">MIN</span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-5">
            <KV k="Area" v={`${Math.round(area).toLocaleString()} HA`} />
            <KV k="Head" v={`${s?.head_ros_kmh ?? '–'} KM/H`} />
            <KV k="Wind" v={`${pad3(activeWind.from_deg)}° ${compass(activeWind.from_deg)}`} />
            <KV k="Speed" v={`${Math.round(activeWind.kmh)} KM/H`} accent={s?.overridden ? '#5cc8ff' : undefined} />
          </div>
        </div>

        <SidePanel
          s={s}
          t={t}
          override={override}
          setOverride={setOverride}
          shownWind={shownWind}
          setWind={setWind}
          fetching={sim.isFetching}
        />

        <div className="hud absolute right-6 bottom-6 left-6 flex h-14 items-center gap-4 px-4">
          <button onClick={togglePlay} className="btn btn-primary !h-8 !w-8 !p-0" aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? <Pause size={14} /> : <Play size={14} />}
          </button>
          <Timeline
            t={t}
            impacts={s?.impacts ?? []}
            onScrub={(v) => {
              setPlaying(false)
              setT(v)
            }}
          />
          <div className="flex">
            {[1, 4].map((x) => (
              <button key={x} onClick={() => setSpeed(x)} className={`btn !h-7 !w-9 !px-0 ${speed === x ? '!border-text' : '!text-dim'} ${x === 4 ? '-ml-px' : ''}`}>
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
            className="btn !h-7"
          >
            <RotateCcw size={11} /> Reset
          </button>
        </div>
      </div>
    </div>
  )
}

function SidePanel({ s, t, override, setOverride, shownWind, setWind, fetching }: {
  s: SimulationResult | undefined
  t: number
  override: boolean
  setOverride: (b: boolean) => void
  shownWind: { kmh: number; fromDeg: number } | null
  setWind: (w: { kmh: number; fromDeg: number }) => void
  fetching: boolean
}) {
  return (
    <div className="hud absolute top-6 right-6 w-[270px]">
      <div className="flex h-8 items-center justify-between border-b border-line px-4">
        <span className="label">Wind</span>
        {fetching && <span className="num blink text-[9px] tracking-[0.12em] text-sample">COMPUTING</span>}
      </div>
      <div className="space-y-3 px-4 py-3">
        {s && (
          <KV k="Observed" v={`${pad3(s.observed_wind.from_deg)}° ${compass(s.observed_wind.from_deg)} · ${Math.round(s.observed_wind.kmh)} KM/H`} />
        )}
        <label className="flex cursor-pointer items-center gap-2.5 text-[11.5px] text-muted">
          <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Override wind
        </label>
        {shownWind && (
          <div className={`space-y-2 ${override ? '' : 'pointer-events-none opacity-35'}`}>
            <label className="block">
              <div className="flex justify-between">
                <span className="label">Speed</span>
                <span className="num text-[11px] text-text">{Math.round(shownWind.kmh)} KM/H</span>
              </div>
              <input
                type="range"
                min={0}
                max={120}
                value={shownWind.kmh}
                onChange={(e) => setWind({ ...shownWind, kmh: Number(e.target.value) })}
                className="w-full"
              />
            </label>
            <label className="block">
              <div className="flex justify-between">
                <span className="label">From</span>
                <span className="num text-[11px] text-text">
                  {pad3(shownWind.fromDeg)}° {compass(shownWind.fromDeg)}
                </span>
              </div>
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
      </div>

      <div className="flex h-8 items-center justify-between border-t border-b border-line px-4">
        <span className="label">Impacts · 60 min</span>
        <span className="num text-[10px] text-dim">SOONEST, WORST CASE</span>
      </div>
      <ul className="space-y-1.5 px-4 py-3">
        {(s?.impacts ?? []).map((i) => {
          const hit = i.minutes <= t
          return (
            <li key={i.id} className="flex items-center justify-between gap-3">
              <span className={`min-w-0 truncate text-[12px] ${hit ? 'text-escalate' : 'text-text'}`}>{i.name}</span>
              <span className={`num shrink-0 text-[11px] ${hit ? 'text-escalate' : 'text-muted'}`}>
                {hit ? 'REACHED' : `T+${String(i.minutes).padStart(2, '0')}`}
              </span>
            </li>
          )
        })}
        {s && s.impacts.length === 0 && <li className="text-[12px] text-dim">No towns, lines, or substations reached.</li>}
      </ul>

      {s && (
        <>
          <div className="flex h-8 items-center border-t border-b border-line px-4">
            <span className="label">Assumptions</span>
          </div>
          <div className="px-4 py-2.5">
            <KV k="RH" v={`${s.assumptions.rh_pct}%`} />
            <KV k="Temp" v={`${s.assumptions.temp_c}°C`} />
            <KV k="Curing" v={`${s.assumptions.curing_pct}%`} />
            <KV k="L:B" v={s.length_to_breadth} />
            <div className="num mt-1.5 text-[9.5px] text-dim">{String(s.assumptions.terrain).toUpperCase()}</div>
          </div>
        </>
      )}
    </div>
  )
}

function Timeline({ t, impacts, onScrub }: { t: number; impacts: { id: string; name: string; minutes: number }[]; onScrub: (v: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const fromEvent = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    onScrub(Math.round(Math.min(1, Math.max(0, (clientX - r.left) / r.width)) * DURATION))
  }
  const pct = (m: number) => `${(m / DURATION) * 100}%`
  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label="Elapsed minutes"
      aria-valuemin={0}
      aria-valuemax={DURATION}
      aria-valuenow={Math.round(t)}
      className="relative h-10 flex-1 cursor-pointer touch-none outline-none"
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture(e.pointerId)
        fromEvent(e.clientX)
      }}
      onPointerMove={(e) => {
        if (e.currentTarget.hasPointerCapture(e.pointerId)) fromEvent(e.clientX)
      }}
      onKeyDown={(e) => {
        if (e.key === 'ArrowRight') onScrub(Math.min(DURATION, Math.round(t) + 1))
        if (e.key === 'ArrowLeft') onScrub(Math.max(0, Math.round(t) - 1))
      }}
    >
      <div className="absolute top-1/2 right-0 left-0 h-px bg-line-2" />
      <div className="absolute top-1/2 left-0 h-[2px] -translate-y-[0.5px] bg-text" style={{ width: pct(t) }} />
      {Array.from({ length: DURATION / 5 + 1 }, (_, i) => i * 5).map((m) => (
        <div key={m} className="absolute top-1/2" style={{ left: pct(m) }}>
          <div className={`w-px -translate-x-1/2 ${m % 15 === 0 ? 'h-2.5 bg-muted' : 'h-1.5 bg-line-2'}`} />
          {m % 15 === 0 && <div className="num absolute top-3 -translate-x-1/2 text-[9px] text-dim">{m}</div>}
        </div>
      ))}
      {impacts.map((i) => (
        <div key={i.id} className="absolute top-0" style={{ left: pct(i.minutes) }} title={`${i.name} · T+${i.minutes} min`}>
          <div className={`h-2 w-2 -translate-x-1/2 rotate-45 ${i.minutes <= t ? 'bg-escalate' : 'border border-escalate bg-void'}`} />
        </div>
      ))}
      <div className="absolute top-1/2 h-4 w-[3px] -translate-x-1/2 -translate-y-1/2 bg-text" style={{ left: pct(t) }} />
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
          properties: { o: Math.sin(Math.PI * p.age) * 0.7 },
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
      <Layer id="wind" type="line" paint={{ 'line-color': '#e6e8eb', 'line-width': 1.25, 'line-opacity': ['get', 'o'] }} />
    </Source>
  )
}
