import { useEffect, useRef, useState } from 'react'
import {
  Bug, Timer, ShieldCheck, CircleCheck, CircleX, Code, Cpu, Flag, FlaskConical, Lightbulb, LoaderCircle, Play, Search,
  TriangleExclamationPoint, User, Wrench, Circle,
} from 'lucide-react'
import type { Diagnosis } from '../types'

export interface ChatMessage {
  role: 'ai' | 'user'
  text: string
  stage?: string
  status?: string
  diagnosis?: Diagnosis | null
  /** When the event arrived (ms since epoch); used to show how long each step took. */
  at?: number
}

interface Props {
  messages: ChatMessage[]
  running: boolean
  explanation: string
  /** Repairs applied after the explanation was written (history entries after iteration 0). */
  repairs?: number
}

function stageIcon(stage?: string, status?: string) {
  if (stage === 'fix' || stage === 'fixing') return Wrench
  if (stage === 'lint') return Search
  if (stage === 'synthesis') return Cpu
  if (stage === 'strength') return Bug
  if (stage === 'timing') return Timer
  if (stage === 'second_opinion') return ShieldCheck
  if (stage === 'simulate') return status === 'PASS' ? CircleCheck : status === 'FAIL' || status === 'ERROR' ? CircleX : Play
  if (stage === 'done') return status === 'PASS' ? Flag : TriangleExclamationPoint
  if (stage === 'rtl') return Code
  if (stage === 'testbench') return FlaskConical
  if (stage === 'intent') return Lightbulb
  if (stage === 'start') return Play
  if (stage === 'error') return TriangleExclamationPoint
  return Circle
}

/** "42s" or "3m 05s". */
export function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60)
  return m > 0 ? `${m}m ${String(seconds % 60).padStart(2, '0')}s` : `${seconds}s`
}

/** Mounted only while a run is active, so it starts counting when the run starts. A live model can
 *  take minutes per step; a clock makes "slow" look different from "stuck". */
function RunTimer({ messageCount }: { messageCount: number }) {
  const runStart = useRef(Date.now())
  const stepStart = useRef(Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    stepStart.current = Date.now() // a new event arrived: the step clock restarts
    setNow(Date.now())
  }, [messageCount])
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  const step = Math.max(0, Math.floor((now - stepStart.current) / 1000))
  const total = Math.max(0, Math.floor((now - runStart.current) / 1000))
  return (
    <span className="run-timer" data-testid="run-timer">
      Working…{' '}
      {/* aria-hidden: a clock inside a live region would be announced every second */}
      <span aria-hidden="true">
        {formatElapsed(step)} since the last update, {formatElapsed(total)} total
      </span>
      {step >= 45 && <span className="slow"> Free models can take a few minutes per step.</span>}
    </span>
  )
}

export default function AgentChat({ messages, running, explanation, repairs = 0 }: Props) {
  const endRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, running])

  return (
    <section className="side-section" aria-label="Run">
      <div className="run-head">
        <h2 className="side-title" style={{ marginBottom: 0 }}>Run</h2>
      </div>
      {/* The live region wraps a plain list: a list element itself may not take the log role. */}
      <div role="log" aria-live="polite" aria-relevant="additions" aria-label="Run timeline">
      <ol className="run-list">
        {messages.map((m, i) => {
          const isUser = m.role === 'user'
          const Icon = isUser ? User : stageIcon(m.stage, m.status)
          const tone = m.status === 'PASS' ? 'ok' : m.status === 'FAIL' || m.status === 'ERROR' || m.stage === 'error' ? 'bad' : ''
          const prev = messages[i - 1]
          const took = m.at && prev?.at && !isUser ? Math.round((m.at - prev.at) / 1000) : null
          return (
            <li key={i} className={`run-item ${isUser ? 'user' : ''} ${tone}`}>
              <Icon size={14} className="ico" aria-hidden="true" />
              {/* A finished step keeps its trailing "..." in the event text; drop it once a later
                  step has arrived so the timeline does not look stuck. */}
              <span className="txt">{i < messages.length - 1 || !running ? m.text.replace(/(\.\.\.|…)$/, '.') : m.text}</span>
              <span className="when">{took != null && took > 0 ? formatElapsed(took) : ''}</span>
              {m.diagnosis && (
                <details className="run-diag" data-testid="chat-diagnosis">
                  {/* Collapsed by default: the full text is also under "Self-correction loop" on the Results tab
                      (self-review UX finding: 20+ lines of model prose filled the 320 px sidebar). */}
                  <summary><strong>Diagnosis</strong> <span className="muted">(click to expand)</span></summary>
                  {m.diagnosis.root_cause && <div><strong>Root cause:</strong> <InlineCode text={m.diagnosis.root_cause} /></div>}
                  {m.diagnosis.fix_location && <div><strong>Fix location:</strong> <InlineCode text={m.diagnosis.fix_location} /></div>}
                  {m.diagnosis.confidence && <div className="muted">Confidence: {m.diagnosis.confidence}</div>}
                </details>
              )}
            </li>
          )
        })}
        {running && (
          <li className="run-item live">
            <LoaderCircle size={14} className="ico spin" aria-hidden="true" />
            <RunTimer messageCount={messages.length} />
            <span className="when" />
          </li>
        )}
      </ol>
      </div>
      <div ref={endRef} aria-hidden="true" />
      {explanation && messages.length > 0 && messages[messages.length - 1]?.text !== explanation && (
        <div className="explanation-box" aria-label="Design explanation">
          <p>{explanation}</p>
          {/* The model explains its FIRST draft; repairs do not rewrite it (live finding, 20 Nov: the text described
              NOR gates after the repair had switched the latch to NAND gates). */}
          {repairs > 0 && (
            <p className="muted explanation-stale" data-testid="explanation-stale">
              Written for the first draft. The self-correction loop changed the code {repairs === 1 ? 'once' : `${repairs} times`} afterwards,
              so parts of this may not match the final design; the Design tab shows the final code.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

/** `code` spans from model text shown as code, not as literal backticks. Plain text only: nothing is parsed as HTML. */
function InlineCode({ text }: { text: string }) {
  const parts = text.split(/(`[^`]+`)/g)
  return <>{parts.map((p, i) => (p.length > 2 && p.startsWith('`') && p.endsWith('`') ? <code key={i}>{p.slice(1, -1)}</code> : p))}</>
}
