import { useState, type KeyboardEvent, type ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'
import type { ModelInfo } from '../types'

// Short chip label, full prompt that it fills in.
const EXAMPLES: [string, string][] = [
  ['4-bit ALU', 'Design a 4-bit ALU with add, sub, and, or, xor and overflow detection'],
  ['Up-counter', 'Design a 4-bit synchronous up-counter with async reset and enable'],
  ['4:1 mux', 'Design a 4:1 multiplexer with 8-bit data paths'],
  ['Buggy counter', 'Design a buggy 4-bit counter'], // showcases the self-correction loop (scripted in offline mode)
]

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

interface Props {
  onGenerate: (prompt: string, freq: number) => void
  running: boolean
  models: ModelInfo[]
  selectedModel: string
  onModelChange: (id: string) => void
  selectedThinking?: string
  onThinkingChange?: (level: string) => void
  offline: boolean
  /** Rendered right under the prompt (the run timeline), above examples and settings. */
  children?: ReactNode
}

export default function PromptPanel({
  onGenerate, running, models, selectedModel, onModelChange, selectedThinking, onThinkingChange, offline, children,
}: Props) {
  const [prompt, setPrompt] = useState('')
  const [freq, setFreq] = useState(100)
  const [invalid, setInvalid] = useState(false)
  const activeModel = models.find((m) => m.id === selectedModel)
  const tooLong = prompt.length > 2000

  function clampFreq(v: number): number {
    // the slider is 10–500 but the backend accepts 1–10000; clamp to keep that contract
    if (!Number.isFinite(v)) return 100
    return Math.min(10000, Math.max(1, Math.round(v)))
  }

  function submit() {
    const text = prompt.trim()
    if (!text || text.length > 2000) {
      setInvalid(true)
      if (!text) setTimeout(() => setInvalid(false), 1500)
      return
    }
    const safeFreq = clampFreq(freq)
    if (safeFreq !== freq) setFreq(safeFreq)
    onGenerate(text, safeFreq)
  }

  function handleTextareaKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      if (!running) submit()
    }
  }

  const levels = activeModel?.thinking_levels ?? []
  const defaultLevel = levels[Math.floor(levels.length / 2)] || levels[0]

  return (
    <>
      <div className="side-section">
        <h2 className="side-title"><label htmlFor="prompt-textarea">Describe the block</label></h2>
        <textarea
          id="prompt-textarea"
          aria-required="true"
          aria-invalid={invalid || tooLong}
          aria-describedby={invalid || tooLong ? 'prompt-error' : 'prompt-meta'}
          value={prompt}
          maxLength={2000}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleTextareaKey}
          placeholder="e.g., a 4-bit ALU with add, sub, and, or, xor and an overflow flag"
          style={invalid || tooLong ? { borderColor: 'var(--fail)' } : undefined}
        />
        {tooLong ? (
          <div id="prompt-error" role="alert" className="field-error">Too long: keep it under 2000 characters ({prompt.length}/2000).</div>
        ) : invalid ? (
          <div id="prompt-error" role="alert" className="field-error">Describe the block first, for example its inputs, outputs and behaviour.</div>
        ) : null}
        <div id="prompt-meta" className={`prompt-meta ${prompt.length > 1800 ? 'over' : ''}`}>
          <span>{prompt.length}/2000</span>
          <span><kbd>{IS_MAC ? '⌘' : 'Ctrl'}</kbd> <kbd>Enter</kbd> to generate</span>
        </div>
        <div className="generate-row">
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={running}
            aria-label={running ? 'Generating RTL, please wait' : 'Generate RTL from the description'}
            aria-busy={running}
          >
            {running ? (<><LoaderCircle size={16} className="spin" aria-hidden="true" /> <span>Generating…</span></>) : <span>Generate RTL</span>}
          </button>
        </div>
      </div>

      {children}

      <div className="side-section">
        <div className="field-label" id="examples-label">Examples</div>
        <div className="example-chips" role="group" aria-labelledby="examples-label">
          {EXAMPLES.map(([label, ex]) => (
            <button key={label} className="chip" aria-label={`${label}: ${ex}`} title={ex} onClick={() => setPrompt(ex)} disabled={running}>
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="side-section settings-grid">
        <div>
          <label className="field-label" htmlFor="model-select" id="model-select-label">Model</label>
          {offline ? (
            <div className="model-offline" role="status" aria-live="polite">
              Offline demo: scripted designs, no AI model. Configure a provider to generate live.
            </div>
          ) : models.length === 0 ? (
            <div className="model-offline" role="status">No models available.</div>
          ) : (
            <>
              <select id="model-select" value={selectedModel} onChange={(e) => onModelChange(e.target.value)} disabled={running}>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
              {activeModel?.note && <div className="model-note" aria-live="polite">{activeModel.note}</div>}
            </>
          )}
        </div>

        {!offline && levels.length > 0 && onThinkingChange && (
          <div>
            <label className="field-label" htmlFor="thinking-select">Thinking level</label>
            <select id="thinking-select" value={selectedThinking || defaultLevel} onChange={(e) => onThinkingChange(e.target.value)} disabled={running}>
              {levels.map((lvl) => (
                <option key={lvl} value={lvl}>{lvl}</option>
              ))}
            </select>
            <div className="thinking-hint">Sent to the model as its reasoning effort.</div>
          </div>
        )}

        <div>
          <div className="freq-row">
            <label className="field-label" htmlFor="freq-slider">Target clock</label>
            <output htmlFor="freq-slider" aria-live="polite">{freq} MHz</output>
          </div>
          <input
            id="freq-slider"
            aria-label="Target clock in MHz, 10 to 500"
            type="range"
            min={10}
            max={500}
            value={freq}
            className="slider"
            onChange={(e) => setFreq(clampFreq(Number(e.target.value)))}
          />
        </div>
      </div>
    </>
  )
}
