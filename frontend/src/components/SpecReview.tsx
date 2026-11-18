import { useState } from 'react'
import type { RTLDesignSpec } from '../types'

const MAX_BEHAVIOR = 4000 // the server's limit: a longer text would be refused after the user pressed the button
const MAX_CONSTRAINTS = 30
const MAX_CONSTRAINT_LENGTH = 500

function parseConstraints(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.slice(0, MAX_CONSTRAINT_LENGTH))
    .slice(0, MAX_CONSTRAINTS)
}

interface Props {
  spec: RTLDesignSpec
  onConfirm: (spec: RTLDesignSpec) => void
  onCancel: () => void
  busy?: boolean
}

export default function SpecReview({ spec, onConfirm, onCancel, busy = false }: Props) {
  const [behavior, setBehavior] = useState(spec.behavior ?? '')
  const [constraints, setConstraints] = useState((spec.constraints ?? []).join('\n'))
  const ports = spec.ports ?? []
  const parameters = spec.parameters ?? []

  function confirm() {
    onConfirm({
      ...spec,
      behavior: behavior.slice(0, MAX_BEHAVIOR),
      constraints: parseConstraints(constraints),
    })
  }

  return (
    <section className="spec-review" aria-label="Review the specification">
      <h2>Review the specification</h2>
      <p>The design and its testbench are both written from this. Fix anything that does not match what you meant.</p>

      <div>Module <span className="mono">{spec.module_name}</span></div>

      <table>
        <caption>Ports</caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Direction</th>
            <th scope="col">Width</th>
            <th scope="col">Description</th>
          </tr>
        </thead>
        <tbody>
          {ports.map((p) => (
            <tr key={p.name}>
              <td className="mono">{p.name}</td>
              <td>{p.direction}</td>
              <td>{p.width}</td>
              <td>{p.description}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {parameters.length > 0 && (
        <div>
          <div className="field-label">Parameters</div>
          <ul>
            {parameters.map((p) => (
              <li key={p.name} className="mono">{`${p.name} = ${p.default}`}</li>
            ))}
          </ul>
        </div>
      )}

      <label className="field-label" htmlFor="spec-behavior">Behaviour</label>
      <textarea
        id="spec-behavior"
        rows={12}
        maxLength={MAX_BEHAVIOR}
        value={behavior}
        onChange={(e) => setBehavior(e.target.value)}
        disabled={busy}
      />

      <label className="field-label" htmlFor="spec-constraints">Constraints (one per line)</label>
      <textarea
        id="spec-constraints"
        rows={8}
        value={constraints}
        onChange={(e) => setConstraints(e.target.value)}
        disabled={busy}
      />

      <div>
        <button type="button" className="btn btn-primary" onClick={confirm} disabled={busy}>
          Generate with this specification
        </button>{' '}
        <button type="button" className="btn btn-ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </section>
  )
}
