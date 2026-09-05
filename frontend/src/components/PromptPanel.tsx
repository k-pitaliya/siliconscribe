import { useState, type KeyboardEvent } from 'react'
import type { ModelInfo } from '../types'

const EXAMPLES = [
  'Design a 4-bit ALU with add, sub, and, or, xor and overflow detection',
  'Design a 4-bit synchronous up-counter with async reset and enable',
  'Design a 4:1 multiplexer with 8-bit data paths',
  'Design a buggy 4-bit counter', // showcases the self-correction loop
]

interface Props {
  onGenerate: (prompt: string, freq: number) => void
  running: boolean
  models: ModelInfo[]
  selectedModel: string
  onModelChange: (id: string) => void
  offline: boolean
}

export default function PromptPanel({
  onGenerate,
  running,
  models,
  selectedModel,
  onModelChange,
  offline,
}: Props) {
  const [prompt, setPrompt] = useState('')
  const [freq, setFreq] = useState(100)
  const [invalid, setInvalid] = useState(false)

  const activeModel = models.find((m) => m.id === selectedModel)

  function clampFreq(v: number): number {
    // slider is 10–500 but backend allows 1–10000; validate/clamp to keep contract
    if (!Number.isFinite(v)) return 100
    return Math.min(10000, Math.max(1, Math.round(v)))
  }

  function submit() {
    const text = prompt.trim()
    if (!text) {
      setInvalid(true)
      setTimeout(() => setInvalid(false), 1000)
      return
    }
    if (text.length > 2000) {
      setInvalid(true)
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

  return (
    <aside className="left-panel glass-panel">
      <div className="panel-header">
        <h3>
          <i className="fa-solid fa-wand-magic-sparkles" /> Design Prompt
        </h3>
      </div>
      <div className="panel-content">
        <div className="session-group">
          <label htmlFor="model-select" id="model-select-label">
            <i className="fa-solid fa-robot" /> AI Model {!offline && <span className="req">· choose before generating</span>}
          </label>
          {offline ? (
            <div className="model-offline" role="status" aria-live="polite">
              <i className="fa-solid fa-plug-circle-xmark" /> Offline demo — no model selection. Add an API key to enable.
            </div>
          ) : models.length === 0 ? (
            <div className="model-offline" role="status">No models available.</div>
          ) : (
            <>
              <select
                id="model-select"
                aria-labelledby="model-select-label"
                aria-label="AI Model selection"
                className="model-select"
                value={selectedModel}
                onChange={(e) => onModelChange(e.target.value)}
                disabled={running}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              {activeModel && (
                <div className="model-note" aria-live="polite">
                  <span className={`model-tag ${activeModel.tag}`}>{activeModel.tag}</span>
                  {activeModel.note}
                </div>
              )}
            </>
          )}
        </div>

        <div className="input-group">
          <label htmlFor="prompt-textarea">Natural Language Requirement</label>
          <textarea
            id="prompt-textarea"
            aria-label="Natural Language Requirement"
            aria-required="true"
            aria-invalid={invalid}
            aria-describedby={invalid ? 'prompt-error' : prompt.length > 2000 ? 'prompt-error' : undefined}
            value={prompt}
            maxLength={2000}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleTextareaKey}
            placeholder="e.g., Design a 4-bit ALU with add, sub, and, or, xor operations with overflow detection..."
            style={invalid || prompt.length > 2000 ? { borderColor: 'var(--neg-red)' } : undefined}
          />
          {prompt.length > 2000 ? (
            <span id="prompt-error" role="alert" style={{ color: 'var(--neg-red)', fontSize: '0.78rem', marginTop: 4, display: 'block' }}>
              Prompt too long — max 2000 characters ({prompt.length}/2000).
            </span>
          ) : invalid ? (
            <span id="prompt-error" role="alert" style={{ color: 'var(--neg-red)', fontSize: '0.78rem', marginTop: 4, display: 'block' }}>
              Please enter a design prompt.
            </span>
          ) : null}
          <span style={{ fontSize: '0.7rem', color: prompt.length > 1800 ? 'var(--warn-amber)' : 'var(--text-muted)', marginTop: 4, display: 'block' }}>
            {prompt.length}/2000 · Tip: Press <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to generate
          </span>
        </div>

        <div className="examples">
          <label id="examples-label">Examples</label>
          <div className="example-chips" role="group" aria-labelledby="examples-label">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                className="chip"
                aria-label={`Use example: ${ex}`}
                onClick={() => setPrompt(ex)}
                disabled={running}
              >
                {ex.replace('Design a ', '').replace('Design ', '')}
              </button>
            ))}
          </div>
        </div>

        <div className="options-group">
          <label htmlFor="freq-slider">
            Target Frequency <span className="slider-val" aria-live="polite">{freq} MHz</span>
          </label>
          <input
            id="freq-slider"
            aria-label="Target frequency in MHz, 10 to 500"
            type="range"
            min={10}
            max={500}
            value={freq}
            className="slider"
            onChange={(e) => setFreq(clampFreq(Number(e.target.value)))}
          />
        </div>

        <button
          className="btn btn-primary btn-block"
          onClick={submit}
          disabled={running}
          aria-label={running ? 'Generating RTL, please wait' : 'Generate RTL from prompt, Ctrl Enter'}
          aria-busy={running}
        >
          {running ? (
            <>
              <i className="fa-solid fa-circle-notch fa-spin" aria-hidden="true" /> <span>Generating…</span>
            </>
          ) : (
            <>
              <span>Generate RTL</span> <i className="fa-solid fa-arrow-right" aria-hidden="true" />
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
