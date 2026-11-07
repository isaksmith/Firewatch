import { X } from 'lucide-react'
import type { Milestone, ScenarioStatus } from '../api'
import { compass, kmhToMph } from '../lib/format'

const FW_COLOR: Record<string, string> = {
  signal: '#ffb21a',
  investigate: '#ffb21a',
  escalate: '#ff4b2b',
  page: '#ff4b2b',
  mutual_aid: '#5cc8ff',
  roll: '#ff4b2b',
  on_scene: '#ff4b2b',
}

const LABELLED = new Set(['call', 'on_scene', 'page'])
const SHORT: Record<string, string> = { call: '911', on_scene: 'On scene', page: 'Page' }

function localClock(s: ScenarioStatus, t: number) {
  return new Date(new Date(s.t0).getTime() + t * 60000).toLocaleTimeString('en-US', {
    timeZone: 'America/Chicago',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function Lane({ label, items, x, now, color, projectFrom }: {
  label: string
  items: Milestone[]
  x: (t: number) => string
  now: number
  color: (m: Milestone) => string
  projectFrom?: number
}) {
  return (
    <div className="relative h-[26px]">
      <span className="label absolute top-[7px] -left-[86px] w-[78px] text-right !text-[9px]">{label}</span>
      <div className="absolute inset-x-0 top-[12px] h-px bg-line-2" />
      {items
        .filter((m) => m.t != null)
        .map((m) => {
          const t = m.t as number
          const happened = t <= now
          const projected = projectFrom != null && t > projectFrom && !happened
          return (
            <div key={m.key} className="absolute top-0 flex -translate-x-1/2 flex-col items-center" style={{ left: x(t) }}>
              <span
                className="mt-[8px] h-[9px] w-[9px] rotate-45"
                style={{
                  background: happened && !projected ? color(m) : 'transparent',
                  boxShadow: `inset 0 0 0 1.25px ${color(m)}`,
                  opacity: happened || projected ? 1 : 0.35,
                }}
                title={`${m.label} · T+${t}`}
              />
            </div>
          )
        })}
      {items
        .filter((m) => m.t != null && LABELLED.has(m.key))
        .map((m) => (
          <span
            key={`l-${m.key}`}
            className="num absolute top-[19px] -translate-x-1/2 text-[9px] whitespace-nowrap text-dim"
            style={{ left: x(m.t as number) }}
          >
            {SHORT[m.key] ?? m.label} {m.t}
          </span>
        ))}
    </div>
  )
}

function WaitingBanner({ w }: { w: NonNullable<ScenarioStatus['waiting']> }) {
  return (
    <div className="num absolute top-1/2 left-1/2 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 border border-ok/60 bg-void/95 px-3 py-1.5 text-[11px] whitespace-nowrap text-ok">
      <span className="blink h-1.5 w-1.5 rotate-45 bg-ok" />
      CLOCK HELD · WAITING FOR {w.name.toUpperCase()} TO REPLY {w.reply} ON RADIO {w.mesh_id}
      <span className="text-dim">· SCRIPT IN {w.seconds_left}S</span>
    </div>
  )
}

export function ScenarioStrip({ s, onClose, onReplay, replaying }: {
  s: ScenarioStatus
  onClose: () => void
  onReplay: () => void
  replaying: boolean
}) {
  const span = s.duration_min
  const now = Math.max(0, s.t_min ?? 0)
  const x = (t: number) => `${(Math.min(Math.max(t, 0), span) / span) * 100}%`
  const size = s.growth[Math.min(Math.round(now), s.growth.length - 1)]
  const maxAc = s.growth[s.growth.length - 1]?.acres || 1
  const growthPath = s.growth
    .filter((g) => g.minute <= now)
    .map((g, i) => `${i ? 'L' : 'M'}${(g.minute / span) * 1000},${40 - (g.acres / maxAc) * 38}`)
    .join(' ')
  const pageT = s.firewatch.find((m) => m.key === 'page')?.t ?? undefined
  const fwOn = s.size_on_scene.firewatch
  const baseOn = s.size_on_scene.baseline
  const w = s.weather

  return (
    <div className="flex h-[104px] shrink-0 border-b border-line bg-void">
      <div className="flex w-[230px] shrink-0 flex-col justify-between border-r border-line px-4 py-2.5">
        <div className="flex items-center justify-between">
          <span className="label !text-sample">Scenario{s.synthetic ? ' · synthetic' : ''}</span>
          {s.running && <span className="blink h-1.5 w-1.5 bg-sample" />}
        </div>
        <div className="flex items-baseline gap-2">
          <span className="num text-[28px] leading-none font-semibold text-text">T+{String(Math.round(now)).padStart(2, '0')}</span>
          <span className="num text-[11px] text-muted">{localClock(s, now)}</span>
        </div>
        <div className="num truncate text-[10px] text-dim" title={s.title}>
          GFDI {Math.round(w.gfdi)} {w.gfdi_band.toUpperCase()} · {compass(w.wind_dir_deg)} {Math.round(kmhToMph(w.wind_kmh))} MPH · RH {w.rh_pct}%
        </div>
      </div>

      <div className="relative min-w-0 flex-1 py-2 pr-6 pl-[100px]">
        <div className="relative h-full">
          <svg viewBox="0 0 1000 40" preserveAspectRatio="none" className="pointer-events-none absolute inset-x-0 bottom-0 h-[34px] w-full">
            {growthPath && <path d={`${growthPath} L${(now / span) * 1000},40 L0,40 Z`} fill="#ff4b2b" opacity={0.12} />}
            {growthPath && <path d={growthPath} fill="none" stroke="#ff4b2b" strokeOpacity={0.5} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
          </svg>
          <Lane label="Today" items={s.baseline} x={x} now={now} color={() => '#8b939d'} />
          <Lane label="Firewatch" items={s.firewatch} x={x} now={now} color={(m) => FW_COLOR[m.key] ?? '#e6e8eb'} projectFrom={pageT} />
          <div className="absolute top-0 bottom-0 w-px bg-text/70" style={{ left: x(now) }} />
          <span className="label absolute bottom-0 -left-[86px] w-[78px] text-right !text-[9px]">Fire size</span>
          {s.waiting && <WaitingBanner w={s.waiting} />}
        </div>
      </div>

      <div className="flex w-[260px] shrink-0 flex-col justify-between border-l border-line px-4 py-2.5">
        <div className="flex items-start justify-between">
          <div>
            <div className="label !text-[9px]">Fire now</div>
            <div className="num text-[15px] font-semibold text-text">
              {size?.acres ?? 0} AC <span className="text-[11px] font-normal text-muted">· {size?.head_mi.toFixed(1) ?? '0.0'} MI RUN</span>
            </div>
          </div>
          <div className="flex gap-1">
            <button onClick={onReplay} disabled={replaying} className="btn !h-6 !px-2 text-[10px]">
              {s.running ? 'Running' : 'Run again'}
            </button>
            <button onClick={onClose} className="flex h-6 w-6 items-center justify-center text-dim hover:bg-raised hover:text-text" aria-label="Hide scenario">
              <X size={13} />
            </button>
          </div>
        </div>
        <div className="num text-[10.5px] text-muted">
          <div className="label mb-0.5 !text-[9px]">At first truck on scene</div>
          {fwOn && baseOn ? (
            <span>
              <span className="text-escalate">{fwOn.acres} AC</span> with Firewatch · <span className="text-text">{baseOn.acres} AC</span> today
            </span>
          ) : (
            <span className="text-dim">Today: {baseOn?.acres ?? '—'} AC at T+62</span>
          )}
        </div>
      </div>
    </div>
  )
}
