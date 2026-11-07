import { useCallback, useEffect, useRef, useState } from 'react'
import { deleteRow, drain, listRecords, rowState, type DrainHooks, type Saved } from './outbox'

export interface Flash {
  key: string
  line: string
}

export function useOutbox(onSent: () => void) {
  const [rows, setRows] = useState<Saved[]>([])
  const [flashes, setFlashes] = useState<Flash[]>([])
  const [, bump] = useState(0)
  const onSentRef = useRef(onSent)
  onSentRef.current = onSent
  const alive = useRef(true)

  const reload = useCallback(async () => {
    const all = await listRecords()
    if (!alive.current) return
    setRows(all)
    bump((n) => n + 1)
  }, [])

  const hooks = useRef<DrainHooks>({
    onTextSent: () => onSentRef.current(),
    onDone: (r) => {
      const f = { key: r.key, line: r.body }
      setFlashes((x) => [...x.filter((y) => y.key !== f.key), f])
      window.setTimeout(() => alive.current && setFlashes((x) => x.filter((y) => y !== f)), 5000)
    },
    onChange: () => void reload(),
  })

  const send = useCallback(
    async (only?: string) => {
      await drain(hooks.current, only)
      await reload()
    },
    [reload],
  )

  const remove = useCallback(
    async (key: string) => {
      await deleteRow(key)
      await reload()
    },
    [reload],
  )

  // Page open, and the connection coming back.
  useEffect(() => {
    alive.current = true
    void reload().then(() => send())
    const on = () => void send()
    window.addEventListener('online', on)
    return () => {
      alive.current = false
      window.removeEventListener('online', on)
    }
  }, [reload, send])

  // Every 30 s, only while something waits.
  const waiting = rows.length > 0
  useEffect(() => {
    if (!waiting) return
    const t = window.setInterval(() => void send(), 30000)
    return () => window.clearInterval(t)
  }, [waiting, send])

  return { rows, flashes, send, remove, reload, stateOf: rowState }
}
