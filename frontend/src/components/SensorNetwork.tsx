import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { Layer, Marker, Source, useMap } from 'react-map-gl/maplibre'
import { api, type SensorDetail, type SensorNetwork, type SensorNode, type SensorStatus } from '../api'

export const SENSOR_STATUS: Record<SensorStatus, { label: string; color: string; rank: number }> = {
  ok: { label: 'OK', color: '#3ddc97', rank: 0 },
  watch: { label: 'Watch', color: '#ffd84d', rank: 1 },
  service: { label: 'Service', color: '#ffb21a', rank: 2 },
  replace: { label: 'Replace', color: '#ff4b2b', rank: 3 },
  stale: { label: 'Stale sensors', color: '#ff4b2b', rank: 4 },
  offline: { label: 'Radio down', color: '#ff4b2b', rank: 5 },
}
const PLOT_ZOOM = 12.5 // below this, each plot's nodes collapse into one marker

const worst = (ns: SensorNode[]) => ns.reduce<SensorStatus>((w, n) => (SENSOR_STATUS[n.status].rank > SENSOR_STATUS[w].rank ? n.status : w), 'ok')

function ago(at: string | null): string {
  if (!at) return 'never'
  const min = Math.round((Date.now() - Date.parse(at)) / 60_000)
  return min < 1 ? 'just now' : min < 120 ? `${min} min ago` : `${(min / 60).toFixed(1)} h ago`
}

function kindLabel(n: SensorNode): string {
  if (n.kind === 'sensor') return n.tier === 'rich' ? 'FireSense rich node · gas + particulate' : 'FireSense bare node · gas + weather'
  return n.kind === 'relay' ? 'FireMesh relay' : 'FireMesh station bridge'
}

/** Shape says what the node is, fill says its health: circle bare, diamond rich, triangle relay, square bridge.
 *  Red is either problem: hollow red when the radio link is down, solid red when sensors are stale or a part needs replacing. */
export function NodeGlyph({ n, size = 9, selected = false }: { n: Pick<SensorNode, 'kind' | 'tier' | 'status'>; size?: number; selected?: boolean }) {
  const c = SENSOR_STATUS[n.status].color
  const hollow = n.status === 'offline'
  const ring = selected ? '0 0 0 2px #050607, 0 0 0 3px #ffffff' : '0 0 0 1px #050607'
  const style = { width: size, height: size, background: hollow ? '#050607' : c, border: hollow ? `1px solid ${c}` : undefined, boxShadow: ring }
  if (n.kind === 'relay')
    return <span className="block" style={{ ...style, boxShadow: undefined, clipPath: 'polygon(50% 0, 100% 100%, 0 100%)', width: size + 2, height: size + 2 }} />
  if (n.kind === 'bridge') return <span className="block" style={style} />
  if (n.tier === 'rich') return <span className="block rotate-45" style={{ ...style, width: size - 1, height: size - 1 }} />
  return <span className="block rounded-full" style={style} />
}

export function SensorLayer({ net, selectedId, onPick }: { net: SensorNetwork; selectedId: string | null; onPick: (id: string) => void }) {
  const { current: map } = useMap()
  const [zoom, setZoom] = useState(() => map?.getZoom() ?? 8)
  useEffect(() => {
    if (!map) return
    const z = () => setZoom(map.getZoom())
    map.on('zoomend', z)
    return () => {
      map.off('zoomend', z)
    }
  }, [map])
  const plots = useMemo(() => {
    const g = new globalThis.Map<number, SensorNode[]>()
    for (const n of net.nodes) if (n.kind === 'sensor' && n.site != null) g.set(n.site, [...(g.get(n.site) ?? []), n])
    return [...g.entries()]
  }, [net])
  const zoomedIn = zoom >= PLOT_ZOOM
  const infra = net.nodes.filter((n) => n.kind !== 'sensor')
  return (
    <>
      <Source id="sensor-links" type="geojson" data={net.links}>
        <Layer
          id="sensor-links"
          type="line"
          paint={{
            'line-color': '#5cc8ff',
            'line-width': ['match', ['get', 'kind'], 'backbone', 1.2, 0.8],
            'line-opacity': ['match', ['get', 'kind'], 'backbone', 0.45, 0.3],
            'line-dasharray': [3, 2],
          }}
        />
      </Source>
      {infra.map((n) => (
        <NodeMarker key={n.node_id} n={n} selected={n.node_id === selectedId} onPick={onPick} />
      ))}
      {zoomedIn
        ? plots.flatMap(([, ns]) => ns.map((n) => <NodeMarker key={n.node_id} n={n} selected={n.node_id === selectedId} onPick={onPick} />))
        : plots.map(([site, ns]) => <PlotMarker key={site} site={site} nodes={ns} />)}
    </>
  )
}

function NodeMarker({ n, selected, onPick }: { n: SensorNode; selected: boolean; onPick: (id: string) => void }) {
  return (
    <Marker longitude={n.lon} latitude={n.lat} anchor="center" style={{ zIndex: selected ? 6 : undefined }}>
      <button
        type="button"
        aria-label={`${n.label}: ${SENSOR_STATUS[n.status].label}`}
        title={`${n.label} · ${SENSOR_STATUS[n.status].label}`}
        onClick={(e) => {
          e.stopPropagation()
          onPick(n.node_id)
        }}
        className="flex h-5 w-5 cursor-pointer items-center justify-center"
      >
        <NodeGlyph n={n} selected={selected} />
      </button>
    </Marker>
  )
}

function PlotMarker({ site, nodes }: { site: number; nodes: SensorNode[] }) {
  const { current: map } = useMap()
  const status = worst(nodes)
  const issues = nodes.filter((n) => n.status !== 'ok').length
  const lon = nodes.reduce((s, n) => s + n.lon, 0) / nodes.length
  const lat = nodes.reduce((s, n) => s + n.lat, 0) / nodes.length
  const c = SENSOR_STATUS[status].color
  return (
    <Marker longitude={lon} latitude={lat} anchor="center">
      <button
        type="button"
        aria-label={`Sensor plot ${site}: ${nodes.length} nodes, ${issues} need attention. Zoom in.`}
        title={`Plot ${site} · ${nodes.length} nodes${issues ? ` · ${issues} need attention` : ''}`}
        onClick={(e) => {
          e.stopPropagation()
          map?.flyTo({ center: [lon, lat], zoom: 15.5, duration: 900 })
        }}
        className="num flex h-5 cursor-pointer items-center gap-1 border bg-void/90 px-1 text-[10px] text-text"
        style={{ borderColor: c }}
      >
        <span className="block h-1.5 w-1.5 rounded-full" style={{ background: c }} />
        P{site}
        {issues > 0 && <span style={{ color: c }}>{issues}!</span>}
      </button>
    </Marker>
  )
}

/** Health tally for the map corner; clicking jumps to the node in the worst shape. */
export function SensorHealthChip({ net, onPick }: { net: SensorNetwork; onPick: (id: string) => void }) {
  const bad = net.nodes.filter((n) => n.status !== 'ok').sort((a, b) => SENSOR_STATUS[b.status].rank - SENSOR_STATUS[a.status].rank)
  return (
    <button
      type="button"
      onClick={() => bad[0] && onPick(bad[0].node_id)}
      className="hud num flex h-7 items-center gap-2.5 px-2 text-[10.5px] text-muted hover:bg-raised"
      title={bad[0] ? `Open ${bad[0].label}` : undefined}
    >
      <span className="label">FireNode{net.simulated ? ' · sim' : ''}</span>
      {(['offline', 'stale', 'replace', 'service', 'watch', 'ok'] as const)
        .filter((s) => net.counts[s] > 0)
        .map((s) => (
          <span key={s} className="flex items-center gap-1">
            <span className="block h-1.5 w-1.5 rounded-full" style={{ background: SENSOR_STATUS[s].color }} />
            <span className="text-text">{net.counts[s]}</span> {SENSOR_STATUS[s].label.toLowerCase()}
          </span>
        ))}
    </button>
  )
}

function Trend({ label, unit, points, digits = 0 }: { label: string; unit: string; points: [string, number][]; digits?: number }) {
  const [hover, setHover] = useState<number | null>(null)
  if (points.length < 2) return null
  const w = 132
  const h = 28
  const t0 = Date.parse(points[0][0])
  const span = Math.max(Date.parse(points[points.length - 1][0]) - t0, 1)
  const vals = points.map((p) => p[1])
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const x = (at: string) => ((Date.parse(at) - t0) / span) * w
  const y = (v: number) => h - 2 - ((v - lo) / (hi - lo || 1)) * (h - 4)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ')
  const shown = hover ?? points.length - 1
  const [at, v] = points[shown]
  return (
    <div className="flex items-center justify-between gap-3 py-1">
      <div className="min-w-0">
        <div className="label !text-[9.5px]">{label}</div>
        <div className="num text-[12px] text-text">
          {v.toFixed(digits)} <span className="text-muted">{unit}</span>
        </div>
        <div className="num text-[9.5px] text-dim">{hover == null ? 'now' : new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div>
      </div>
      <svg
        width={w}
        height={h}
        className="shrink-0 cursor-crosshair overflow-visible"
        role="img"
        aria-label={`${label}, last 24 hours: ${lo.toFixed(digits)} to ${hi.toFixed(digits)} ${unit}`}
        onMouseMove={(e) => {
          const px = e.clientX - e.currentTarget.getBoundingClientRect().left
          const target = t0 + (px / w) * span
          let best = 0
          points.forEach((p, i) => {
            if (Math.abs(Date.parse(p[0]) - target) < Math.abs(Date.parse(points[best][0]) - target)) best = i
          })
          setHover(best)
        }}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={0} x2={w} y1={h - 1} y2={h - 1} stroke="#1d2127" />
        <path d={d} fill="none" stroke="#5cc8ff" strokeWidth={1.5} strokeLinejoin="round" />
        {hover != null && <line x1={x(at)} x2={x(at)} y1={0} y2={h} stroke="#565e68" />}
        <circle cx={x(at)} cy={y(v)} r={2.5} fill="#5cc8ff" stroke="#050607" strokeWidth={1} />
      </svg>
    </div>
  )
}

function Indicator({ label, good, text }: { label: string; good: boolean; text: string }) {
  return (
    <div className="bg-void px-3 py-1.5">
      <div className="label !text-[9.5px]">{label}</div>
      <div className="flex items-center gap-1.5 text-[11px] text-text">
        <span className="block h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: good ? SENSOR_STATUS.ok.color : SENSOR_STATUS.offline.color }} />
        {text}
      </div>
    </div>
  )
}

function Reading({ k, v }: { k: string; v: string | null }) {
  if (v == null) return null
  return (
    <div className="flex items-baseline justify-between gap-2 py-[2px]">
      <span className="label !text-[9.5px]">{k}</span>
      <span className="num text-[11.5px] text-text">{v}</span>
    </div>
  )
}

export function SensorPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ['sensor', id], queryFn: () => api.sensor(id), refetchInterval: 15_000 })
  const n: SensorDetail | undefined = q.data
  const s = n ? SENSOR_STATUS[n.status] : null
  const l = n?.latest ?? {}
  const f = (v: number | undefined, digits: number, unit: string) => (v == null ? null : `${v.toFixed(digits)} ${unit}`)
  return (
    <div className="hud absolute top-14 left-4 z-10 flex max-h-[calc(100%-7rem)] w-[320px] flex-col overflow-y-auto text-[11.5px]">
      <div className="flex items-start justify-between gap-2 border-b border-line px-3 py-2">
        <div className="min-w-0">
          <div className="font-medium break-words text-text">{n?.label ?? id}</div>
          {n && (
            <div className="num mt-0.5 text-[10px] text-muted">
              {kindLabel(n)} · {n.node_id}
              {n.simulated && <span className="ml-1.5 border border-sample/60 px-1 text-sample">SIMULATED</span>}
            </div>
          )}
        </div>
        <button type="button" aria-label="Close" onClick={onClose} className="text-muted hover:text-text">
          x
        </button>
      </div>
      {q.isError && <p className="px-3 py-2 text-escalate">Couldn't load this node: {(q.error as Error).message}</p>}
      {n && s && (
        <>
          <div className="flex items-center gap-2 border-b border-line px-3 py-2">
            <NodeGlyph n={n} size={10} />
            <span className="font-semibold" style={{ color: s.color }}>
              {s.label}
            </span>
            <span className="text-muted">
              {n.actions.length ? `${n.actions.length} thing${n.actions.length > 1 ? 's' : ''} to do` : 'Nothing to do'}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-px border-b border-line bg-line">
            <Indicator
              label="FireMesh link"
              good={n.radio === 'ok'}
              text={n.radio === 'ok' ? `OK · heard ${ago(n.last_heard)}` : 'Down, cause unknown'}
            />
            {n.kind === 'sensor' ? (
              <Indicator
                label="FireSense"
                good={n.sensors === 'ok'}
                text={n.sensors === 'ok' ? 'Fresh samples' : n.sensors === 'stale' ? 'Stale, may need replacement' : 'Unknown while radio is down'}
              />
            ) : (
              <Indicator label="FireSense" good text="None fitted" />
            )}
          </div>
          {n.actions.length > 0 && (
            <ul className="space-y-1 border-b border-line px-3 py-2">
              {n.actions.map((a) => (
                <li key={a} className="flex gap-1.5 text-text">
                  <span className="text-dim">→</span>
                  {a}
                </li>
              ))}
            </ul>
          )}
          <div className="border-b border-line px-3 py-2">
            <div className="label mb-1">Health checks</div>
            {n.checks.map((c) => (
              <div key={c.key} className="border-t border-line/60 py-1.5 first:border-t-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-text">{c.part}</span>
                  <span className="num shrink-0 text-[10px] font-semibold" style={{ color: SENSOR_STATUS[c.status].color }}>
                    {SENSOR_STATUS[c.status].label.toUpperCase()}
                  </span>
                </div>
                <div className="num text-[10.5px] text-muted">{c.value}</div>
                {c.status !== 'ok' && <div className="text-[10.5px] text-muted">{c.detail}</div>}
              </div>
            ))}
          </div>
          {n.status !== 'offline' && (
            <div className="border-b border-line px-3 py-2">
              <div className="label mb-1">Last 24 hours</div>
              <Trend label="Battery" unit="V" points={n.series.pack_v} digits={2} />
              <Trend label="Solar" unit="W" points={n.series.solar_w} digits={1} />
              {n.tier === 'rich' && <Trend label="PM2.5" unit="µg/m³" points={n.series.pm25} />}
              {n.kind === 'sensor' && <Trend label="Gas resistance" unit="kΩ" points={n.series.gas_kohm} />}
            </div>
          )}
          {n.kind === 'sensor' && (
            <div className="border-b border-line px-3 py-2">
              <div className="label mb-1">Latest readings</div>
              <Reading k="Temperature" v={f(l.temp_c, 1, '°C')} />
              <Reading k="Humidity" v={f(l.rh_pct, 0, '%')} />
              <Reading k="Pressure" v={f(l.pressure_hpa, 0, 'hPa')} />
              <Reading k="Gas resistance" v={f(l.gas_kohm, 0, 'kΩ')} />
              <Reading k="PM2.5 / PM10" v={l.pm25 == null ? null : `${l.pm25} / ${l.pm10 ?? '—'} µg/m³`} />
            </div>
          )}
          <div className="px-3 py-2 text-[10.5px] text-muted">
            <div>Heard {ago(n.last_heard)}{n.via_label ? ` · reports via ${n.via_label}` : ''}</div>
            <div>Installed {new Date(n.installed_at).toLocaleDateString()}</div>
          </div>
        </>
      )}
    </div>
  )
}
