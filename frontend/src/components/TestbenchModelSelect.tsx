import type { ModelInfo } from '../types'

interface Props {
  models: ModelInfo[]
  value: string
  onChange: (id: string) => void
  disabled?: boolean
}

export default function TestbenchModelSelect({ models, value, onChange, disabled = false }: Props) {
  // Distinct groups in order of first appearance.
  const groups: string[] = []
  for (const m of models) {
    const g = m.group ?? 'Models'
    if (!groups.includes(g)) groups.push(g)
  }

  return (
    <div className="testbench-model">
      <label className="field-label" htmlFor="tb-model-select">Testbench written by</label>
      <select
        id="tb-model-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        <option value="">Same model as the design</option>
        {groups.map((g) => (
          <optgroup key={g} label={g}>
            {models
              .filter((m) => (m.group ?? 'Models') === g)
              .map((m) => (
                <option key={m.id} value={m.id} title={m.id}>
                  {`${m.label}${m.free ? ' (free)' : ''}`}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <div className="model-note">
        {value
          ? 'A separate model writes the testbench, so a failing check cannot be rewritten away by the design model.'
          : 'The same model writes the design and its testbench. Pick another to make the check independent.'}
      </div>
    </div>
  )
}
