import { useState } from 'react'
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

  function submit() {
    const text = prompt.trim()
    if (!text) {
      setInvalid(true)
      setTimeout(() => setInvalid(false), 1000)
      return
    }
    onGenerate(text, freq)
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
          <label>
            <i className="fa-solid fa-robot" /> AI Model {!offline && <span className="req">· choose before generating</span>}
          </label>
          {offline ? (
            <div className="model-offline">
              <i className="fa-solid fa-plug-circle-xmark" /> Offline demo — no model selection. Add an API key to enable.
            </div>
          ) : models.length === 0 ? (
            <div className="model-offline">No models available.</div>
          ) : (
            <>
              <select
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
                <div className="model-note">
                  <span className={`model-tag ${activeModel.tag}`}>{activeModel.tag}</span>
                  {activeModel.note}
                </div>
              )}
            </>
          )}
        </div>

        <div className="input-group">
          <label>Natural Language Requirement</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g., Design a 4-bit ALU with add, sub, and, or, xor operations with overflow detection..."
            style={invalid ? { borderColor: 'var(--neg-red)' } : undefined}
          />
        </div>

        <div className="examples">
          <label>Examples</label>
          <div className="example-chips">
            {EXAMPLES.map((ex) => (
              <button key={ex} className="chip" onClick={() => setPrompt(ex)} disabled={running}>
                {ex.replace('Design a ', '').replace('Design ', '')}
              </button>
            ))}
          </div>
        </div>

        <div className="options-group">
          <label>
            Target Frequency <span className="slider-val">{freq} MHz</span>
          </label>
          <input
            type="range"
            min={10}
            max={500}
            value={freq}
            className="slider"
            onChange={(e) => setFreq(Number(e.target.value))}
          />
        </div>

        <button className="btn btn-primary btn-block" onClick={submit} disabled={running}>
          {running ? (
            <>
              <i className="fa-solid fa-circle-notch fa-spin" /> <span>Generating…</span>
            </>
          ) : (
            <>
              <span>Generate RTL</span> <i className="fa-solid fa-arrow-right" />
            </>
          )}
        </button>
      </div>
    </aside>
  )
}
