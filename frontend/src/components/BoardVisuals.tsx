import type { BoardBurn, BoardPost } from '../api'
import { ageMinutes, catMeta, kmAndBearing } from '../lib/board'
import { POINTS } from '../lib/compass'

const CATEGORY_ORDER = ['fire', 'smoke', 'hazard', 'burn', 'other'] as const
export type Filter = 'all' | (typeof CATEGORY_ORDER)[number]

type LatLon = { lat: number; lon: number }

const located = (p: BoardPost): p is BoardPost & LatLon => p.lat != null && p.lon != null

/** 1 for the last hour, fading to 0.35 at a day old. */
const freshness = (p: BoardPost) => {
  const m = ageMinutes(p)
  return m < 60 ? 1 : Math.max(0.35, 1 - (m / 1440) * 0.65)
}

export function CatIcon({ cat, className = 'h-5 w-5' }: { cat: string; className?: string }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round', strokeLinejoin: 'round' } as const
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...common}>
      {cat === 'fire' && (
        <>
          <path d="M12 2.5c.6 3.4 5.5 5.6 5.5 10.8a5.5 5.5 0 0 1-11 0c0-2.6 1.3-4.4 2.6-5.6.1 2 .9 3.3 2.1 3.9-.3-3.2-.2-6.3.8-9.1z" />
          <path d="M12 20.2a2.3 2.3 0 0 1-2.3-2.3c0-1.5 1.2-2.4 2.3-3.5 1.1 1.1 2.3 2 2.3 3.5a2.3 2.3 0 0 1-2.3 2.3z" />
        </>
      )}
      {cat === 'smoke' && (
        <>
          <path d="M6 21c-2.2-2.6 2.2-4.4 0-7s2.2-4.4 0-7" />
          <path d="M12 18c-2.2-2.6 2.2-4.4 0-7s2.2-4.4 0-7" />
          <path d="M18 21c-2.2-2.6 2.2-4.4 0-7s2.2-4.4 0-7" />
        </>
      )}
      {cat === 'hazard' && (
        <>
          <path d="M12 3.2 21.6 20H2.4z" />
          <path d="M12 9.6v4.6M12 17.1v.1" />
        </>
      )}
      {cat === 'burn' && (
        <>
          <circle cx="12" cy="12" r="9.6" strokeDasharray="2.6 2.4" />
          <path d="M12 6.6c.4 2 3.3 3.2 3.3 6.3a3.3 3.3 0 0 1-6.6 0c0-1.5.8-2.6 1.5-3.3.1 1.2.5 1.9 1.2 2.3-.2-1.8 0-3.7.6-5.3z" />
        </>
      )}
      {!['fire', 'smoke', 'hazard', 'burn'].includes(cat) && (
        <>
          <circle cx="12" cy="12" r="9.2" />
          <path d="M12 10.8v6M12 7.4v.1" />
        </>
      )}
    </svg>
  )
}

export function PhoneIcon({ className = 'h-4 w-4' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={2} strokeLinejoin="round">
      <path d="M5 3h4l2 5-2.5 1.5a11 11 0 0 0 6 6L16 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 5a2 2 0 0 1 2-2z" />
    </svg>
  )
}

/** Tiles across the top of the board: what is open right now. */
export function StatTiles({ posts, burns }: { posts: BoardPost[]; burns: BoardBurn[] }) {
  const open = posts.filter((p) => p.status === 'open')
  const hot = open.filter((p) => p.category === 'fire' || p.category === 'smoke')
  const seen = open.reduce((n, p) => n + p.confirms, 0)
  const tiles = [
    { label: 'Open reports', value: open.length, tone: 'text-text', cat: null },
    { label: 'Fire or smoke', value: hot.length, tone: hot.length ? 'text-escalate' : 'text-text', cat: 'fire' },
    { label: 'Neighbors confirming', value: seen, tone: 'text-text', cat: null },
    { label: 'Burns today', value: burns.length, tone: burns.length ? 'text-ok' : 'text-text', cat: 'burn' },
  ]
  return (
    <div className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className="flex flex-col gap-1 bg-panel px-3 py-2.5">
          <span className="label flex items-center gap-1.5">
            {t.cat && <CatIcon cat={t.cat} className={`h-3 w-3 ${t.value ? t.tone : ''}`} />}
            {t.label}
          </span>
          <span className={`num text-[24px] leading-none font-medium ${t.tone}`}>{t.value}</span>
        </div>
      ))}
    </div>
  )
}

const SIZE = 400
const C = SIZE / 2
const R = 176
const RANGES_KM = [2, 3, 5, 8, 10, 15, 20, 30, 50, 80, 100, 150, 200]

function project(center: LatLon, p: LatLon, kmPerUnit: number) {
  const { km, deg } = kmAndBearing(center, p)
  const r = km / kmPerUnit
  const a = (deg * Math.PI) / 180
  return { x: C + r * Math.sin(a), y: C - r * Math.cos(a) }
}

const kmLabel = (km: number) => `${Number.isInteger(km) ? km : km.toFixed(1)} km`

/**
 * Every located open report and today's burns, drawn around the person (once they share location) or around the
 * reports themselves. Board positions are rounded to about a kilometer, so this shows where, not exactly where.
 */
export function AreaScope({
  posts,
  burns,
  position,
  filter,
  onPick,
}: {
  posts: BoardPost[]
  burns: BoardBurn[]
  position: LatLon | null
  filter: Filter
  onPick: (id: number) => void
}) {
  const open = posts.filter((p) => p.status === 'open')
  const placed = open.filter(located)
  const unplaced = open.length - placed.length
  const anchors: LatLon[] = [...placed, ...burns]
  const center: LatLon | null =
    position ??
    (anchors.length
      ? { lat: anchors.reduce((s, a) => s + a.lat, 0) / anchors.length, lon: anchors.reduce((s, a) => s + a.lon, 0) / anchors.length }
      : null)

  const reach = center
    ? Math.max(0, ...placed.map((p) => kmAndBearing(center, p).km), ...burns.map((b) => kmAndBearing(center, b).km + b.radius_km))
    : 0
  const range = RANGES_KM.find((r) => r >= reach * 1.12) ?? Math.ceil(reach * 1.12)
  const kmPerUnit = range / R

  const stacked = new Map<string, number>()
  const blips = center
    ? placed.map((p) => {
        const key = `${p.lat},${p.lon}`
        const k = stacked.get(key) ?? 0
        stacked.set(key, k + 1)
        const at = project(center, p, kmPerUnit)
        const a = k * 2.4
        return { p, x: at.x + (k ? 9 * Math.cos(a) : 0), y: at.y + (k ? 9 * Math.sin(a) : 0) }
      })
    : []
  const matches = (p: BoardPost) => filter === 'all' || p.category === filter

  return (
    <figure className="m-0">
      <div className="brackets relative mx-auto aspect-square w-full max-w-[420px] p-1">
        <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="block h-full w-full" role="group" aria-label="Where reports are">
          <defs>
            <radialGradient id="scope-bg">
              <stop offset="0" style={{ stopColor: 'var(--color-panel-2)' }} />
              <stop offset="1" style={{ stopColor: 'var(--color-void)' }} />
            </radialGradient>
            {(['escalate', 'investigate'] as const).map((c) => (
              <radialGradient key={c} id={`scope-heat-${c}`}>
                <stop offset="0" style={{ stopColor: `var(--color-${c})`, stopOpacity: 0.45 }} />
                <stop offset="1" style={{ stopColor: `var(--color-${c})`, stopOpacity: 0 }} />
              </radialGradient>
            ))}
          </defs>

          <circle cx={C} cy={C} r={R} fill="url(#scope-bg)" style={{ stroke: 'var(--color-line-2)' }} />
          {[0.25, 0.5, 0.75].map((f) => (
            <circle key={f} cx={C} cy={C} r={R * f} fill="none" strokeDasharray={f === 0.5 ? undefined : '2 4'} style={{ stroke: 'var(--color-line-2)' }} />
          ))}
          <path d={`M${C} ${C - R}V${C + R}M${C - R} ${C}H${C + R}`} style={{ stroke: 'var(--color-line)' }} />
          {Array.from({ length: 72 }, (_, i) => {
            const deg = i * 5
            const len = deg % 45 === 0 ? 9 : deg % 15 === 0 ? 5 : 2.5
            const a = (deg * Math.PI) / 180
            return (
              <line
                key={deg}
                x1={C + R * Math.sin(a)}
                y1={C - R * Math.cos(a)}
                x2={C + (R - len) * Math.sin(a)}
                y2={C - (R - len) * Math.cos(a)}
                style={{ stroke: deg % 45 === 0 ? 'var(--color-muted)' : 'var(--color-line-2)' }}
              />
            )
          })}
          {POINTS.filter((pt) => pt.abbr.length === 1).map((pt) => {
            const a = (pt.deg * Math.PI) / 180
            return (
              <text
                key={pt.abbr}
                x={C + (R + 12) * Math.sin(a)}
                y={C - (R + 12) * Math.cos(a)}
                textAnchor="middle"
                dominantBaseline="central"
                className="num"
                fontSize="11"
                style={{ fill: pt.abbr === 'N' ? 'var(--color-text)' : 'var(--color-dim)' }}
              >
                {pt.abbr}
              </text>
            )
          })}
          {center &&
            [0.5, 1].map((f) => (
              <text key={f} x={C + 5} y={C + R * f - 5} className="num" fontSize="10" style={{ fill: 'var(--color-dim)' }}>
                {kmLabel(range * f)}
              </text>
            ))}

          {center &&
            burns.map((b, i) => {
              const at = project(center, b, kmPerUnit)
              const r = Math.max(5, b.radius_km / kmPerUnit)
              const dim = filter !== 'all' && filter !== 'burn'
              return (
                <g key={`burn-${i}`} className="text-ok" opacity={dim ? 0.2 : 1}>
                  <title>{`Registered burn, ${b.radius_km} km around`}</title>
                  <circle cx={at.x} cy={at.y} r={r} fill="currentColor" fillOpacity={0.07} stroke="currentColor" strokeDasharray="3 3" />
                  <circle cx={at.x} cy={at.y} r={2} fill="currentColor" />
                </g>
              )
            })}

          <g style={{ mixBlendMode: 'screen' }}>
            {blips
              .filter(({ p }) => (p.category === 'fire' || p.category === 'smoke') && matches(p))
              .map(({ p, x, y }) => (
                <circle
                  key={`heat-${p.id}`}
                  cx={x}
                  cy={y}
                  r={24 + 6 * Math.min(p.confirms, 4)}
                  fill={`url(#scope-heat-${p.category === 'fire' ? 'escalate' : 'investigate'})`}
                  opacity={freshness(p)}
                />
              ))}
          </g>

          {center && (
            <g style={{ stroke: position ? 'var(--color-sample)' : 'var(--color-muted)' }} strokeWidth={1.5}>
              <path d={`M${C - 9} ${C}h6M${C + 3} ${C}h6M${C} ${C - 9}v6M${C} ${C + 3}v6`} />
              {position && (
                <text x={C} y={C + 20} textAnchor="middle" className="num" fontSize="10" stroke="none" style={{ fill: 'var(--color-sample)' }}>
                  YOU
                </text>
              )}
            </g>
          )}

          {blips.map(({ p, x, y }) => {
            const m = catMeta(p.category)
            const on = matches(p)
            const s = 9 + Math.min(p.confirms, 4) * 1.5
            const age = ageMinutes(p)
            const said = `${m.label}, ${age < 1 ? 'just now' : age < 60 ? `${age} min ago` : `${Math.round(age / 60)} hr ago`}`
            return (
              <a
                key={p.id}
                href={`#post-${p.id}`}
                aria-label={said}
                aria-hidden={!on}
                tabIndex={on ? 0 : -1}
                className={`${m.text} cursor-pointer outline-none [&:focus-visible>.focus]:opacity-100`}
                style={{ pointerEvents: on ? 'auto' : 'none', opacity: on ? freshness(p) : 0.15 }}
                onClick={(e) => {
                  e.preventDefault()
                  onPick(p.id)
                }}
              >
                <title>{said}</title>
                {p.flagged && on && <circle className="scope-ping" cx={x} cy={y} r={s * 0.7} fill="none" stroke="currentColor" strokeWidth={1.5} />}
                <circle cx={x} cy={y} r={s} fill="transparent" />
                <circle className="focus" cx={x} cy={y} r={s + 3} fill="none" opacity={0} style={{ stroke: 'var(--color-text)' }} strokeWidth={1.5} />
                <rect
                  x={x - s / 2}
                  y={y - s / 2}
                  width={s}
                  height={s}
                  transform={`rotate(45 ${x} ${y})`}
                  fill="currentColor"
                  style={{ stroke: 'var(--color-void)' }}
                  strokeWidth={1.5}
                />
              </a>
            )
          })}

          {!center && (
            <text x={C} y={C} textAnchor="middle" dominantBaseline="central" fontSize="13" style={{ fill: 'var(--color-muted)' }}>
              No reports with a location
            </text>
          )}
        </svg>
      </div>
      <figcaption className="mt-2 text-center text-[12px] leading-snug text-muted">
        {position
          ? 'Centered on you. Your location stays on this phone. '
          : center
            ? 'Centered on the reports. '
            : 'Reports show here as neighbors post them. '}
        Points are rounded to about 1 km.
        {unplaced > 0 && ` ${unplaced} ${unplaced === 1 ? 'report has' : 'reports have'} no location.`}
      </figcaption>
    </figure>
  )
}

export function CategoryFilter({ posts, filter, onChange }: { posts: BoardPost[]; filter: Filter; onChange: (f: Filter) => void }) {
  const open = posts.filter((p) => p.status === 'open')
  const chips: { key: Filter; label: string; n: number }[] = [
    { key: 'all', label: 'All', n: open.length },
    ...CATEGORY_ORDER.map((c) => ({ key: c, label: catMeta(c).label, n: open.filter((p) => p.category === c).length })),
  ]
  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6" role="group" aria-label="Show reports">
      {chips.map((c) => {
        const on = filter === c.key
        const m = c.key === 'all' ? null : catMeta(c.key)
        return (
          <button
            key={c.key}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on && c.key !== 'all' ? 'all' : c.key)}
            className={`btn !h-11 !gap-1.5 !px-1.5 ${on ? (m ? `${m.border} ${m.tint} ${m.text}` : 'btn-primary') : c.n ? '' : 'text-dim'}`}
          >
            {m && <CatIcon cat={c.key} className={`h-4 w-4 shrink-0 ${on || !c.n ? '' : m.text}`} />}
            <span>{c.label}</span>
            <span className="num opacity-70">{c.n}</span>
          </button>
        )
      })}
    </div>
  )
}

/** Reports per hour over the last day, stacked by category. */
export function ActivityStrip({ posts, filter }: { posts: BoardPost[]; filter: Filter }) {
  const bins = Array.from({ length: 24 }, () => Object.fromEntries(CATEGORY_ORDER.map((c) => [c, 0])) as Record<string, number>)
  for (const p of posts) {
    const h = Math.floor(ageMinutes(p) / 60)
    if (h > 23) continue
    const cat = (CATEGORY_ORDER as readonly string[]).includes(p.category) ? p.category : 'other'
    bins[23 - h][cat]++
  }
  const tallest = Math.max(1, ...bins.map((b) => Object.values(b).reduce((s, n) => s + n, 0)))
  const lastHour = Object.values(bins[23]).reduce((s, n) => s + n, 0)
  const H = 44
  const W = 10
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <h3 className="label">Reports by hour</h3>
        <span className="num text-[11px] text-muted">{lastHour ? `${lastHour} in the last hour` : 'None in the last hour'}</span>
      </div>
      <svg
        viewBox={`0 0 ${24 * W} ${H}`}
        preserveAspectRatio="none"
        className="block h-12 w-full"
        role="img"
        aria-label={`${posts.length} reports in the last 24 hours, ${lastHour} in the last hour`}
      >
        {bins.map((b, i) => {
          let y = H
          return (
            <g key={i}>
              <rect x={i * W + 1} y={H - 1} width={W - 2} height={1} style={{ fill: 'var(--color-line-2)' }} />
              {CATEGORY_ORDER.map((c) => {
                if (!b[c]) return null
                const h = (b[c] / tallest) * (H - 4)
                y -= h
                return (
                  <rect
                    key={c}
                    x={i * W + 1}
                    y={y}
                    width={W - 2}
                    height={h - 0.5}
                    fill="currentColor"
                    className={catMeta(c).text}
                    opacity={filter === 'all' || filter === c ? 0.9 : 0.15}
                  />
                )
              })}
            </g>
          )
        })}
      </svg>
      <div className="num mt-1 flex justify-between text-[10px] text-dim">
        <span>24 h ago</span>
        <span>12 h</span>
        <span>Now</span>
      </div>
    </div>
  )
}

/** Up to five marks for the people who confirmed, so a glance shows how many. */
export function SeenMeter({ n }: { n: number }) {
  return (
    <span className="inline-flex items-center gap-[3px]" aria-hidden="true">
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} className={`h-2 w-2 rotate-45 ${i < n ? 'bg-text' : 'border border-line-2'}`} />
      ))}
      {n > 5 && <span className="num ml-0.5 text-[10px] text-text">+{n - 5}</span>}
    </span>
  )
}

/** An arrow pointing from the person to the report, with the distance. */
export function DirectionChip({ from, to }: { from: LatLon; to: LatLon }) {
  const { km, deg } = kmAndBearing(from, to)
  const near = km < 1
  const point = POINTS[Math.round(deg / 45) % 8]
  return (
    <span
      className="num inline-flex items-center gap-1 border border-line-2 px-1.5 py-[1px] text-[11px] text-text"
      aria-label={near ? 'Under 1 km from you' : `About ${Math.round(km)} km ${point.name} of you`}
    >
      {!near && (
        <svg viewBox="0 0 12 12" className="h-3 w-3" style={{ transform: `rotate(${deg}deg)` }} aria-hidden="true">
          <path d="M6 1 9.5 10 6 8 2.5 10z" fill="currentColor" />
        </svg>
      )}
      {near ? '< 1 km' : `${Math.round(km)} km ${point.abbr}`}
    </span>
  )
}
