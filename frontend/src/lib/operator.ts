import { useSyncExternalStore } from 'react'

const KEY = 'firewatch.operator'
const DEFAULT = 'Dispatch 1'
const listeners = new Set<() => void>()
/** Used when storage is blocked, so the name still works until reload. */
let memory: string | null = null

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? memory ?? DEFAULT
  } catch {
    return memory ?? DEFAULT
  }
}

export function setOperator(name: string) {
  memory = name
  try {
    localStorage.setItem(KEY, name)
  } catch {
    /* storage blocked; the in-memory name is used */
  }
  listeners.forEach((l) => l())
}

export function useOperator(): string {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    read,
  )
}
