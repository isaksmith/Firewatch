import { useEffect, useRef, useState } from 'react'
import { askMotionPermission, directionText, DISTANCES, headingFromEvent, POINTS } from '../lib/compass'

export interface Pointing {
  bearing: number | null
  miles: number | null
}

type Mode = 'closed' | 'live' | 'fallback' | 'locked'

/** "Smoke is far away? Point at it." Asks for motion only when tapped. */
export function CompassPicker({ value, onChange, disabled }: { value: Pointing; onChange: (v: Pointing) => void; disabled?: boolean }) {
  const [mode, setMode] = useState<Mode>(value.bearing != null ? 'locked' : 'closed')
  const [heading, setHeading] = useState<number | null>(null)
  const stop = useRef<(() => void) | null>(null)
  const latest = useRef<number | null>(null)

  // Reset from outside (after a post): go back to the link.
  useEffect(() => {
    if (value.bearing == null && value.miles == null && mode === 'locked') setMode('closed')
  }, [value.bearing, value.miles, mode])

  useEffect(() => () => stop.current?.(), [])

  function listen() {
    stop.current?.()
    latest.current = null
    setHeading(null)
    const onEvent = (e: Event) => {
      const h = headingFromEvent(e)
      if (h == null) return
      latest.current = h
      setHeading(h)
      window.clearTimeout(timer)
    }
    const timer = window.setTimeout(() => {
      if (latest.current == null) {
        stop.current?.()
        setMode('fallback')
      }
    }, 3000)
    window.addEventListener('deviceorientationabsolute', onEvent)
    window.addEventListener('deviceorientation', onEvent)
    stop.current = () => {
      window.clearTimeout(timer)
      window.removeEventListener('deviceorientationabsolute', onEvent)
      window.removeEventListener('deviceorientation', onEvent)
      stop.current = null
    }
  }

  function start() {
    // Permission must be requested straight from the tap, before anything is awaited.
    const asked = askMotionPermission()
    setMode('live')
    asked.then((ok) => {
      if (!ok) setMode('fallback')
      else listen()
    })
  }

  function lock() {
    if (heading == null) return
    stop.current?.()
    onChange({ ...value, bearing: Math.round(heading) % 360 })
    setMode('locked')
  }

  function change() {
    onChange({ bearing: null, miles: value.miles })
    start()
  }

  function pickPoint(deg: number) {
    onChange({ ...value, bearing: deg })
    setMode('locked')
  }

  const distance = (
    <div className="mt-2">
      <p className="text-[13px] text-text">How far away?</p>
      <div className="mt-1 grid grid-cols-2 gap-1.5" role="group" aria-label="How far away">
        {DISTANCES.map((d) => (
          <button
            key={d.miles}
            type="button"
            aria-pressed={value.miles === d.miles}
            disabled={disabled}
            onClick={() => onChange({ ...value, miles: d.miles })}
            className={`btn !h-11 !px-1 ${value.miles === d.miles ? 'btn-primary' : ''}`}
          >
            {d.label}
          </button>
        ))}
      </div>
    </div>
  )

  if (mode === 'closed')
    return (
      <button type="button" disabled={disabled} onClick={start} className="mt-2 min-h-11 text-left text-[13px] text-text underline underline-offset-2">
        Smoke is far away? Point at it
      </button>
    )

  return (
    <div className="mt-2 border border-line-2 p-3">
      {mode === 'live' && (
        <>
          <p className="text-[13px] text-text">Hold your phone flat and point its top at the smoke.</p>
          <p className="mt-1 text-[15px] text-text" role="status">
            {heading == null ? 'Waiting for the compass...' : `Pointing ${directionText(heading)}`}
          </p>
          <p className="text-[12px] text-muted">Rough estimate. A phone compass can be off by a lot.</p>
          <button type="button" className="btn btn-primary mt-2 !h-11 w-full" disabled={heading == null} onClick={lock}>
            Use this direction
          </button>
        </>
      )}
      {mode === 'fallback' && (
        <>
          <p className="text-[13px] text-text">This phone&apos;s compass is not available. Pick a direction:</p>
          <div className="mt-1 grid grid-cols-4 gap-1.5" role="group" aria-label="Direction">
            {POINTS.map((p) => (
              <button key={p.abbr} type="button" className="btn !h-11 !px-1" aria-label={p.name} onClick={() => pickPoint(p.deg)}>
                {p.abbr}
              </button>
            ))}
          </div>
        </>
      )}
      {mode === 'locked' && value.bearing != null && (
        <p className="flex flex-wrap items-center gap-x-3 text-[13px] text-text">
          <span>Direction: {directionText(value.bearing)}</span>
          <button type="button" className="min-h-11 underline underline-offset-2" onClick={change}>
            Change
          </button>
        </p>
      )}
      {(mode === 'locked' || mode === 'fallback') && distance}
    </div>
  )
}
