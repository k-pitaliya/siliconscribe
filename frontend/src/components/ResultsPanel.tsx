import { useState } from 'react'
import WaveformViewer from './WaveformViewer'
import SchematicView from './SchematicView'
import type { IterationRecord, Schematic, SimulationResult, Waveform } from '../types'

interface Props {
  result: SimulationResult | null
  waveform: Waveform | null
  schematic: Schematic | null
  history: IterationRecord[]
}

type Tab = 'waveform' | 'results' | 'schematic'

export default function ResultsPanel({ result, waveform, schematic, history }: Props) {
  const [tab, setTab] = useState<Tab>('results')

  return (
    <div className="results-pane glass-panel">
      <div className="tabs results-tabs">
        <button className={`tab ${tab === 'results' ? 'active' : ''}`} onClick={() => setTab('results')}>
          <i className="fa-solid fa-square-check" /> Results
        </button>
        <button className={`tab ${tab === 'waveform' ? 'active' : ''}`} onClick={() => setTab('waveform')}>
          <i className="fa-solid fa-chart-line" /> Waveform
        </button>
        <button className={`tab ${tab === 'schematic' ? 'active' : ''}`} onClick={() => setTab('schematic')}>
          <i className="fa-solid fa-diagram-project" /> Schematic
        </button>
      </div>
      <div className="tab-content">
        {tab === 'results' && <ResultsView result={result} history={history} />}
        {tab === 'waveform' && <WaveformViewer waveform={waveform} />}
        {tab === 'schematic' && <SchematicView schematic={schematic} />}
      </div>
    </div>
  )
}

function ResultsView({ result, history }: { result: SimulationResult | null; history: IterationRecord[] }) {
  if (!result) return <div className="empty-state">No simulation yet. Generate a design to see results.</div>

  const cov = result.coverage || {}
  return (
    <div className="results-view">
      <div className={`status-badge ${result.status.toLowerCase()}`}>
        <i
          className={`fa-solid ${
            result.status === 'PASS' ? 'fa-circle-check' : result.status === 'FAIL' ? 'fa-circle-xmark' : 'fa-triangle-exclamation'
          }`}
        />
        {result.status}
      </div>

      <div className="metric-grid">
        <Metric label="Tests" value={String(result.test_count)} />
        <Metric label="Passed" value={String(result.pass_count)} tone="ok" />
        <Metric label="Failed" value={String(result.fail_count)} tone={result.fail_count ? 'bad' : undefined} />
        <Metric label="Pass rate" value={cov.pass_rate != null ? `${cov.pass_rate}%` : '—'} />
      </div>

      {history.length > 1 && (
        <div className="iteration-timeline">
          <h4>Self-correction loop</h4>
          {history.map((h) => (
            <div key={h.iteration} className={`iter ${h.status.toLowerCase()}`}>
              <span className="iter-badge">#{h.iteration}</span>
              <span className={`iter-status ${h.status.toLowerCase()}`}>{h.status}</span>
              <span className="iter-summary">{h.fix_summary}</span>
              <span className="iter-counts">
                {h.pass_count}✓ / {h.fail_count}✗
              </span>
            </div>
          ))}
        </div>
      )}

      {result.errors.length > 0 && (
        <div className="error-list">
          <h4>Errors</h4>
          {result.errors.slice(0, 8).map((e, i) => (
            <div key={i} className="error-line">
              {e.line != null ? `L${e.line}: ` : ''}
              {e.message}
            </div>
          ))}
        </div>
      )}

      <details className="log-details" open={result.status !== 'PASS'}>
        <summary>Simulation log</summary>
        <pre className="log-pre">{result.log_excerpt}</pre>
      </details>
    </div>
  )
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'bad' }) {
  return (
    <div className="metric">
      <div className={`metric-value ${tone ?? ''}`}>{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  )
}
