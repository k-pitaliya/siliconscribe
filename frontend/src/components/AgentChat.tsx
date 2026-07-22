import { useEffect, useRef } from 'react'

export interface ChatMessage {
  role: 'ai' | 'user'
  text: string
  stage?: string
  status?: string
}

interface Props {
  messages: ChatMessage[]
  running: boolean
  explanation: string
}

function stageIcon(stage?: string, status?: string): string {
  if (stage === 'fix' || stage === 'fixing') return 'fa-screwdriver-wrench'
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
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <aside className="right-panel glass-panel">
      <div className="panel-header">
        <h3>
          <i className="fa-regular fa-comments" /> AI Agent
        </h3>
        <span className={`status-indicator ${running ? 'busy' : 'online'}`} />
      </div>
      <div className="chat-container">
        <div className="chat-messages">
          {messages.map((m, i) => {
            const isAi = m.role === 'ai'
            const statusClass =
              m.status === 'PASS' ? 'ok' : m.status === 'FAIL' || m.status === 'ERROR' || m.stage === 'error' ? 'bad' : ''
            return (
              <div key={i} className={`message ${isAi ? 'ai-msg' : 'user-msg'}`}>
                <div className={`msg-avatar ${isAi ? '' : 'user'}`}>
                  <i className={`fa-solid ${isAi ? stageIcon(m.stage, m.status) : 'fa-user'}`} />
                </div>
                <div className={`msg-bubble ${isAi ? '' : 'user'} ${statusClass}`}>
                  <p>{m.text}</p>
                </div>
              </div>
            )
          })}
          {running && (
            <div className="message ai-msg">
              <div className="msg-avatar">
                <i className="fa-solid fa-circle-notch fa-spin" />
              </div>
              <div className="msg-bubble">
                <p className="muted">Working…</p>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>
        {explanation && (
          <div className="explanation-box">
            <i className="fa-solid fa-circle-info" /> {explanation}
          </div>
        )}
      </div>
    </aside>
  )
}
