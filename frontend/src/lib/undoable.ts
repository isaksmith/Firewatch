import { useEffect, useRef, useState } from 'react'

/** Run an action after a short countdown the person can cancel: undo instead of "Are you sure?". */
export function useUndoable(seconds = 5) {
  const [left, setLeft] = useState<number | null>(null)
  const fnRef = useRef<(() => void) | null>(null)
  useEffect(() => {
    if (left === null) return
    const t = setTimeout(() => {
      if (left <= 1) {
        const f = fnRef.current
        fnRef.current = null
        setLeft(null)
        f?.()
      } else setLeft(left - 1)
    }, 1000)
    return () => clearTimeout(t)
  }, [left])
  return {
    left,
    start: (fn: () => void) => {
      fnRef.current = fn
      setLeft(seconds)
    },
    undo: () => {
      fnRef.current = null
      setLeft(null)
    },
  }
}
