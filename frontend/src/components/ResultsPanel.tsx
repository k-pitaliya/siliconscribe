import { useState, useCallback, type KeyboardEvent } from 'react'
import WaveformViewer from './WaveformViewer'
import SchematicView from './SchematicView'
import type { IterationRecord, Schematic, SimulationResult, Waveform, SynthesisInfo, LintInfo } from '../types'

interface Props {
  result: SimulationResult | null
  waveform: Waveform | null
  schematic: Schematic | null
  history: IterationRecord[]
  iterations?: number
  synthesis?: SynthesisInfo | null
  lint?: LintInfo | null
}

type Tab = 'waveform' | 'results' | 'schematic'

const TAB_ORDER: Tab[] = ['results', 'waveform', 'schematic']

export default function ResultsPanel({ result, waveform, schematic, history, iterations, synthesis, lint }: Props) {
  const [tab, setTab] = useState<Tab>('results')

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault()
      const idx = TAB_ORDER.indexOf(tab)
      const dir = e.key === 'ArrowRight' ? 1 : -1
      const next = TAB_ORDER[(idx + dir + TAB_ORDER.length) % TAB_ORDER.length]
      setTab(next)
      // focus the newly active tab button
      const el = document.querySelector<HTMLButtonElement>(`.results-tabs [data-tab="${next}"]`)
      el?.focus()
    }
  }, [tab])

  return (
    <div className="results-pane glass-panel">
      <div className="tabs results-tabs" role="tablist" aria-label="Results view tabs" onKeyDown={handleKeyDown}>
        <button
          role="tab"
          aria-selected={tab === 'results'}
          aria-controls="panel-results"
          id="tab-results"
          data-tab="results"
          className={`tab ${tab === 'results' ? 'active' : ''}`}
          onClick={() => setTab('results')}
          tabIndex={tab === 'results' ? 0 : -1}
        >
          <i className="fa-solid fa-square-check" aria-hidden="true" /> Results
        </button>
        <button
          role="tab"
          aria-selected={tab === 'waveform'}
          aria-controls="panel-waveform"
          id="tab-waveform"
          data-tab="waveform"
          className={`tab ${tab === 'waveform' ? 'active' : ''}`}
          onClick={() => setTab('waveform')}
          tabIndex={tab === 'waveform' ? 0 : -1}
        >
          <i className="fa-solid fa-chart-line" aria-hidden="true" /> Waveform
        </button>
        <button
          role="tab"
          aria-selected={tab === 'schematic'}
          aria-controls="panel-schematic"
          id="tab-schematic"
          data-tab="schematic"
          className={`tab ${tab === 'schematic' ? 'active' : ''}`}
          onClick={() => setTab('schematic')}
          tabIndex={tab === 'schematic' ? 0 : -1}
        >
          <i className="fa-solid fa-diagram-project" aria-hidden="true" /> Schematic
        </button>
      </div>
      <div className="tab-content">
        {tab === 'results' && (
          <div role="tabpanel" id="panel-results" aria-labelledby="tab-results">
            <ResultsView result={result} history={history} iterations={iterations} synthesis={synthesis} lint={lint} />
          </div>
        )}
        {tab === 'waveform' && (
          <div role="tabpanel" id="panel-waveform" aria-labelledby="tab-waveform">
            <WaveformViewer waveform={waveform} />
          </div>
        )}
        {tab === 'schematic' && (
          <div role="tabpanel" id="panel-schematic" aria-labelledby="tab-schematic">
            <SchematicView schematic={schematic} />
          </div>
        )}
      </div>
    </div>
  )
}

function ResultsView({
  result,
  history,
  iterations,
  synthesis,
  lint,
}: {
  result: SimulationResult | null
  history: IterationRecord[]
  iterations?: number
  synthesis?: SynthesisInfo | null
  lint?: LintInfo | null
}) {
  if (!result) return <div className="empty-state">No simulation yet. Generate a design to see results.</div>

  const cov = result.coverage || {}
  const passRate = cov.pass_rate
  let passTone: 'ok' | 'warn' | 'bad' | undefined
  if (passRate != null) {
    if (passRate === 100) passTone = 'ok'
    else if (passRate >= 70) passTone = 'warn'
    else passTone = 'bad'
  }

  // Bug fix: history always includes iteration 0, so hide timeline when only initial iteration
  // Use explicit iterations prop when available; otherwise infer from history max iteration
  const derivedIterations = iterations ?? Math.max(...history.map(h => h.iteration), 0)
  const showTimeline = derivedIterations > 0 && history.length > 1 && history.some(h => h.iteration > 0)

  return (
    <div className="results-view">
      <div className={`status-badge ${result.status.toLowerCase()}`}>
        <i
          className={`fa-solid ${
            result.status === 'PASS' ? 'fa-circle-check' : result.status === 'FAIL' ? 'fa-circle-xmark' : 'fa-triangle-exclamation'
          }`}
          aria-hidden="true"
        />
        {result.status}
      </div>

      <div className="metric-grid">
        <Metric label="Tests" value={String(result.test_count)} />
        <Metric label="Passed" value={String(result.pass_count)} tone="ok" />
        <Metric label="Failed" value={String(result.fail_count)} tone={result.fail_count ? 'bad' : undefined} />
        <Metric label="Pass rate" value={passRate != null ? `${passRate}%` : '—'} tone={passTone} />
      </div>

      {/* Synthesis section */}
      {synthesis && (
        <div className="synthesis-section" data-testid="synthesis-section" style={{
          margin: '1rem 0',
          padding: '0.75rem 0.9rem',
          background: synthesis.available ? 'rgba(99,102,241,0.08)' : 'rgba(255,255,255,0.03)',
          border: '1px solid var(--border-glass)',
          borderLeft: `3px solid ${synthesis.available ? 'var(--accent-primary)' : 'var(--text-muted)'}`,
          borderRadius: 8,
        }}>
          <h4 style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
            <i className="fa-solid fa-microchip" aria-hidden="true" /> Synthesis {synthesis.available ? '(yosys)' : ''}
          </h4>
          {synthesis.available ? (
            <div style={{ fontSize: '0.85rem', lineHeight: 1.5 }}>
              {synthesis.cell_count != null && <div>Cells: <strong>{synthesis.cell_count}</strong></div>}
              {synthesis.area_estimate != null && <div>Area estimate: <strong>{String(synthesis.area_estimate)} µm²</strong></div>}
              {synthesis.cell_count == null && synthesis.area_estimate == null && <div className="muted">Synthesis available — no metrics reported.</div>}
            </div>
          ) : (
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              {synthesis.error ? `Synthesis error: ${synthesis.error}` : 'Synthesis not available (yosys not installed — showing port-level schematic)'}
            </div>
          )}
        </div>
      )}

      {/* Lint section */}
      {lint && (lint.errors.length > 0 || lint.warnings.length > 0) && (
        <div className="lint-section" data-testid="lint-section" style={{
          margin: '1rem 0',
          padding: '0.75rem 0.9rem',
          background: lint.errors.length ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)',
          border: '1px solid var(--border-glass)',
          borderLeft: `3px solid ${lint.errors.length ? 'var(--neg-red)' : 'var(--warn-amber)'}`,
          borderRadius: 8,
        }}>
          <h4 style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: 6 }}>
            <i className="fa-solid fa-magnifying-glass" aria-hidden="true" /> Lint {lint.ok ? '— ok' : `— ${lint.errors.length} error(s), ${lint.warnings.length} warning(s)`}
          </h4>
          {lint.errors.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              {lint.errors.slice(0, 5).map((e, i) => (
                <div key={`e-${i}`} className="error-line">{e.line != null ? `L${e.line}: ` : ''}{e.message}</div>
              ))}
            </div>
          )}
          {lint.warnings.length > 0 && (
            <div>
              {lint.warnings.slice(0, 5).map((w, i) => (
                <div key={`w-${i}`} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: '#fcd34d', padding: '0.15rem 0' }}>
                  {w.line != null ? `L${w.line}: ` : ''}{w.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {showTimeline && (
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

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className="metric">
      <div className={`metric-value ${tone ?? ''}`}>{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  )
}
