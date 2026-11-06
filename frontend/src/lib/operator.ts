import { useSyncExternalStore } from 'react'

const KEY = 'firewatch.operator'
const listeners = new Set<() => void>()

export function setOperator(name: string) {
  localStorage.setItem(KEY, name)
  listeners.forEach((l) => l())
}

export function useOperator(): string {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => localStorage.getItem(KEY) ?? 'Dispatch 1',
  )
}
