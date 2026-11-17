import { useState, useCallback, useEffect, useMemo, type KeyboardEvent } from 'react'
import WaveformViewer, { type WaveformMarker } from './WaveformViewer'
import TestCasesView from './TestCasesView'
import SchematicView from './SchematicView'
import type { IterationRecord, Schematic, SimulationResult, StrengthReport, Waveform, SynthesisInfo, LintInfo } from '../types'

interface Props {
  result: SimulationResult | null
  waveform: Waveform | null
  schematic: Schematic | null
  history: IterationRecord[]
  iterations?: number
  synthesis?: SynthesisInfo | null
  strength?: StrengthReport | null
  lint?: LintInfo | null
  /** True when the shown result came from the built-in demo, not a live model. */
  degraded?: boolean
  /** Set when a PASS rests on too few executed checks. */
  warning?: string
}

type Tab = 'results' | 'tests' | 'waveform' | 'schematic'

const TAB_ORDER: Tab[] = ['results', 'tests', 'waveform', 'schematic']

const TAB_META: Record<Tab, { label: string; icon: string }> = {
  results: { label: 'Results', icon: 'fa-square-check' },
  tests: { label: 'Test cases', icon: 'fa-list-check' },
  waveform: { label: 'Waveform', icon: 'fa-chart-line' },
  schematic: { label: 'Schematic', icon: 'fa-diagram-project' },
}

export default function ResultsPanel({ result, waveform, schematic, history, iterations, synthesis, strength, lint, degraded, warning }: Props) {
  const [tab, setTab] = useState<Tab>('results')
  // The pane is small next to the editor; "Expand" lets a long test list or a waveform use the whole window.
  const [expanded, setExpanded] = useState(false)
  useEffect(() => {
    if (!expanded) return undefined
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') setExpanded(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])
  // Clicking a check in "Test cases" (or a failure flag in the waveform) moves the waveform cursor.
  const [focus, setFocus] = useState<{ t: number; seq: number } | null>(null)

  const failMarkers = useMemo<WaveformMarker[]>(
    () =>
      (result?.checks ?? [])
        .filter((c) => c.status === 'FAIL' && c.t != null)
        .map((c) => ({ t: c.t as number, label: c.name })),
    [result],
  )

  const showInWaveform = useCallback((t: number) => {
    setFocus((prev) => ({ t, seq: (prev?.seq ?? 0) + 1 }))
    setTab('waveform')
  }, [])

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
    <div className={`results-pane glass-panel${expanded ? ' is-expanded' : ''}`}>
      <div className="tabs results-tabs" role="tablist" aria-label="Results view tabs" onKeyDown={handleKeyDown}>
        {TAB_ORDER.map((id) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            {...(tab === id ? { 'aria-controls': `panel-${id}` } : {})}
            id={`tab-${id}`}
            data-tab={id}
            className={`tab ${tab === id ? 'active' : ''}`}
            onClick={() => setTab(id)}
            tabIndex={tab === id ? 0 : -1}
          >
            <i className={`fa-solid ${TAB_META[id].icon}`} aria-hidden="true" /> {TAB_META[id].label}
            {id === 'tests' && result && result.test_count > 0 && (
              <span className="tab-badge" data-testid="tests-badge"> {result.test_count}</span>
            )}
          </button>
        ))}
        <button
          className="tab tab-expand"
          aria-pressed={expanded}
          aria-label={expanded ? 'Restore results pane' : 'Expand results pane'}
          title={expanded ? 'Restore (Esc)' : 'Expand to full window'}
          onClick={() => setExpanded((v) => !v)}
        >
          <i className={`fa-solid ${expanded ? 'fa-compress' : 'fa-expand'}`} aria-hidden="true" />
          {expanded ? ' Restore' : ' Expand'}
        </button>
      </div>
      <div className="tab-content">
        {tab === 'results' && (
          <div role="tabpanel" id="panel-results" aria-labelledby="tab-results">
            <ResultsView result={result} history={history} iterations={iterations} synthesis={synthesis} strength={strength} lint={lint} degraded={degraded} warning={warning} />
          </div>
        )}
        {tab === 'tests' && (
          <div role="tabpanel" id="panel-tests" aria-labelledby="tab-tests">
            {result ? (
              <TestCasesView result={result} timescalePs={waveform?.timescale_ps ?? null} onShowInWaveform={showInWaveform} />
            ) : (
              <div className="empty-state">No simulation yet. Generate a design to see its test cases.</div>
            )}
          </div>
        )}
        {tab === 'waveform' && (
          <div role="tabpanel" id="panel-waveform" aria-labelledby="tab-waveform">
            <WaveformViewer
              waveform={waveform}
              markers={failMarkers}
              focusTime={focus?.t ?? null}
              focusSeq={focus?.seq}
            />
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
  strength,
  lint,
  degraded,
  warning,
}: {
  result: SimulationResult | null
  history: IterationRecord[]
  iterations?: number
  synthesis?: SynthesisInfo | null
  strength?: StrengthReport | null
  lint?: LintInfo | null
  degraded?: boolean
  warning?: string
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

      {degraded && (
        <div className="demo-tag" role="note" data-testid="demo-result-tag">
          <i className="fa-solid fa-triangle-exclamation" aria-hidden="true" />
          Built-in demo result: not generated by the AI model for your prompt
        </div>
      )}
      {warning && (
        <div className="weak-tag" role="note" data-testid="weak-evidence-tag">
          <i className="fa-solid fa-circle-info" aria-hidden="true" /> {warning}
        </div>
      )}

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
              {synthesis.cell_count != null && <div>Generic cells (unmapped): <strong>{synthesis.cell_count}</strong></div>}
              {synthesis.flip_flops != null && (
                <div data-testid="synth-flops">Flip-flops: <strong>{synthesis.flip_flops}</strong> · Latches: <strong>{synthesis.latches ?? 0}</strong></div>
              )}
              {synthesis.cell_types && synthesis.cell_types.length > 0 && (
                <div className="muted" data-testid="synth-types">
                  {synthesis.cell_types.map(([name, n]) => `${name} ×${n}`).join(' · ')}
                </div>
              )}
              {synthesis.latch_warning && (
                <div data-testid="synth-latch" style={{ color: 'var(--warn-amber)' }}>
                  <i className="fa-solid fa-triangle-exclamation" aria-hidden="true" /> {synthesis.latch_warning}
                </div>
              )}
              {synthesis.warnings?.map((w) => (
                <div key={w} className="muted" data-testid="synth-warning">Yosys: {w}</div>
              ))}
              {synthesis.area_estimate != null && (
                <div>Relative area proxy: <strong>{String(synthesis.area_estimate)}</strong> <span className="muted">(cells × 5 — no liberty/tech map, not µm²)</span></div>
              )}
              {synthesis.cell_count == null && synthesis.area_estimate == null && <div className="muted">Synthesis available — no metrics reported.</div>}
            </div>
          ) : (
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              {synthesis.error ? `Synthesis error: ${synthesis.error}` : 'Synthesis not available (yosys not installed — showing port-level schematic)'}
            </div>
          )}
        </div>
      )}

      {/* Testbench strength: did the testbench notice injected bugs? */}
      {strength && (strength.status === 'ok' || strength.status === 'partial') && (
        <div className="strength-section" data-testid="strength-section" style={{
          margin: '1rem 0',
          padding: '0.75rem 0.9rem',
          background: 'rgba(99,102,241,0.08)',
          border: '1px solid var(--border-glass)',
          borderLeft: `3px solid ${strength.killed === strength.total ? 'var(--pos-green)' : 'var(--warn-amber)'}`,
          borderRadius: 8,
        }}>
          <h4 style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
            <i className="fa-solid fa-bug" aria-hidden="true" /> Testbench strength
          </h4>
          <div style={{ fontSize: '0.85rem', lineHeight: 1.5 }}>
            <div data-testid="strength-summary">
              Caught <strong>{strength.killed} of {strength.total}</strong> injected bugs
              {strength.status === 'partial' && <span className="muted"> (stopped early at the time limit)</span>}
            </div>
            {strength.survivors.length > 0 && (
              <div data-testid="strength-survivors" style={{ marginTop: 4 }}>
                <span className="muted">Not noticed by the testbench:</span>
                <ul style={{ margin: '2px 0 0 1.1rem', padding: 0 }}>
                  {strength.survivors.map((s) => (
                    <li key={`${s.line}-${s.description}`} style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
                      line {s.line}: {s.description}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {strength.note && <div className="muted" style={{ marginTop: 4, fontSize: '0.78rem' }}>{strength.note}</div>}
          </div>
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
              {h.diagnosis && (
                <div className="iter-diagnosis" data-testid={`diagnosis-${h.iteration}`}>
                  {h.diagnosis.root_cause && (
                    <div><strong>Root cause:</strong> {h.diagnosis.root_cause}</div>
                  )}
                  {h.diagnosis.symptom && (
                    <div><strong>Symptom:</strong> {h.diagnosis.symptom}</div>
                  )}
                  {h.diagnosis.fix_location && (
                    <div><strong>Fix location:</strong> {h.diagnosis.fix_location}</div>
                  )}
                  {h.diagnosis.confidence && (
                    <div className="muted">Confidence: {h.diagnosis.confidence}</div>
                  )}
                </div>
              )}
              {!h.diagnosis && h.fix_type === 'offline_scripted' && (
                <div className="iter-diagnosis muted" data-testid={`scripted-${h.iteration}`}>
                  Scripted offline fix — no root-cause diagnosis was produced.
                </div>
              )}
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
        <pre className="log-pre">{result.log_excerpt.slice(0, 2500)}{result.log_excerpt.length > 2500 ? '\n… truncated (2500 chars shown)' : ''}</pre>
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
