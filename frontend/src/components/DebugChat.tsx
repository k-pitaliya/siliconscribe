import { Fragment, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Bot, CircleCheck, CircleX, LoaderCircle, MessageCircleQuestion, Send, Square, Wrench } from 'lucide-react'
import { askAgent } from '../api'
import type { AgentEvent, AgentFix, SimulationRerun, Waveform } from '../types'

type ToolEvent = Extract<AgentEvent, { type: 'tool' }>
type AnswerEvent = Extract<AgentEvent, { type: 'answer' }>

interface Turn {
  question: string
  status: string
  tools: ToolEvent[]
  answer?: AnswerEvent
  error?: string
}

interface Props {
  rtl: string
  tb: string
  model?: string
  thinking?: string
  /** True while a generation or re-run is in progress: questions wait until it ends. */
  busy: boolean
  /** The waveform on screen, used to turn "@125ns" in an answer into a cursor position. */
  waveform: Waveform | null
  /** Move the waveform cursor to this time (VCD ticks) and show the Waveform tab. */
  onShowTime: (ticks: number) => void
  /** Put a verified fix into the editor. */
  onApplyFix: (file: 'rtl' | 'testbench', code: string) => void
  /** The simulation the agent ran for evidence (the editor's current code). */
  onEvidenceRun: (run: SimulationRerun, rtl: string, tb: string) => void
}

const SUGGESTIONS = [
  'Why did the first check fail?',
  'Is the design or the testbench wrong?',
  'Walk me through the first 5 clock cycles.',
]

const TOOL_LABEL: Record<string, string> = {
  failing_checks: 'Read the failing checks',
  values_at: 'Read values at a time',
  changes: 'Listed value changes',
  cycle_table: 'Built a cycle-by-cycle table',
  find_value: 'Searched the waveform for a value',
  drivers: 'Found what drives a signal',
  read_code: 'Read source lines',
  test_fix: 'Simulated a candidate fix',
  '(format)': 'Reply format corrected',
}

export default function DebugChat({ rtl, tb, model, thinking, busy, waveform, onShowTime, onApplyFix, onEvidenceRun }: Props) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const [asking, setAsking] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => () => abortRef.current?.abort(), [])
  useEffect(() => { endRef.current?.scrollIntoView({ block: 'nearest' }) }, [turns])

  const update = (fn: (t: Turn) => Turn) => setTurns((prev) => (prev.length ? [...prev.slice(0, -1), fn(prev[prev.length - 1])] : prev))

  async function ask(question: string) {
    const q = question.trim()
    if (!q || asking || busy || !rtl || !tb) return
    const history = turns
      .filter((t) => t.answer)
      .slice(-4)
      .map((t) => ({ question: t.question, answer: (t.answer as AnswerEvent).text.slice(0, 8000) }))
    setTurns((prev) => [...prev, { question: q, status: 'Sending…', tools: [] }])
    setInput('')
    setAsking(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const askedRtl = rtl
    const askedTb = tb
    try {
      await askAgent(
        { rtl_code: askedRtl, testbench_code: askedTb, question: q.slice(0, 2000), history, model: model || undefined, reasoning_effort: thinking || undefined },
        (e) => {
          if (e.type === 'status') update((t) => ({ ...t, status: e.message }))
          else if (e.type === 'run') {
            onEvidenceRun(e.result, askedRtl, askedTb)
            update((t) => ({ ...t, status: 'Reading the evidence…' }))
          } else if (e.type === 'tool') update((t) => ({ ...t, tools: [...t.tools, e], status: 'Reading the evidence…' }))
          else if (e.type === 'answer') update((t) => ({ ...t, answer: e, status: '' }))
          else if (e.type === 'error') update((t) => ({ ...t, error: e.message, status: '' }))
        },
        ctrl.signal,
      )
    } catch (err) {
      const e = err as Error
      update((t) => ({ ...t, status: '', error: e.name === 'AbortError' ? 'Stopped.' : e.message }))
    } finally {
      setAsking(false)
      if (abortRef.current === ctrl) abortRef.current = null
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void ask(input)
    }
  }

  const disabled = busy || !rtl || !tb
  return (
    <section className="side-section debug-chat" aria-label="Ask about this run">
      <h2 className="side-title">
        <MessageCircleQuestion size={14} aria-hidden="true" /> Ask about this run
      </h2>
      <p className="muted debug-intro">
        The AI re-simulates the code in the editor, then reads the waveform and the source before answering.
      </p>
      {turns.length === 0 && (
        <div className="example-chips" aria-label="Example questions">
          {SUGGESTIONS.map((s) => (
            <button key={s} type="button" className="chip" disabled={disabled || asking} onClick={() => void ask(s)}>{s}</button>
          ))}
        </div>
      )}
      <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Debugging conversation" className="debug-log">
        {turns.map((t, i) => (
          <div key={i} className="debug-turn">
            <p className="debug-q">{t.question}</p>
            {t.tools.length > 0 && (
              <ol className="debug-steps" aria-label="Evidence the AI collected">
                {t.tools.map((ev, j) => (
                  <li key={j} className={ev.ok ? '' : 'bad'}>
                    <details>
                      <summary>
                        {ev.tool === 'test_fix' ? <Wrench size={12} aria-hidden="true" /> : <span className="step-dot" aria-hidden="true" />}
                        <span>{TOOL_LABEL[ev.tool] ?? ev.tool}{argHint(ev)}</span>
                      </summary>
                      {ev.thought && <p className="muted step-thought">{ev.thought}</p>}
                      <pre className="step-result">{ev.result}</pre>
                    </details>
                  </li>
                ))}
              </ol>
            )}
            {t.status && (
              <p className="debug-status"><LoaderCircle size={13} className="spin" aria-hidden="true" /> {t.status}</p>
            )}
            {t.error && <p className="field-error" role="alert">{t.error}</p>}
            {t.answer && (
              <Answer answer={t.answer} waveform={waveform} onShowTime={onShowTime} onApplyFix={onApplyFix} />
            )}
          </div>
        ))}
        <div ref={endRef} aria-hidden="true" />
      </div>
      <div className="debug-input">
        <label htmlFor="debug-question" className="sr-only">Question about this run</label>
        <textarea
          id="debug-question"
          rows={2}
          value={input}
          maxLength={2000}
          placeholder={disabled ? 'Generate or load a design first' : 'e.g. why is count 2 at 20 ns?'}
          disabled={disabled}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
        />
        {asking ? (
          <button type="button" className="btn btn-danger" onClick={() => abortRef.current?.abort()} aria-label="Stop the question">
            <Square size={13} aria-hidden="true" /> Stop
          </button>
        ) : (
          <button type="button" className="btn btn-primary" onClick={() => void ask(input)} disabled={disabled || !input.trim()} aria-label="Ask">
            <Send size={14} aria-hidden="true" /> Ask
          </button>
        )}
      </div>
    </section>
  )
}

function argHint(ev: ToolEvent): string {
  const a = ev.args ?? {}
  const sig = typeof a.signal === 'string' ? a.signal : Array.isArray(a.signals) ? (a.signals as unknown[]).slice(0, 3).join(', ') : ''
  const t = typeof a.t_ns === 'number' ? `@${a.t_ns}ns` : typeof a.from_ns === 'number' ? `${a.from_ns}–${typeof a.to_ns === 'number' ? a.to_ns : 'end'}ns` : ''
  const parts = [sig, t, typeof a.file === 'string' ? a.file : ''].filter(Boolean)
  return parts.length ? `: ${parts.join(' ')}` : ''
}

function Answer({ answer, waveform, onShowTime, onApplyFix }: {
  answer: AnswerEvent
  waveform: Waveform | null
  onShowTime: (ticks: number) => void
  onApplyFix: (file: 'rtl' | 'testbench', code: string) => void
}) {
  const [applied, setApplied] = useState(false)
  const SUSPECT: Record<string, string> = { design: 'Design', testbench: 'Testbench', both: 'Design and testbench', unclear: 'Unclear', none: 'No bug' }
  return (
    <div className={`debug-answer ${answer.rule_based ? 'rule' : ''}`} data-testid="agent-answer">
      <div className="debug-answer-head">
        <Bot size={14} aria-hidden="true" />
        <span>{answer.rule_based ? 'Rule-based evidence (no AI)' : 'AI answer'}</span>
        {!answer.rule_based && (
          <span className="muted">{answer.steps} evidence step{answer.steps === 1 ? '' : 's'}</span>
        )}
      </div>
      {!answer.rule_based && answer.model && <p className="debug-model muted">{answer.model}</p>}
      {!answer.rule_based && answer.suspect !== 'unclear' && (
        <p className="debug-verdict">Suspect: <strong>{SUSPECT[answer.suspect] ?? answer.suspect}</strong> · confidence {answer.confidence}</p>
      )}
      {answer.note && <p className="debug-note">{answer.note}</p>}
      <RichText text={answer.text} waveform={waveform} onShowTime={onShowTime} />
      {answer.fix && <FixCard fix={answer.fix} applied={applied} onApply={() => { onApplyFix(answer.fix!.file, answer.fix!.code); setApplied(true) }} />}
    </div>
  )
}

function FixCard({ fix, applied, onApply }: { fix: AgentFix; applied: boolean; onApply: () => void }) {
  const ok = fix.status === 'PASS'
  return (
    <div className={`fix-card ${ok ? 'ok' : 'bad'}`} data-testid="agent-fix">
      <div className="fix-head">
        {ok ? <CircleCheck size={14} aria-hidden="true" /> : <CircleX size={14} aria-hidden="true" />}
        <span>
          Proposed fix to the {fix.file === 'rtl' ? 'design' : 'testbench'}: the server re-simulated it,{' '}
          <strong>{fix.status}</strong> {fix.test_count > 0 ? `(${fix.pass_count} of ${fix.test_count} checks passed)` : ''}
        </span>
      </div>
      {fix.file === 'testbench' && (
        <p className="debug-note">This changes the checker itself. A testbench fix can make a wrong design pass: read it before you apply it.</p>
      )}
      {!ok && <pre className="step-result">{fix.summary}</pre>}
      <details>
        <summary>View the proposed {fix.file === 'rtl' ? 'design' : 'testbench'}</summary>
        <pre className="step-result fix-code">{fix.code}</pre>
      </details>
      <button type="button" className="btn" onClick={onApply} disabled={applied}>
        {applied ? 'Applied to the editor' : 'Apply to the editor'}
      </button>
      {applied && <p className="muted">Press Re-run to see it in the main results.</p>}
    </div>
  )
}

/** Model text with `code`, **bold**, ``` blocks and clickable "@125ns" times. Plain text only: nothing is parsed as HTML. */
export function RichText({ text, waveform, onShowTime }: { text: string; waveform: Waveform | null; onShowTime: (ticks: number) => void }) {
  const ps = waveform?.timescale_ps ?? null
  const blocks = text.split(/```[a-z]*\n?/)
  return (
    <div className="rich-text">
      {blocks.map((b, i) =>
        i % 2 === 1 ? (
          <pre key={i} className="step-result">{b.replace(/\n$/, '')}</pre>
        ) : (
          b.split(/\n{2,}/).filter((p) => p.trim()).map((p, j) => <p key={`${i}-${j}`}>{inline(p.trim(), ps, onShowTime)}</p>)
        ),
      )}
    </div>
  )
}

// Times are clickable with or without the '@' (models write "at 25ns" as often as "@25ns").
const TOKEN_RE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|(?:@\s?)?\b\d+(?:\.\d+)?\s?ns\b)/g

function inline(p: string, ps: number | null, onShowTime: (ticks: number) => void): ReactNode {
  return p.split(TOKEN_RE).map((part, k) => {
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) return <code key={k}>{part.slice(1, -1)}</code>
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={k}>{part.slice(2, -2)}</strong>
    const m = /^(?:@\s?)?(\d+(?:\.\d+)?)\s?ns$/.exec(part)
    if (m) {
      const ns = Number(m[1])
      if (ps && ps > 0) {
        const ticks = Math.round((ns * 1000) / ps)
        return (
          <button key={k} type="button" className="time-link" onClick={() => onShowTime(ticks)} title="Show this time in the waveform">
            {part}
          </button>
        )
      }
      return <code key={k}>{part}</code>
    }
    return <Fragment key={k}>{part}</Fragment>
  })
}
