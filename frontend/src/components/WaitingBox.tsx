import { firstLine, savedAtText, type RowState, type Saved } from '../lib/outbox'
import type { Flash } from '../lib/useOutbox'

export function WaitingBox({
  rows,
  flashes,
  stateOf,
  onSend,
  onDelete,
}: {
  rows: Saved[]
  flashes: Flash[]
  stateOf: (key: string) => RowState
  onSend: (key: string) => void
  onDelete: (key: string) => void
}) {
  const flashed = new Set(flashes.map((f) => f.key))
  const shown = rows.filter((r) => !flashed.has(r.key))
  if (!shown.length && !flashes.length) return null
  return (
    <section className="border border-line bg-panel p-4" aria-label="Waiting to send">
      <h2 className="label mb-2">Waiting to send</h2>
      <ul className="divide-y divide-line">
        {flashes.map((f) => (
          <li key={f.key} className="py-2">
            <p className="break-words text-[14px] text-text">{firstLine(f.line)}</p>
            <p className="text-[13px] text-text" role="status">
              Sent.
            </p>
          </li>
        ))}
        {shown.map((r) => {
          const st = stateOf(r.key)
          const photoOnly = r.textSent
          const dead = st.mode === 'rejected' || st.mode === 'expired'
          return (
            <li key={r.key} className="py-2">
              <p className="break-words text-[14px] text-text">{photoOnly ? 'Photo for your post, waiting to send' : firstLine(r.body)}</p>
              <p className="num text-[12px] text-muted">{savedAtText(r.savedAt)}</p>
              {st.mode === 'limited' && st.text && <p className="text-[13px] text-investigate">{st.text}</p>}
              {st.mode === 'rejected' && (
                <p className="text-[13px] text-escalate">
                  This post could not be sent.{st.text ? ` ${st.text}` : ''}
                </p>
              )}
              {st.mode === 'expired' && (
                <p className="text-[13px] text-escalate">Not sent: saved over 2 hours ago. Post again if it still matters.</p>
              )}
              <div className="mt-1 flex flex-wrap gap-1.5">
                {!dead && (
                  <button type="button" className="btn !h-11" onClick={() => onSend(r.key)}>
                    Send now
                  </button>
                )}
                <button type="button" className="btn !h-11" onClick={() => onDelete(r.key)}>
                  Delete
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
