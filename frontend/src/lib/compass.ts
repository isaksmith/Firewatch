// Compass helpers for pointing at smoke from far away. Nothing here runs until the person taps.

export const POINTS = [
  { abbr: 'N', name: 'north', deg: 0 },
  { abbr: 'NE', name: 'northeast', deg: 45 },
  { abbr: 'E', name: 'east', deg: 90 },
  { abbr: 'SE', name: 'southeast', deg: 135 },
  { abbr: 'S', name: 'south', deg: 180 },
  { abbr: 'SW', name: 'southwest', deg: 225 },
  { abbr: 'W', name: 'west', deg: 270 },
  { abbr: 'NW', name: 'northwest', deg: 315 },
] as const

export const DISTANCES = [
  { label: 'Under 1 mile', miles: 0.5 },
  { label: '1 to 3 miles', miles: 2 },
  { label: '3 to 5 miles', miles: 4 },
  { label: 'Farther than 5 miles', miles: 7 },
] as const

const norm = (d: number) => ((d % 360) + 360) % 360

export const pointName = (deg: number) => POINTS[Math.round(norm(deg) / 45) % 8].name

/** "northwest (312°)" */
export const directionText = (deg: number) => `${pointName(deg)} (${Math.round(norm(deg)) % 360}°)`

type MotionEvent = Event & { alpha?: number | null; webkitCompassHeading?: number }

/** iPhone gives webkitCompassHeading. Android gives alpha on the absolute event; heading = 360 - alpha, plus the screen turn. */
export function headingFromEvent(e: Event): number | null {
  const ev = e as MotionEvent
  if (typeof ev.webkitCompassHeading === 'number' && Number.isFinite(ev.webkitCompassHeading)) return norm(ev.webkitCompassHeading)
  if (ev.type === 'deviceorientationabsolute' && typeof ev.alpha === 'number' && Number.isFinite(ev.alpha)) {
    const angle = typeof screen !== 'undefined' && screen.orientation ? screen.orientation.angle : 0
    return norm(360 - ev.alpha + angle)
  }
  return null
}

/** Must be called straight from the tap, before any await. Resolves false when refused. */
export function askMotionPermission(): Promise<boolean> {
  const DOE = (typeof window !== 'undefined' ? window.DeviceOrientationEvent : undefined) as
    | (typeof DeviceOrientationEvent & { requestPermission?: () => Promise<string> })
    | undefined
  if (DOE && typeof DOE.requestPermission === 'function') {
    try {
      return DOE.requestPermission().then(
        (r) => r === 'granted',
        () => false,
      )
    } catch {
      return Promise.resolve(false)
    }
  }
  return Promise.resolve(true)
}
