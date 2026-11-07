import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronRight, Radio } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import Map, { Layer, Marker, NavigationControl, ScaleControl, Source, type MapRef } from 'react-map-gl/maplibre'
import { api, type Climatology, type PlanParams, type PlanSite, type RegionPlan, type RiskFactor, type TierPower } from '../api'
import { TopBar } from '../components/TopBar'
import { KV, SectionHeader } from '../components/ui'
import { useLowData } from '../lib/lowData'
import { BASEMAP_STYLE, BLANK_STYLE, KANSAS_VIEW } from '../lib/map'

const DEFAULT_REGION = 'district:cottonwood-creek'
const MONTHS = 'JFMAMJJASOND'
const usd = (n: number) => `$${Math.round(n).toLocaleString('en-US')}`
const pct = (x: number) => `${Math.round(x * 100)}%`
const pct1 = (x: number) => `${(x * 100).toFixed(1)}%`
const KM_PER_MI = 1.609344

// Classes by rank within the region, since scores are normalized per region and only compare inside it.
const RISK_CLASSES = [
  { min: 0.95, color: '#ff4b2b', opacity: 0.5, label: 'Highest', note: 'top 5% of the region' },
  { min: 0.8, color: '#ff8a1f', opacity: 0.32, label: 'High', note: 'next 15%' },
  { min: 0.5, color: '#ffb21a', opacity: 0.16, label: 'Elevated', note: 'next 30%' },
]
const FACTOR_LABELS: Record<RiskFactor, string> = {
  history: 'Reported wildfires',
  burns: 'Satellite-seen burning',
  lines: 'Power lines',
  people: 'Towns nearby',
}
const riskClass = (rank: number) => RISK_CLASSES.find((c) => rank >= c.min)
const topShare = (rank: number) => `top ${Math.max(1, Math.ceil((1 - rank) * 100))}%`
const riskStep = (scale: number) => ['step', ['get', 'rank'], 0, ...[...RISK_CLASSES].reverse().flatMap((c) => [c.min, c.opacity * scale])]
// Keeps the region and the selected plot clear of the legend in the top-right corner, when the map is wide enough.
const mapPadding = (m: MapRef) => ({ top: 48, bottom: 48, left: 48, right: m.getContainer().clientWidth >= 640 ? 280 : 48 })

type FormKey = 'sites' | 'bare' | 'rich' | 'budget' | 'richKm' | 'bareKm'
const LIMITS: Record<FormKey, { min: number; max: number; label: string }> = {
  sites: { min: 1, max: 60, label: 'Plots' },
  bare: { min: 0, max: 16, label: 'Bare per plot' },
  rich: { min: 0, max: 16, label: 'Rich per plot' },
  budget: { min: 500, max: 500000, label: 'Budget' },
  richKm: { min: 0.5, max: 10, label: 'Rich smoke range' },
  bareKm: { min: 0.1, max: 2, label: 'Bare gas fetch' },
}

function useDebounced<T>(value: T, ms = 400): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function WindRose({ rose, size = 120 }: { rose: number[]; size?: number }) {
  const r = size / 2 - 14
  const max = Math.max(...rose, 0.01)
  const c = size / 2
  return (
    <svg width={size} height={size} aria-label="Fire-weather wind rose">
      {[0.5, 1].map((f) => (
        <circle key={f} cx={c} cy={c} r={r * f} fill="none" stroke="#2a3038" strokeDasharray="1 2" />
      ))}
      {rose.map((share, i) => {
        const len = (share / max) * r
        const a0 = ((i * 22.5 - 9) * Math.PI) / 180
        const a1 = ((i * 22.5 + 9) * Math.PI) / 180
        const p = (a: number, l: number) => `${c + l * Math.sin(a)},${c - l * Math.cos(a)}`
        return share > 0 ? <polygon key={i} points={`${c},${c} ${p(a0, len)} ${p(a1, len)}`} fill="#ffb21a" fillOpacity={0.75} /> : null
      })}
      {['N', 'E', 'S', 'W'].map((d, i) => {
        const a = (i * 90 * Math.PI) / 180
        return (
          <text key={d} x={c + (r + 8) * Math.sin(a)} y={c - (r + 8) * Math.cos(a) + 3} textAnchor="middle" className="num" fontSize={9} fill="#565e68">
            {d}
          </text>
        )
      })}
    </svg>
  )
}

function MonthBars({ hours }: { hours: number[] }) {
  const max = Math.max(...hours, 1)
  const w = 150
  const h = 44
  const bw = w / 12
  return (
    <svg width={w} height={h + 12} aria-label="High fire-danger hours by month">
      {hours.map((v, i) => (
        <g key={i}>
          <rect x={i * bw + 1} y={h - (v / max) * h} width={bw - 2} height={(v / max) * h} fill={v > 0 ? '#ff4b2b' : '#1d2127'} fillOpacity={0.8} />
          <text x={i * bw + bw / 2} y={h + 10} textAnchor="middle" className="num" fontSize={8} fill="#565e68">
            {MONTHS[i]}
          </text>
        </g>
      ))}
    </svg>
  )
}

function CoverageCurve({ curve, chosen }: { curve: number[]; chosen: number }) {
  const w = 300
  const h = 56
  const max = Math.max(...curve, 0.01)
  const x = (i: number) => (i / Math.max(curve.length - 1, 1)) * (w - 8) + 4
  const y = (v: number) => h - 4 - (v / max) * (h - 12)
  const d = curve.map((v, i) => `${i ? 'L' : 'M'}${x(i)},${y(v)}`).join(' ')
  const at = Math.min(chosen, curve.length - 1)
  return (
    <svg width={w} height={h} aria-label="Coverage by number of plots">
      <path d={d} fill="none" stroke="#3ddc97" strokeWidth={1.25} />
      <line x1={x(at)} x2={x(at)} y1={4} y2={h - 4} stroke="#e6e8eb" strokeOpacity={0.4} strokeDasharray="2 2" />
      <rect x={x(at) - 2.5} y={y(curve[at]) - 2.5} width={5} height={5} fill="#e6e8eb" />
      <text x={w - 4} y={10} textAnchor="end" className="num" fontSize={9} fill="#565e68">
        {curve.length - 1} PLOTS · {pct(curve[curve.length - 1])}
      </text>
    </svg>
  )
}

function ClimatePanel({ c }: { c: Climatology }) {
  return (
    <div className="space-y-3 px-4 py-3">
      <div className="flex items-start gap-4">
        <WindRose rose={c.fire_wind_rose} />
        <div className="min-w-0 flex-1 space-y-1 pt-1">
          <div className="label !text-[9.5px]">Wind in High+ fire danger</div>
          {c.fire_wind_modes.map((m) => (
            <div key={m.from} className="num text-[12px] text-text">
              from {m.from} <span className="text-muted">{pct(m.share)}</span>
            </div>
          ))}
          <div className="text-[11px] leading-snug text-muted">
            Smoke drifts the other way, so sensors go on the {c.fire_wind_modes.map((m) => compassOpposite(m.from)).join(' and ')} side of what they
            watch.
          </div>
        </div>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="label mb-1 !text-[9.5px]">High+ hours by month</div>
          <MonthBars hours={c.fire_hours_by_month} />
        </div>
        <div className="w-[110px] shrink-0">
          <KV k="Hours/yr" v={c.fire_hours_per_year} />
          <KV k="Very high" v={c.very_high_hours_per_year} />
          <KV k="Median wind" v={`${Math.round(c.fire_wind_kmh_median / KM_PER_MI)} mph`} />
        </div>
      </div>
    </div>
  )
}

const OPPOSITE: Record<string, string> = {
  N: 'S', NNE: 'SSW', NE: 'SW', ENE: 'WSW', E: 'W', ESE: 'WNW', SE: 'NW', SSE: 'NNW',
  S: 'N', SSW: 'NNE', SW: 'NE', WSW: 'ENE', W: 'E', WNW: 'ESE', NW: 'SE', NNW: 'SSE',
}
const compassOpposite = (d: string) => OPPOSITE[d] ?? d

function PowerRow({ tier, p }: { tier: string; p: TierPower }) {
  const w = p.winter_worst_week
  const f = p.fire_season_worst_week
  const short = (row: typeof w) => (row.days_on_battery == null ? 'OK' : `${row.days_on_battery} d on pack`)
  return (
    <div className="grid grid-cols-[52px_1fr_1fr] items-baseline gap-2 py-[3px] text-[11.5px]">
      <span className="label !text-[9.5px]">{tier}</span>
      <span className="num text-text" title={`${f.made_wh_day} Wh/day made vs ${f.need_wh_day} needed, ${f.sun_hours} sun-hours`}>
        <span className={f.days_on_battery == null ? 'text-ok' : 'text-investigate'}>{short(f)}</span>
      </span>
      <span className="num text-text" title={`${w.made_wh_day} Wh/day made vs ${w.need_wh_day} needed, ${w.sun_hours} sun-hours`}>
        <span className={w.days_on_battery == null ? 'text-ok' : 'text-investigate'}>{short(w)}</span>
      </span>
    </div>
  )
}

function FactorBars({ shares }: { shares: { key: RiskFactor; share: number }[] }) {
  return (
    <div className="space-y-[3px]">
      {shares.map((f) => (
        <div key={f.key} className="grid grid-cols-[118px_1fr_30px] items-center gap-2 text-[10.5px]">
          <span className="text-muted">{FACTOR_LABELS[f.key]}</span>
          <span className="h-1.5 bg-raised">
            <span className="block h-full bg-investigate/80" style={{ width: `${f.share * 100}%` }} />
          </span>
          <span className="num text-right text-dim">{pct(f.share)}</span>
        </div>
      ))}
    </div>
  )
}

function RiskLine({ rank, tallgrass, downwind }: { rank: number; tallgrass: boolean; downwind: number }) {
  const cls = riskClass(rank)
  return (
    <div className="text-[11.5px] leading-snug">
      <span style={{ color: cls?.color ?? '#8b939c' }}>{cls?.label ?? 'Lower'} risk</span>
      <span className="text-muted">
        {' '}
        · {topShare(rank)} of the region{tallgrass ? ' · tallgrass fuel' : ''}
        {downwind >= 0.2 ? ' · fire winds carry it toward a town' : ''}
      </span>
    </div>
  )
}

function SiteCard({ s, open, onToggle }: { s: PlanSite; open: boolean; onToggle: () => void }) {
  return (
    <div className={`border-b border-line ${open ? 'bg-panel-2' : ''}`}>
      <button onClick={onToggle} className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-raised">
        <span className="num w-6 text-[11px] text-investigate">S{s.id}</span>
        <span className="min-w-0 flex-1 truncate text-[12px] text-text">{s.label}</span>
        <span className="num text-[10px] text-dim">
          {s.bare}B · {s.rich}R
        </span>
        <ChevronRight size={12} className={`text-dim transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div className="space-y-2.5 px-4 pb-3 pl-13 text-[11.5px] leading-snug">
          <div className="space-y-1.5">
            <div className="label !text-[9px]">Why this ground</div>
            <RiskLine rank={s.risk.rank} tallgrass={s.risk.tallgrass} downwind={s.risk.downwind_of_town} />
            <FactorBars shares={s.risk.factors} />
            <ul className="space-y-1 text-muted">
              {s.reasons.map((r) => (
                <li key={r}>· {r}</li>
              ))}
            </ul>
          </div>
          <div className="space-y-1">
            <div className="label !text-[9px]">Why this plot over others</div>
            <ul className="space-y-1 text-muted">
              {s.choice.map((r) => (
                <li key={r}>· {r}</li>
              ))}
            </ul>
          </div>
          <div className="space-y-1">
            <div className="label !text-[9px]">Where in the cell</div>
            <ul className="space-y-1 text-muted">
              <li>· {s.placement}</li>
              <li>· {s.layout}</li>
            </ul>
          </div>
          {s.checks.length > 0 && (
            <ul className="space-y-1 text-investigate/90">
              {s.checks.map((r) => (
                <li key={r}>! {r}</li>
              ))}
            </ul>
          )}
          <div className="num text-[10.5px] text-dim">
            {s.gateway ? (
              <>
                LINK {s.gateway.name.toUpperCase()} · {(s.gateway.km / KM_PER_MI).toFixed(1)} MI · {s.gateway.quality.toUpperCase()} ·{' '}
                {s.hops} RELAY{s.hops === 1 ? '' : 'S'} TO STATION
              </>
            ) : (
              <span className="text-escalate">NO RADIO PATH: SURVEY A TALLER MOUNT</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function NumField({ label, value, onChange, min, max, step = 1 }: { label: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="label !text-[9.5px]">{label}</span>
      <input
        type="number"
        value={Number.isNaN(value) ? '' : value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className="field num w-full"
      />
    </label>
  )
}

type CellProps = Record<RiskFactor, number> & { rank: number; covered: number; tallgrass: boolean; downwind: number }

function PlanMap({
  plan,
  selected,
  onSelect,
  busy,
}: {
  plan: RegionPlan | undefined
  selected: number | null
  onSelect: (id: number) => void
  busy: string | null
}) {
  const mapRef = useRef<MapRef>(null)
  const [ready, setReady] = useState(false)
  const [hovered, setHover] = useState<{ id: number; plan: RegionPlan; props: CellProps } | null>(null)
  const hover = hovered?.plan === plan ? hovered : null
  const [legendOpen, setLegendOpen] = useState(true)
  const { on: lowData } = useLowData()
  const lines = useQuery({ queryKey: ['layer', 'power_lines'], queryFn: () => api.layer('power_lines') })
  const fires = useQuery({ queryKey: ['layer', 'wildfire_history'], queryFn: () => api.layer('wildfire_history') })
  const key = plan?.region.key
  const bbox = plan?.region.bbox
  useEffect(() => {
    const m = mapRef.current
    if (ready && bbox && m) m.fitBounds([bbox[0], bbox[1], bbox[2], bbox[3]], { padding: mapPadding(m), duration: 900 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, key])
  const site = plan?.sites.find((s) => s.id === selected)
  useEffect(() => {
    const m = mapRef.current
    if (ready && site && m) m.flyTo({ center: [site.lon, site.lat], zoom: 15, duration: 1000, padding: mapPadding(m) })
  }, [ready, site])
  const wildfires = useMemo(
    () => (fires.data ? { ...fires.data, features: fires.data.features.filter((f) => f.properties?.type === 'WF') } : null),
    [fires.data],
  )

  return (
    <div className="relative flex-1 bg-void">
      <Map
        ref={mapRef}
        initialViewState={KANSAS_VIEW}
        mapStyle={lowData ? BLANK_STYLE : BASEMAP_STYLE}
        style={{ width: '100%', height: '100%' }}
        attributionControl={{ compact: true }}
        onLoad={() => setReady(true)}
        interactiveLayerIds={plan ? ['cells-fill'] : []}
        onMouseMove={(e) => {
          const f = e.features?.[0]
          if (!f || !plan) return setHover(null)
          setHover((h) => (h && h.id === f.id && h.plan === plan ? h : { id: f.id as number, plan, props: f.properties as CellProps }))
        }}
        onMouseLeave={() => setHover(null)}
      >
        <NavigationControl position="bottom-right" showCompass={false} />
        <ScaleControl position="bottom-left" unit="imperial" maxWidth={90} />
        {plan && (
          <Source id="cells" type="geojson" data={plan.geojson.cells} generateId>
            <Layer
              id="cells-fill"
              type="fill"
              paint={{
                'fill-antialias': false,
                'fill-color': ['step', ['get', 'rank'], '#121519', ...[...RISK_CLASSES].reverse().flatMap((c) => [c.min, c.color])] as unknown as string,
                // Fades when zoomed into a plot so the nodes and basemap stay readable.
                'fill-opacity': ['interpolate', ['linear'], ['zoom'], 12, riskStep(1), 15, riskStep(0.25)] as unknown as number,
              }}
            />
            {hover && (
              <Layer id="cells-hover" type="line" filter={['==', ['id'], hover.id]} paint={{ 'line-color': '#e6e8eb', 'line-width': 1.25 }} />
            )}
            <Layer
              id="cells-covered"
              type="line"
              filter={['>=', ['get', 'covered'], 0.3]}
              paint={{ 'line-color': '#3ddc97', 'line-width': 1, 'line-opacity': ['interpolate', ['linear'], ['get', 'covered'], 0.3, 0.25, 0.9, 0.8] }}
            />
          </Source>
        )}
        {plan && (
          <Source id="region" type="geojson" data={plan.region.boundary}>
            <Layer id="region-line" type="line" paint={{ 'line-color': '#e6e8eb', 'line-opacity': 0.6, 'line-width': 1.25 }} />
          </Source>
        )}
        {lines.data && (
          <Source id="lines" type="geojson" data={lines.data}>
            <Layer id="lines" type="line" paint={{ 'line-color': '#c9d4e0', 'line-width': 1, 'line-opacity': 0.45 }} />
          </Source>
        )}
        {wildfires && (
          <Source id="wildfires" type="geojson" data={wildfires}>
            <Layer
              id="wildfires"
              type="circle"
              paint={{ 'circle-radius': 3, 'circle-color': 'transparent', 'circle-stroke-color': '#ff4b2b', 'circle-stroke-width': 1, 'circle-stroke-opacity': 0.8 }}
            />
          </Source>
        )}
        {plan && (
          <Source id="links" type="geojson" data={plan.geojson.links}>
            <Layer
              id="links"
              type="line"
              paint={{
                'line-color': '#5cc8ff',
                'line-width': ['match', ['get', 'kind'], 'backbone', 1.5, 1],
                'line-opacity': ['match', ['get', 'quality'], 'clear', 0.85, 0.5],
                'line-dasharray': ['match', ['get', 'kind'], 'backbone', ['literal', [1, 0]], ['literal', [2, 2]]],
              }}
            />
          </Source>
        )}
        {plan && (
          <Source id="nodes" type="geojson" data={plan.geojson.nodes}>
            <Layer
              id="nodes"
              type="circle"
              minzoom={12}
              paint={{
                'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, ['match', ['get', 'tier'], 'rich', 3, 2], 16, ['match', ['get', 'tier'], 'rich', 7, 5]],
                'circle-color': ['match', ['get', 'tier'], 'rich', '#3ddc97', '#e6e8eb'],
                'circle-stroke-color': '#050607',
                'circle-stroke-width': 1,
              }}
            />
          </Source>
        )}
        {plan?.relays.map((r) => (
          <Marker key={`${r.lon},${r.lat}`} longitude={r.lon} latitude={r.lat} anchor="center">
            <div className="group relative" title={`${r.name} · ${r.mount} · ${r.power} power · to ${r.uplink}`}>
              <Radio size={14} className="text-sample" />
              <span className="num pointer-events-none absolute top-1/2 left-full ml-1.5 hidden -translate-y-1/2 bg-void/85 px-1 text-[10px] whitespace-nowrap text-sample group-hover:block">
                {r.name}
              </span>
            </div>
          </Marker>
        ))}
        {plan && (
          <Marker longitude={plan.station.lon} latitude={plan.station.lat} anchor="center">
            <div className="relative" title={plan.station.name}>
              <span className="block h-3 w-3 border border-text bg-void" />
              <span className="num pointer-events-none absolute top-1/2 left-full ml-2 -translate-y-1/2 bg-void/80 px-1 text-[10px] whitespace-nowrap text-text">
                STATION BRIDGE
              </span>
            </div>
          </Marker>
        )}
        {plan?.sites.map((s) => (
          <Marker
            key={s.id}
            longitude={s.lon}
            latitude={s.lat}
            anchor="center"
            onClick={(e) => {
              e.originalEvent.stopPropagation()
              onSelect(s.id)
            }}
          >
            <div className="relative cursor-pointer">
              <span className={`block h-3.5 w-3.5 rotate-45 border ${selected === s.id ? 'border-text bg-investigate' : 'border-investigate bg-void/70'}`} />
              <span
                className={`num pointer-events-none absolute top-1/2 left-full ml-2 -translate-y-1/2 px-1 text-[10px] whitespace-nowrap ${
                  selected === s.id ? 'bg-text text-void' : 'bg-void/80 text-investigate'
                }`}
              >
                S{s.id}
              </span>
            </div>
          </Marker>
        ))}
      </Map>

      <div className="pointer-events-none absolute inset-3 brackets" style={{ ['--b' as string]: '#3a414b' }} />
      {busy && (
        <div className="hud num absolute top-4 left-4 flex h-7 items-center gap-2 px-3 text-[10px] tracking-[0.12em] text-sample">
          <span className="blink h-1.5 w-1.5 bg-sample" /> PLANNING {busy.toUpperCase()}…
        </div>
      )}
      <div className={`hud absolute top-4 right-4 space-y-1.5 p-3 text-[11px] text-muted ${legendOpen ? 'w-[230px]' : ''}`}>
        <button onClick={() => setLegendOpen((o) => !o)} className="label flex w-full items-center justify-between gap-3 hover:text-text">
          {legendOpen ? 'Fire-start risk' : 'Legend'}
          <ChevronRight size={12} className={`transition-transform ${legendOpen ? 'rotate-90' : ''}`} />
        </button>
        {legendOpen && <Legend />}
      </div>
      {hover && (
        <div className="hud absolute bottom-12 left-4 w-[260px] max-w-[calc(100%-5rem)] space-y-1.5 p-3">
          <RiskLine rank={hover.props.rank} tallgrass={hover.props.tallgrass} downwind={hover.props.downwind} />
          <FactorBars
            shares={(Object.keys(FACTOR_LABELS) as RiskFactor[]).map((k) => ({ key: k, share: hover.props[k] })).sort((a, b) => b.share - a.share)}
          />
          <div className="num text-[10px] text-dim">
            {hover.props.covered >= 0.3 ? `WATCHED ${pct(hover.props.covered)} BY THE PLAN'S PLOTS` : 'NOT WATCHED BY A PLOT'}
          </div>
        </div>
      )}
    </div>
  )
}

function Legend() {
  return (
    <>
      {RISK_CLASSES.map((c) => (
        <div key={c.label} className="flex items-center gap-2.5">
          <span className="h-2.5 w-4 border" style={{ background: c.color, opacity: Math.min(1, c.opacity * 2), borderColor: c.color }} />
          <span className="text-text">{c.label}</span>
          <span className="text-[10px] text-dim">{c.note}</span>
        </div>
      ))}
      <div className="pb-1.5 text-[10px] leading-snug text-dim">
        Scored from reported wildfires, satellite-seen burning, power lines, and towns; raised in tallgrass and where fire winds blow toward a town.
        Hover the map for a cell's breakdown.
      </div>
      <div className="label mb-1 border-t border-line pt-2">Network</div>
      <div className="flex items-center gap-2.5">
        <span className="h-2.5 w-4 border border-ok/80" /> Watched by a plot
      </div>
      <div className="flex items-center gap-2.5">
        <span className="ml-0.5 h-2.5 w-2.5 rotate-45 border border-investigate" /> <span className="ml-1">Sensor plot</span>
      </div>
      <div className="flex items-center gap-2.5">
        <span className="ml-1 h-2 w-2 rounded-full bg-text" /> <span className="ml-0.5">Bare node</span>
        <span className="ml-2 h-2 w-2 rounded-full bg-ok" /> Rich
      </div>
      <div className="flex items-center gap-2.5">
        <Radio size={13} className="text-sample" /> Relay · <span className="h-px w-4 bg-sample" /> link
      </div>
      <div className="flex items-center gap-2.5">
        <span className="ml-0.5 h-2.5 w-2.5 rounded-full border border-escalate" /> <span className="ml-0.5">Reported wildfire</span>
      </div>
      <div className="pt-1 text-[10px] text-dim">Zoom into a plot to see its nodes.</div>
    </>
  )
}

export function Planner() {
  const regions = useQuery({ queryKey: ['planner-regions'], queryFn: api.plannerRegions, retry: true, retryDelay: 2000 })
  const [region, setRegion] = useState(DEFAULT_REGION)
  const [mode, setMode] = useState<'plots' | 'budget'>('plots')
  const [form, setForm] = useState({ sites: 10, bare: 7, rich: 2, budget: 20000, richKm: 3, bareKm: 0.4 })
  const [selected, setSelected] = useState<number | null>(null)
  const problems = (Object.keys(LIMITS) as FormKey[])
    .filter((k) => (k !== 'sites' || mode === 'plots') && (k !== 'budget' || mode === 'budget'))
    .filter((k) => !(Number.isFinite(form[k]) && form[k] >= LIMITS[k].min && form[k] <= LIMITS[k].max))
    .map((k) => `${LIMITS[k].label} must be ${LIMITS[k].min.toLocaleString()}–${LIMITS[k].max.toLocaleString()}`)
  if (form.bare + form.rich < 1) problems.push('A plot needs at least one node')
  const wanted = JSON.stringify({
    region,
    sites: mode === 'plots' ? form.sites : undefined,
    budget_usd: mode === 'budget' ? form.budget : undefined,
    bare_per_site: form.bare,
    rich_per_site: form.rich,
    rich_range_km: form.richKm,
    bare_fetch_km: form.bareKm,
  })
  // Only valid inputs reach the API, so a half-typed number can't replace the plan with an error.
  const committed = useDebounced(problems.length ? null : wanted)
  const [request, setRequest] = useState(wanted)
  if (committed && committed !== request) setRequest(committed)
  const { region: planRegion, ...params } = JSON.parse(request) as PlanParams & { region: string }
  const plan = useQuery({
    queryKey: ['plan', request],
    queryFn: () => api.plan(planRegion, params),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })
  const p = plan.data
  const set = (k: FormKey) => (v: number) => setForm((f) => ({ ...f, [k]: v }))
  const regionName = (key: string) =>
    [...(regions.data?.districts ?? []), ...(regions.data?.counties ?? [])].find((r) => r.key === key)?.name ?? key
  const outOfDate = !!p && (wanted !== request || plan.isFetching || plan.isError || problems.length > 0)
  const plotCost = (form.bare * 175 + form.rich * 240) * 1.1

  return (
    <div className="flex h-full flex-col bg-bg">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[380px] shrink-0 flex-col overflow-y-auto border-r border-line bg-panel">
          <SectionHeader right={problems.length === 0 && (plan.isFetching || wanted !== request) ? <span className="num text-[10px] text-sample">PLANNING…</span> : null}>
            Region planner
          </SectionHeader>
          <div className="space-y-3 border-b border-line px-4 py-3">
            <label className="flex flex-col gap-1">
              <span className="label !text-[9.5px]">Region</span>
              <select
                value={region}
                onChange={(e) => {
                  setRegion(e.target.value)
                  setSelected(null)
                }}
                className="field w-full"
              >
                {!regions.data && <option value={region}>{p?.region.name ?? 'Loading regions…'}</option>}
                <optgroup label="Fire districts">
                  {regions.data?.districts.map((d) => (
                    <option key={d.key} value={d.key}>
                      {d.name}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Kansas counties">
                  {regions.data?.counties.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.name}
                    </option>
                  ))}
                </optgroup>
              </select>
            </label>
            <div className="flex gap-1">
              {(['plots', 'budget'] as const).map((m) => (
                <button key={m} onClick={() => setMode(m)} className={`btn !h-6 flex-1 ${mode === m ? 'btn-primary' : ''}`}>
                  {m === 'plots' ? 'Number of plots' : 'Budget'}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-3 gap-2">
              {mode === 'plots' ? (
                <NumField label="Plots" value={form.sites} onChange={set('sites')} min={1} max={60} />
              ) : (
                <NumField label="Budget $" value={form.budget} onChange={set('budget')} min={500} max={500000} step={500} />
              )}
              <NumField label="Bare / plot" value={form.bare} onChange={set('bare')} min={0} max={16} />
              <NumField label="Rich / plot" value={form.rich} onChange={set('rich')} min={0} max={16} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <NumField label="Rich smoke range km" value={form.richKm} onChange={set('richKm')} min={0.5} max={10} step={0.5} />
              <NumField label="Bare gas fetch km" value={form.bareKm} onChange={set('bareKm')} min={0.1} max={2} step={0.1} />
            </div>
            <p className="text-[11px] leading-snug text-dim">
              Default mix is the sensor design's 7 bare + 2 rich nodes per 15-acre plot. Detection ranges are planning guesses until the field burn trial
              measures them.
            </p>
          </div>

          {(problems.length > 0 || plan.isError || plan.isFetching || wanted !== request) && (
            <div className="space-y-1 border-b border-line px-4 py-3 text-[11.5px] leading-snug">
              {problems.map((m) => (
                <div key={m} className="text-investigate">
                  {m}. The plan updates when it's in range.
                </div>
              ))}
              {plan.isError && !plan.isFetching && (
                <div className="text-escalate">
                  Couldn't plan {regionName(planRegion)}: {(plan.error as Error).message}
                </div>
              )}
              {problems.length === 0 && (plan.isFetching || wanted !== request) && (
                <div className="text-sample">
                  Planning {regionName(JSON.parse(wanted).region)}… A county's first plan downloads its terrain and climate, which takes a few seconds.
                </div>
              )}
              {outOfDate && <div className="text-dim">Below is the previous plan, for {p!.region.name}.</div>}
            </div>
          )}

          {p && (
            <div className={outOfDate ? 'opacity-50' : ''}>
              <SectionHeader right={<span className="num text-[10px] text-dim">{p.region.area_sq_mi.toLocaleString()} SQ MI</span>}>
                {p.region.name}
              </SectionHeader>
              <div className="grid grid-cols-2 gap-x-6 border-b border-line px-4 py-3">
                <KV k="Plots" v={p.summary.sites} />
                <KV k="Relays" v={p.summary.relays} />
                <KV k="Bare nodes" v={p.summary.bare} />
                <KV k="Rich nodes" v={p.summary.rich} />
                <KV k="Hardware" v={usd(p.bom.hardware)} />
                <KV k="+10% spares" v={usd(p.bom.total)} accent="#e6e8eb" />
                <KV k="Priority watched" v={pct1(p.summary.priority_covered)} accent="#3ddc97" />
                <KV k="Max relays" v={p.summary.max_hops ?? '—'} />
              </div>
              <div className="border-b border-line px-4 py-2.5 text-[11.5px] leading-snug text-muted">
                Smoke from the {p.summary.rich} rich nodes watches {pct1(p.summary.watched_by_rich)} of the risk; gas from the {p.summary.bare} bare
                nodes watches {pct1(p.summary.watched_by_bare)}. A bare node only senses its own {p.params.plot_acres}-acre plot and{' '}
                {p.params.bare_fetch_km} km upwind, so the bare count changes cost and how surely a fire inside the plot is confirmed, not where plots
                go. Rich nodes' smoke range decides placement.
              </div>
              {p.params.budget_usd != null && (
                <div className="border-b border-line px-4 py-2.5 text-[11.5px] leading-snug text-muted">
                  {usd(p.bom.total)} of the {usd(p.params.budget_usd)} budget buys {p.summary.sites} plot{p.summary.sites === 1 ? '' : 's'}. Each plot
                  adds about {usd(plotCost)} with spares, plus any relays it needs, so the plan changes in steps of roughly that much.
                </div>
              )}
              <div className="border-b border-line px-4 py-3">
                <div className="label mb-1 !text-[9.5px]">Share of likely fire starts watched, by plots placed</div>
                <CoverageCurve curve={p.summary.coverage_curve} chosen={p.summary.sites} />
                <p className="mt-1 text-[11px] leading-snug text-dim">
                  Plots watch the highest-priority ground; satellites, line faults, and neighbor reports cover the rest. Each extra plot adds less.
                </p>
              </div>

              {p.warnings.length > 0 && (
                <div className="space-y-1.5 border-b border-line px-4 py-3">
                  {p.warnings.map((w) => (
                    <div key={w} className="flex gap-2 text-[11.5px] leading-snug text-investigate">
                      <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {w}
                    </div>
                  ))}
                </div>
              )}

              <SectionHeader right={<span className="num text-[10px] text-dim">ERA5 2016–2025</span>}>Fire-weather climate</SectionHeader>
              <ClimatePanel c={p.climate} />
              <div className="border-t border-b border-line px-4 py-3">
                <div className="grid grid-cols-[52px_1fr_1fr] gap-2 pb-1">
                  <span />
                  <span className="label !text-[9px]">Fire season worst wk</span>
                  <span className="label !text-[9px]">Winter worst wk</span>
                </div>
                <PowerRow tier="Bare" p={p.power.bare} />
                <PowerRow tier="Rich" p={p.power.rich} />
                <p className="mt-1.5 text-[11px] leading-snug text-dim">
                  Solar at {p.climate.sun_hours.fire_season_worst_week} and {p.climate.sun_hours.winter_worst_week} sun-hours. Rich nodes can run the PM fan
                  up to {pct(p.power.rich.max_pm_duty_fire_season ?? 0)} of the time in fire season. PM sensor is below its −10 °C limit about{' '}
                  {p.climate.pm_too_cold_days_per_year} days a year.
                </p>
              </div>

              <SectionHeader right={<span className="num text-[10px] text-dim">{p.summary.reported_wildfires} REPORTED · ~{p.summary.burns_per_year} BURNS/YR</span>}>
                Plots
              </SectionHeader>
              {p.sites.map((s) => (
                <SiteCard key={s.id} s={s} open={selected === s.id} onToggle={() => setSelected(selected === s.id ? null : s.id)} />
              ))}

              <SectionHeader>Relays and station</SectionHeader>
              <div className="space-y-1.5 border-b border-line px-4 py-3 text-[11.5px]">
                <div className="flex justify-between gap-3">
                  <span className="text-text">{p.station.name}</span>
                  <span className="num text-[10px] text-dim">BRIDGE</span>
                </div>
                {p.relays.map((r) => (
                  <div key={`${r.lon},${r.lat}`} className="pt-1">
                    <div className="flex justify-between gap-3">
                      <span className="min-w-0 text-muted">{r.name}</span>
                      <span className="num shrink-0 text-[10px] text-dim">
                        {r.power === 'mains' ? 'MAINS' : 'SOLAR'} · {(r.km / KM_PER_MI).toFixed(1)} MI
                      </span>
                    </div>
                    <div className="text-[10.5px] leading-snug text-dim">
                      {r.why} Carries {r.serves.map((id) => `S${id}`).join(', ')} toward {r.uplink}.
                    </div>
                  </div>
                ))}
              </div>

              <SectionHeader>Bill of materials</SectionHeader>
              <div className="border-b border-line px-4 py-3 text-[11.5px]">
                {p.bom.lines.map((l) => (
                  <div key={l.item} className="flex justify-between gap-3 py-[2px]">
                    <span className="text-muted">
                      {l.qty} × {l.item}
                    </span>
                    <span className="num text-text">{usd(l.total)}</span>
                  </div>
                ))}
                <div className="mt-1 flex justify-between border-t border-line pt-1">
                  <span className="text-muted">Spares (10%)</span>
                  <span className="num text-text">{usd(p.bom.spares)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-text">Total</span>
                  <span className="num text-text">{usd(p.bom.total)}</span>
                </div>
                <p className="mt-1.5 text-[11px] leading-snug text-dim">
                  With the custom carrier board at ~100 units: about {usd(p.bom.custom_pcb_hardware)} before spares. Excludes tax, shipping, labor, and the
                  site survey.
                </p>
              </div>

              <SectionHeader>Assumptions</SectionHeader>
              <ul className="space-y-1.5 px-4 py-3 text-[11px] leading-snug text-dim">
                {p.assumptions.map((a) => (
                  <li key={a}>· {a}</li>
                ))}
              </ul>
            </div>
          )}
        </aside>
        <PlanMap
          plan={p}
          selected={selected}
          onSelect={(id) => setSelected(id)}
          busy={problems.length === 0 && (plan.isFetching || wanted !== request) ? regionName(JSON.parse(wanted).region) : null}
        />
      </div>
    </div>
  )
}
