import { useEffect, useRef } from 'react'
import type { Diagnosis } from '../types'

export interface ChatMessage {
  role: 'ai' | 'user'
  text: string
  stage?: string
  status?: string
  diagnosis?: Diagnosis | null
}

interface Props {
  messages: ChatMessage[]
  running: boolean
  explanation: string
}

function stageIcon(stage?: string, status?: string): string {
  if (stage === 'fix' || stage === 'fixing') return 'fa-screwdriver-wrench'
  if (stage === 'lint') return 'fa-magnifying-glass'
  if (stage === 'synthesis') return 'fa-microchip'
  if (stage === 'simulate') {
    if (status === 'PASS') return 'fa-circle-check'
    if (status === 'FAIL' || status === 'ERROR') return 'fa-circle-xmark'
    return 'fa-play'
  }
  if (stage === 'done') return status === 'PASS' ? 'fa-flag-checkered' : 'fa-triangle-exclamation'
  if (stage === 'rtl' || stage === 'testbench') return 'fa-code'
  if (stage === 'intent') return 'fa-lightbulb'
  if (stage === 'error') return 'fa-triangle-exclamation'
  return 'fa-robot'
}

export default function AgentChat({ messages, running, explanation }: Props) {
  const endRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    // smooth scroll to bottom on new messages
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, running])

  return (
    <aside className="right-panel glass-panel" aria-label="AI Agent chat">
      <div className="panel-header">
        <h3>
          <i className="fa-regular fa-comments" aria-hidden="true" /> AI Agent
        </h3>
        <span
          className={`status-indicator ${running ? 'busy' : 'online'}`}
          role="status"
          aria-label={running ? 'Agent busy' : 'Agent online'}
          title={running ? 'Busy' : 'Online'}
        />
      </div>
      <div className="chat-container" ref={containerRef}>
        <div
          className="chat-messages"
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Agent conversation"
        >
          {messages.map((m, i) => {
            const isAi = m.role === 'ai'
            const statusClass =
              m.status === 'PASS' ? 'ok' : m.status === 'FAIL' || m.status === 'ERROR' || m.stage === 'error' ? 'bad' : ''
            return (
              <div key={i} className={`message ${isAi ? 'ai-msg' : 'user-msg'}`}>
                <div className={`msg-avatar ${isAi ? '' : 'user'}`} aria-hidden="true">
                  <i className={`fa-solid ${isAi ? stageIcon(m.stage, m.status) : 'fa-user'}`} />
                </div>
                <div className={`msg-bubble ${isAi ? '' : 'user'} ${statusClass}`}>
                  <p>{m.text}</p>
                  {m.diagnosis && (
                    <div className="msg-diagnosis" data-testid="chat-diagnosis">
                      {m.diagnosis.root_cause && (
                        <div><strong>Root cause:</strong> {m.diagnosis.root_cause}</div>
                      )}
                      {m.diagnosis.fix_location && (
                        <div><strong>Fix location:</strong> {m.diagnosis.fix_location}</div>
                      )}
                      {m.diagnosis.confidence && (
                        <div className="muted">Confidence: {m.diagnosis.confidence}</div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
          {running && (
            <div className="message ai-msg" aria-live="polite">
              <div className="msg-avatar" aria-hidden="true">
                <i className="fa-solid fa-circle-notch fa-spin" />
              </div>
              <div className="msg-bubble">
                <p className="muted">Working…</p>
              </div>
            </div>
          )}
          <div ref={endRef} tabIndex={-1} aria-hidden="true" />
        </div>
        {explanation && messages.length > 0 && messages[messages.length - 1]?.text !== explanation && (
          <div className="explanation-box" role="note" aria-label="Design explanation">
            <i className="fa-solid fa-circle-info" aria-hidden="true" /> {explanation}
          </div>
        )}
      </div>
    </aside>
  )
}
