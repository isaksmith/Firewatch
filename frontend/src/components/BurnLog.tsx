import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type NewBurn } from '../api'
import { centralInput, centralToIso, clock12 } from '../lib/format'
import { useLowData } from '../lib/lowData'
import { useUndoable } from '../lib/undoable'
import { UndoBar } from './ui'

/** Said the next time the panel opens, when a burn was saved or failed after the panel had closed. */
let notice: { text: string; bad: boolean } | null = null

/** Send the burn. Works even if the panel is gone by the time the answer comes back. */
function submitBurn(body: NewBurn, qc: QueryClient, keepalive: boolean): Promise<string> {
  return api.logBurn(body, keepalive).then(
    (b) => {
      qc.invalidateQueries({ queryKey: ['burns'] })
      qc.invalidateQueries({ queryKey: ['alerts'] })
      notice = { text: `Burn logged. Smoke near it will not page the district until ${clock12(b.end)}.`, bad: false }
      return notice.text
    },
    (e: Error) => {
      notice = { text: e.message, bad: true }
      throw e
    },
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12.5px] font-medium text-text">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11.5px] text-dim">{hint}</span>}
    </label>
  )
}

export function BurnLog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const { on: lowData } = useLowData()
  const burns = useQuery({ queryKey: ['burns'], queryFn: api.burns, refetchInterval: lowData ? 60_000 : 30_000 })
  const [caller, setCaller] = useState('')
  const [lat, setLat] = useState('37.27')
  const [lon, setLon] = useState('-99.33')
  const [start, setStart] = useState(() => centralInput(new Date()))
  const [end, setEnd] = useState(() => centralInput(new Date(Date.now() + 5 * 3600_000)))
  const [done, setDone] = useState<string | null>(() => (notice && !notice.bad ? notice.text : null))
  const [failed, setFailed] = useState<string | null>(() => (notice?.bad ? notice.text : null))
  const [saving, setSaving] = useState(false)
  const undoable = useUndoable(6)
  useEffect(() => {
    notice = null
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const begin = () => {
    const body: NewBurn = { caller: caller.trim(), lat: Number(lat), lon: Number(lon), start: centralToIso(start), end: centralToIso(end) }
    setDone(null)
    setFailed(null)
    undoable.start(
      () => {
        setSaving(true)
        // Show the "saved" note on the next open even if this panel is closed before the answer arrives.
        notice = { text: 'Your last burn call was saved.', bad: false }
        submitBurn(body, qc, false)
          .then((t) => {
            setDone(t)
            setCaller('')
          })
          .catch((e: Error) => setFailed(e.message))
          .finally(() => setSaving(false))
      },
      () => {
        void submitBurn(body, qc, true).catch(() => {})
      },
    )
  }

  const latN = Number(lat)
  const lonN = Number(lon)
  let problem: string | null = null
  if (!caller.trim()) problem = 'Type who called.'
  else if (lat.trim() === '' || lon.trim() === '' || Number.isNaN(latN) || Number.isNaN(lonN) || Math.abs(latN) > 90 || Math.abs(lonN) > 180)
    problem = 'Check the latitude and longitude. They are numbers like 37.27 and -99.33 (the station).'
  else if (!start || !end || new Date(end) <= new Date(start)) problem = 'The end time must be after the start time.'

  const list = burns.data?.burns ?? []
  const inputCls = 'field w-full !h-11 !text-[14px]'

  return (
    <aside className="flex w-[400px] shrink-0 flex-col border-l border-line bg-panel">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line pr-2 pl-4">
        <span className="label !text-muted">Burn log</span>
        <button onClick={onClose} className="flex h-6 w-6 items-center justify-center text-dim hover:bg-raised hover:text-text" aria-label="Close burn log">
          <X size={14} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <section className="border-b border-line px-4 py-4">
          <h2 className="mb-3 text-[15px] font-semibold">Log a burn call</h2>
          <div className="space-y-3">
            <Field label="Who called">
              <input value={caller} onChange={(e) => setCaller(e.target.value)} className={inputCls} placeholder="Henderson" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Latitude">
                <input value={lat} onChange={(e) => setLat(e.target.value)} inputMode="decimal" className={inputCls} />
              </Field>
              <Field label="Longitude">
                <input value={lon} onChange={(e) => setLon(e.target.value)} inputMode="decimal" className={inputCls} />
              </Field>
            </div>
            <p className="-mt-1 text-[11.5px] text-dim">Where the burn is, as latitude and longitude for now.</p>
            <Field label="Starts" hint="Central time">
              <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Ends">
              <input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} className={inputCls} />
            </Field>
            {problem && caller.length > 0 && <p className="text-[12px] text-investigate">{problem}</p>}
            {undoable.left !== null ? (
              <UndoBar message="Logging this burn." left={undoable.left} onUndo={undoable.undo} />
            ) : (
              <button
                disabled={!!problem || saving}
                onClick={begin}
                className="btn btn-primary !h-12 w-full !text-[13px]"
              >
                Log this burn
              </button>
            )}
            {failed && <p className="text-[12px] text-escalate">{failed}</p>}
            {done && (
              <p role="status" className="border border-line-2 border-l-2 border-l-ok bg-raised px-3 py-2 text-[12.5px]">
                {done}
              </p>
            )}
          </div>
        </section>
        <section className="px-4 py-4">
          <h2 className="mb-2 text-[15px] font-semibold">Burns on file</h2>
          {burns.isLoading && <p className="text-[12px] text-dim">Loading…</p>}
          {burns.isError && <p className="text-[12px] text-escalate">Could not load the burn list.</p>}
          {burns.data && list.length === 0 && <p className="text-[12px] text-dim">No burns called in yet.</p>}
          <ul>
            {list.map((b) => (
              <li key={b.id} className="border-t border-line py-2.5">
                <div className="text-[13px]">{b.label ?? `${b.caller} burn`}</div>
                <div className="num mt-0.5 flex justify-between gap-2 text-[11px] text-dim">
                  <span>
                    {b.caller} called {clock12(b.called_in)}
                  </span>
                  <span className="text-ok">
                    {clock12(b.start)} to {clock12(b.end)}
                  </span>
                </div>
                <div className="num mt-0.5 text-[10.5px] text-dim">
                  {b.lat.toFixed(3)}, {b.lon.toFixed(3)}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </aside>
  )
}
