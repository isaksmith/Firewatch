import { useEffect, useRef, useState } from 'react'

/**
 * Run an action after a short countdown the person can cancel: undo instead of "Are you sure?".
 * Only the Undo button cancels. Leaving the screen during the countdown saves now, and closing or
 * reloading the tab runs `onUnload` (a keepalive request) so the action is not lost.
 */
export function useUndoable(seconds = 5) {
  const [left, setLeft] = useState<number | null>(null)
  const fnRef = useRef<(() => void) | null>(null)
  const unloadRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    if (left === null) return
    const t = setTimeout(() => {
      if (left <= 1) {
        const f = fnRef.current
        fnRef.current = null
        unloadRef.current = null
        setLeft(null)
        f?.()
      } else setLeft(left - 1)
    }, 1000)
    return () => clearTimeout(t)
  }, [left])

  useEffect(() => {
    const flushUnload = () => {
      const f = unloadRef.current
      fnRef.current = null
      unloadRef.current = null
      f?.()
    }
    window.addEventListener('pagehide', flushUnload)
    window.addEventListener('beforeunload', flushUnload)
    return () => {
      window.removeEventListener('pagehide', flushUnload)
      window.removeEventListener('beforeunload', flushUnload)
      // Unmounted mid-countdown: commit now.
      const f = fnRef.current
      fnRef.current = null
      unloadRef.current = null
      f?.()
    }
  }, [])

  return {
    left,
    start: (fn: () => void, onUnload?: () => void) => {
      fnRef.current = fn
      unloadRef.current = onUnload ?? fn
      setLeft(seconds)
    },
    undo: () => {
      fnRef.current = null
      unloadRef.current = null
      setLeft(null)
    },
  }
}
