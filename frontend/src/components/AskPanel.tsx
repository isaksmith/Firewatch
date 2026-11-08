import { useMutation, useQuery } from '@tanstack/react-query'
import { Send, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type AskAnswer } from '../api'
import { useTier } from '../lib/tier'

type Turn = { id: number; question: string; answer?: AskAnswer; error?: string }

const EXAMPLES = ['Where is the fire?', 'Is it heading toward town?', 'How big is it?']

/** Ask Firewatch what a resident's texted question would get back: the same facts, model and checks, but the
 *  answer stays on this screen. */
export function AskPanel({ onClose, onOpenAlert }: { onClose: () => void; onOpenAlert: (id: number) => void }) {
  const { castPlus, castName, online } = useTier()
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false })
  const llmOn = castPlus && health.data?.llm_configured === true
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const nextId = useRef(1)
  const end = useRef<HTMLDivElement>(null)

  const ask = useMutation({
    mutationFn: ({ question }: { id: number; question: string }) => api.ask(question, castPlus),
    onSuccess: (answer, { id }) => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, answer } : t))),
    onError: (e: Error, { id }) => setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, error: e.message } : t))),
  })

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [turns])

  function send(text: string) {
    const question = text.trim()
    if (!question || ask.isPending) return
    const id = nextId.current++
    setTurns((ts) => [...ts, { id, question }])
    setDraft('')
    ask.mutate({ id, question })
  }

  return (
    <aside
      aria-label="Ask Firewatch"
      className="absolute inset-0 z-20 flex w-full flex-col bg-panel md:static md:inset-auto md:z-auto md:w-[400px] md:shrink-0 md:border-l md:border-line"
    >
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line pr-2 pl-4">
        <span className="label !text-muted">Ask Firewatch</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close Ask Firewatch"
          className="flex h-6 w-6 items-center justify-center text-dim hover:bg-raised hover:text-text"
        >
          <X size={14} />
        </button>
      </div>
      <p className="border-b border-line px-4 py-2 text-[11.5px] leading-snug text-muted">
        The answer a resident would get by texting this question, from the open fires in the district. Nothing is sent.{' '}
        <span className={llmOn ? 'text-ok' : 'text-degraded'}>
          {llmOn
            ? `${castName}: agent dispatch`
            : !online
            ? 'Internet down: plain template answers, as a radio question would get.'
            : !castPlus
            ? `${castName}: plain template answers. FireCast Plus adds agent dispatch.`
            : 'Agent dispatch not configured on the server: plain template answers.'}
        </span>
      </p>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3" aria-live="polite">
        {turns.length === 0 && (
          <div className="space-y-2">
            <p className="text-[12px] text-dim">Try one:</p>
            {EXAMPLES.map((q) => (
              <button key={q} type="button" onClick={() => send(q)} className="btn !h-7 w-full !justify-start">
                {q}
              </button>
            ))}
          </div>
        )}
        {turns.map((t) => (
          <div key={t.id} className="space-y-1.5">
            <div className="ml-8 border border-line-2 bg-void px-3 py-2 text-[12.5px] text-text">{t.question}</div>
            {t.answer ? (
              <div className="mr-8 border border-sample/40 bg-sample/5 px-3 py-2 text-[12.5px] text-text">
                <div>{t.answer.answer}</div>
                <div className="num mt-1.5 flex flex-wrap gap-x-3 text-[10px] tracking-[0.08em] text-dim uppercase">
                  <span className={t.answer.by_model ? 'text-ok' : ''}>{t.answer.by_model ? 'Agent dispatch' : 'Template'}</span>
                  <span>{t.answer.answer.length}/160 chars</span>
                  {t.answer.fires.map((f) => (
                    <button key={f.id} type="button" onClick={() => onOpenAlert(f.id)} className="uppercase hover:text-text">
                      Fire {f.id} ›
                    </button>
                  ))}
                </div>
              </div>
            ) : t.error ? (
              <div className="mr-8 text-[12px] text-escalate">Could not get an answer: {t.error}</div>
            ) : (
              <div className="label mr-8">{llmOn ? 'Asking agent dispatch…' : 'Looking it up…'}</div>
            )}
          </div>
        ))}
        <div ref={end} />
      </div>
      <form
        className="flex shrink-0 gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(draft)
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          maxLength={300}
          placeholder="Ask about the fires, as a resident would"
          aria-label="Question"
          className="field min-w-0 flex-1 !h-8"
        />
        <button type="submit" disabled={!draft.trim() || ask.isPending} className="btn !h-8" aria-label="Send question">
          <Send size={12} /> Ask
        </button>
      </form>
    </aside>
  )
}
