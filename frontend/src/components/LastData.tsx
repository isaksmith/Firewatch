import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { clock12, plainDate } from '../lib/format'

function when(iso: string): string {
  const d = new Date(iso)
  const today = new Date().toDateString() === d.toDateString()
  return today ? clock12(iso) : plainDate(iso)
}

/**
 * Offline, FireCast keeps working on what it last received. This says what that was: when the fire's weather
 * was sampled and when its last evidence arrived, so nobody mistakes an old forecast for a fresh one.
 */
export function LastData({ eventId, className = '' }: { eventId: number; className?: string }) {
  // Same query key as the alert drawer, so this reads the cached alert rather than fetching it again.
  const q = useQuery({ queryKey: ['alert', eventId], queryFn: () => api.alert(eventId), refetchInterval: 3_000 })
  const a = q.data
  if (!a) return null
  const w = a.weather
  return (
    <span className={`text-degraded ${className}`}>
      Offline: using the last data received.{' '}
      {w.valid_time ? (
        <>
          Weather sampled {when(w.valid_time)}
          {w.source ? ` (${w.source})` : ''}
        </>
      ) : (
        'No weather sample'
      )}
      , last evidence {when(a.last_seen)}.
    </span>
  )
}
