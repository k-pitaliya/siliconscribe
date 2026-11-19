import SpecSummary from './SpecSummary'
import { useState, useCallback, useEffect, useMemo, type KeyboardEvent, type ReactNode } from 'react'
import { Activity, ArrowUpDown, Timer, Bug, CircleCheck, CircleX, Cpu, FileCode, Info, ListChecks, Search, TriangleExclamationPoint, Workflow , ShieldCheck } from 'lucide-react'
import WaveformViewer, { type WaveformMarker } from './WaveformViewer'
import TestCasesView from './TestCasesView'
import SchematicView from './SchematicView'
import type { CriticalPathRow, RTLDesignSpec, SecondOpinion, IterationRecord, Schematic, SimulationResult, StrengthReport, TimingReport, UntoggledSignal, Waveform, SynthesisInfo, LintInfo } from '../types'

export type Tab = 'design' | 'results' | 'tests' | 'waveform' | 'schematic'

interface Props {
  result: SimulationResult | null
  waveform: Waveform | null
  schematic: Schematic | null
  history: IterationRecord[]
  iterations?: number
  synthesis?: SynthesisInfo | null
  strength?: StrengthReport | null
  timing?: TimingReport | null
  /** The model that wrote the design, so a result is never attributed to the wrong one after switching models. */
  model?: string | null
  /** The separate model that wrote the testbench, when there was one. */
  testbenchModel?: string | null
  /** A fresh testbench's verdict after a repair rewrote the first one. */
  secondOpinion?: SecondOpinion | null
  /** The specification the design was built from. */
  spec?: RTLDesignSpec | null
  lint?: LintInfo | null
  /** True when the shown result came from the built-in demo, not a live model. */
  degraded?: boolean
  /** Set when a PASS rests on too few executed checks. */
  warning?: string
  disputed?: string
  /** The code editor, shown in the Design tab. Without it the workspace has no Design tab. */
  design?: ReactNode
  /** Ask the workspace to show a tab (the seq makes a repeated request count). */
  tabRequest?: { tab: Tab; seq: number } | null
  /** Told whenever the visible tab changes. */
  onTabChange?: (tab: Tab) => void
}

const TAB_META: Record<Tab, { label: string; Icon: typeof Activity }> = {
  design: { label: 'Design', Icon: FileCode },
  results: { label: 'Results', Icon: CircleCheck },
  tests: { label: 'Test cases', Icon: ListChecks },
  waveform: { label: 'Waveform', Icon: Activity },
  schematic: { label: 'Schematic', Icon: Workflow },
}

export default function ResultsPanel({
  result, waveform, schematic, history, iterations, synthesis, strength, timing, model, testbenchModel, secondOpinion, spec, lint, degraded, warning, disputed, design, tabRequest, onTabChange,
}: Props) {
  // Depend on whether there IS a design tab, not on the element itself: the element is new on every
  // render, and re-running the request effect each render would override the user's own tab clicks.
  const hasDesign = design != null
  const order = useMemo<Tab[]>(
    () => (hasDesign ? ['design', 'results', 'tests', 'waveform', 'schematic'] : ['results', 'tests', 'waveform', 'schematic']),
    [hasDesign],
  )
  const [tab, setTab] = useState<Tab>(hasDesign ? 'design' : 'results')
  useEffect(() => {
    // Apply each request exactly once (its seq changes per request).
    if (tabRequest && (hasDesign || tabRequest.tab !== 'design')) setTab(tabRequest.tab)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabRequest])
  useEffect(() => {
    onTabChange?.(tab)
  }, [tab, onTabChange])

  // Clicking a check in "Test cases" (or a failure flag in the waveform) moves the waveform cursor.
  const [focus, setFocus] = useState<{ t: number; seq: number } | null>(null)
  // A cursor placed on one run's waveform must not reappear on the next run's (self-review finding).
  useEffect(() => { setFocus(null) }, [result, waveform])
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
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const idx = order.indexOf(tab)
    const next = order[(idx + (e.key === 'ArrowRight' ? 1 : -1) + order.length) % order.length]
    setTab(next)
    document.querySelector<HTMLButtonElement>(`.results-tabs [data-tab="${next}"]`)?.focus()
  }, [tab, order])

  return (
    <main className="main-pane results-pane" aria-label="Workspace">
      <div className="tabs results-tabs">
        <div className="tablist" role="tablist" aria-label="Workspace views" onKeyDown={handleKeyDown}>
          {order.map((id) => {
            const { label, Icon } = TAB_META[id]
            return (
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
                <Icon size={15} aria-hidden="true" /> {label}
                {id === 'tests' && result && result.test_count > 0 && (
                  <span className="tab-badge" data-testid="tests-badge"> {result.test_count}</span>
                )}
              </button>
            )
          })}
        </div>
      </div>
      <div className="tab-content">
        {tab === 'design' && (
          <div className="tab-panel" role="tabpanel" id="panel-design" aria-labelledby="tab-design">{design}</div>
        )}
        {tab === 'results' && (
          <div className="tab-panel padded" role="tabpanel" id="panel-results" aria-labelledby="tab-results">
            <ResultsView result={result} history={history} iterations={iterations} synthesis={synthesis} strength={strength} timing={timing}
              model={model} testbenchModel={testbenchModel} secondOpinion={secondOpinion} spec={spec} lint={lint} degraded={degraded} warning={warning} disputed={disputed} onOpenTests={() => setTab('tests')} />
          </div>
        )}
        {tab === 'tests' && (
          <div className="tab-panel" role="tabpanel" id="panel-tests" aria-labelledby="tab-tests">
            {result ? (
              <TestCasesView result={result} timescalePs={waveform?.timescale_ps ?? null} onShowInWaveform={showInWaveform} />
            ) : (
              <div className="empty-state">No simulation yet. Generate a design to see its test cases.</div>
            )}
          </div>
        )}
        {tab === 'waveform' && (
          <div className="tab-panel" role="tabpanel" id="panel-waveform" aria-labelledby="tab-waveform">
            <WaveformViewer waveform={waveform} markers={failMarkers} focusTime={focus?.t ?? null} focusSeq={focus?.seq} />
          </div>
        )}
        {tab === 'schematic' && (
          <div className="tab-panel" role="tabpanel" id="panel-schematic" aria-labelledby="tab-schematic">
            <SchematicView schematic={schematic} synthesis={synthesis} />
          </div>
        )}
      </div>
    </main>
  )
}

function ResultsView({
  result, history, iterations, synthesis, strength, timing, model, testbenchModel, secondOpinion, spec, lint, degraded, warning, disputed, onOpenTests,
}: {
  result: SimulationResult | null
  history: IterationRecord[]
  iterations?: number
  synthesis?: SynthesisInfo | null
  strength?: StrengthReport | null
  timing?: TimingReport | null
  model?: string | null
  testbenchModel?: string | null
  secondOpinion?: SecondOpinion | null
  spec?: RTLDesignSpec | null
  lint?: LintInfo | null
  degraded?: boolean
  warning?: string
  disputed?: string
  onOpenTests?: () => void
}) {
  if (!result) return <div className="empty-state">No simulation yet. Generate a design to see results.</div>

  const passRate = (result.coverage || {}).pass_rate
  let passTone: 'ok' | 'warn' | 'bad' | undefined
  if (passRate != null) passTone = passRate === 100 ? 'ok' : passRate >= 70 ? 'warn' : 'bad'

  // History always includes iteration 0, so only show the loop when a repair actually happened.
  const derivedIterations = iterations ?? Math.max(...history.map((h) => h.iteration), 0)
  const showTimeline = derivedIterations > 0 && history.length > 1 && history.some((h) => h.iteration > 0)
  const StatusIcon = result.status === 'PASS' ? CircleCheck : result.status === 'FAIL' ? CircleX : TriangleExclamationPoint
  const groups = result.check_groups ?? []
  const strengthShown = strength && (strength.status === 'ok' || strength.status === 'partial')
  const toggle = result.measured_toggle
  const timingShown = !!timing && timing.available
  const mappedArea = timingShown && timing?.area_um2 != null
  const compiled = result.status === 'PASS' || result.status === 'FAIL'

  return (
    <div className="results-view">
      {/* A built-in demo result is labelled BEFORE the verdict, so it is never read as a live result. */}
      {(degraded || model === 'offline demo') && (
        <div className="notice demo-tag" role="note" data-testid="demo-result-tag">
          <TriangleExclamationPoint size={16} aria-hidden="true" />
          Built-in demo result: not generated by the AI model for your prompt
        </div>
      )}
      {/* The one bold element on the page: the verdict and the four numbers that matter. */}
      <div className={`verdict ${disputed && result.status === 'PASS' ? 'disputed' : ''}`}>
        <div className={`status-badge ${disputed && result.status === 'PASS' ? 'disputed' : result.status.toLowerCase()}`} data-testid="verdict-badge">
          <StatusIcon size={28} aria-hidden="true" />
          {disputed && result.status === 'PASS' ? 'PASS, disputed' : result.status}
        </div>
        <Metric label="Checks" value={String(result.test_count)} />
        <Metric label="Passed" value={String(result.pass_count)} tone="ok" />
        <Metric label="Failed" value={String(result.fail_count)} tone={result.fail_count ? 'bad' : undefined} />
        <Metric label="Pass rate" value={passRate != null ? `${passRate}%` : '—'} tone={passTone} />
      </div>
      {disputed && result.status === 'PASS' && (
        <div className="notice caution critical" role="alert" data-testid="disputed-tag">
          <TriangleExclamationPoint size={16} aria-hidden="true" />
          <span><strong>Do not trust this PASS yet.</strong> {disputed} The testbench was changed during repair; see the notes below.</span>
        </div>
      )}
      {warning && (
        <div className="notice weak-tag caution" role="note" data-testid="weak-evidence-tag">
          <Info size={16} aria-hidden="true" /> {warning}
        </div>
      )}
      {secondOpinion && (
        <div className={`notice second-opinion ${secondOpinion.status === 'FAIL' ? 'weak-tag' : ''}`} role="note" data-testid="second-opinion">
          <ShieldCheck size={16} aria-hidden="true" />{' '}
          {secondOpinion.status === 'PASS' && <>Second opinion agrees: a fresh testbench, written from the same specification, passes all {secondOpinion.pass_count} of {secondOpinion.test_count} checks.</>}
          {secondOpinion.status === 'FAIL' && <>Second opinion disagrees: a fresh testbench, written from the same specification, fails {secondOpinion.fail_count} of {secondOpinion.test_count} checks.</>}
          {secondOpinion.status !== 'PASS' && secondOpinion.status !== 'FAIL' && <>Second opinion not obtained: {secondOpinion.note}</>}
        </div>
      )}
      {model && model !== 'offline demo' && (
        <div className="model-used muted" data-testid="model-used">
          Design written by <span className="mono">{model}</span>
          {testbenchModel ? <>. Testbench written by <span className="mono">{testbenchModel}</span>, a separate model</> : <>, which also wrote the testbench</>}
        </div>
      )}

      {(strengthShown || synthesis || toggle || timingShown) && (
        <div className="two-col">
          {strengthShown && strength && (
            <div className="section strength-section" data-testid="strength-section">
              <h3><Bug size={16} aria-hidden="true" /> Testbench strength</h3>
              <div className="section-body">
                <div data-testid="strength-summary">
                  Caught <strong>{strength.killed} of {strength.total}</strong> injected bugs
                  {strength.status === 'partial' && <span className="muted"> (stopped early at the time limit)</span>}
                </div>
                {/* Same threshold as the backend's weak-testbench warning: amber only when under half were caught. */}
                <div className={`bar ${strength.total && strength.killed / strength.total < 0.5 ? 'weak' : ''}`} aria-hidden="true">
                  <span style={{ width: `${strength.total ? (100 * strength.killed) / strength.total : 0}%` }} />
                </div>
                {strength.survivors.length > 0 && (
                  <div data-testid="strength-survivors">
                    <span className="muted">Not noticed by the testbench:</span>
                    <ul className="survivors">
                      {strength.survivors.map((s) => (
                        <li key={`${s.line}-${s.description}`}>line {s.line}: {s.description}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {strength.note && <div className="muted">{strength.note}</div>}
              </div>
            </div>
          )}
          {synthesis && (
            <div className="section synthesis-section" data-testid="synthesis-section">
              <h3><Cpu size={16} aria-hidden="true" /> Synthesis {synthesis.available ? '(yosys)' : ''}</h3>
              {synthesis.available ? (
                <div className="section-body">
                  {synthesis.cell_count != null && <div>Generic cells (unmapped): <strong>{synthesis.cell_count}</strong></div>}
                  {synthesis.flip_flops != null && (
                    <div data-testid="synth-flops">Flip-flops: <strong>{synthesis.flip_flops}</strong>, latches: <strong>{synthesis.latches ?? 0}</strong></div>
                  )}
                  {synthesis.cell_types && synthesis.cell_types.length > 0 && (
                    <div className="muted mono" data-testid="synth-types">
                      {synthesis.cell_types.map(([name, n]) => `${name} ×${n}`).join(', ')}
                    </div>
                  )}
                  {synthesis.latch_warning && (
                    <div data-testid="synth-latch" style={{ color: 'var(--warn)' }}>
                      <TriangleExclamationPoint size={14} aria-hidden="true" style={{ verticalAlign: '-2px' }} /> {synthesis.latch_warning}
                    </div>
                  )}
                  {synthesis.warnings?.map((w) => (
                    <div key={w} className="muted" data-testid="synth-warning">Yosys: {w}</div>
                  ))}
                  {synthesis.area_estimate != null && !mappedArea && (
                    <div>Relative area proxy: <strong>{String(synthesis.area_estimate)}</strong> <span className="muted">(cells × 5, no technology library, not µm²)</span></div>
                  )}
                  {synthesis.cell_count == null && synthesis.area_estimate == null && <div className="muted">Synthesis ran but reported no metrics.</div>}
                </div>
              ) : (
                <div className="section-body muted">
                  {synthesis.error ? `Synthesis error: ${synthesis.error}` : 'Synthesis not available: Yosys is not installed, so only the port-level schematic is shown.'}
                </div>
              )}
            </div>
          )}
          {timingShown && timing && (
            <div className="section timing-section" data-testid="timing-section">
              <h3><Timer size={16} aria-hidden="true" /> Timing and area (pre-layout)</h3>
              <div className="section-body">
                {timing.slack_ns != null ? (
                  timing.clock?.startsWith('virtual') ? (
                    // No clock in the design: the honest question is "how long is the slowest input-to-output path?"
                    <div data-testid="timing-summary" style={timing.met ? undefined : { color: 'var(--fail)' }}>
                      <strong>Longest input-to-output path: {(timing.period_ns - timing.slack_ns).toFixed(2)} ns.</strong>
                      {' '}{timing.met
                        ? `It fits the ${timing.period_ns} ns budget (${timing.target_mhz} MHz) with ${timing.slack_ns.toFixed(2)} ns to spare.`
                        : `It is ${(-timing.slack_ns).toFixed(2)} ns over the ${timing.period_ns} ns budget (${timing.target_mhz} MHz).`}
                      <span className="muted"> This design has no clock.</span>
                    </div>
                  ) : (
                    <div data-testid="timing-summary" style={timing.met ? undefined : { color: 'var(--fail)' }}>
                      <strong>{timing.met ? 'Meets' : 'Misses'} {timing.target_mhz} MHz</strong>
                      {' '}with {timing.slack_ns >= 0 ? '+' : ''}{timing.slack_ns.toFixed(2)} ns slack
                      {timing.fmax_mhz != null && <span className="muted"> (maximum about {Math.round(timing.fmax_mhz)} MHz)</span>}
                    </div>
                  )
                ) : (
                  <div data-testid="timing-summary" className="muted">{timing.error ?? 'No timing result.'}</div>
                )}
                {timing.critical_start && timing.critical_end && (
                  <div>Slowest path: <span className="mono">{timing.critical_start}</span> to <span className="mono">{timing.critical_end}</span>
                    {timing.critical_delay_ns != null && <>, {timing.critical_delay_ns.toFixed(2)} ns</>}</div>
                )}
                {/* Shown whenever the proof ran or was skipped: a timeout or a size skip must be visible, not silent. */}
                {(timing.equivalence || timing.equivalence_method) && <EquivalenceLine status={timing.equivalence ?? null} method={timing.equivalence_method ?? ''} />}
                {timing.critical_path && timing.critical_path.length > 1 && (
                  <CriticalPath rows={timing.critical_path} total={timing.critical_delay_ns ?? null} truncated={!!timing.critical_path_truncated} />)}
                {timing.area_um2 != null && (
                  <div data-testid="timing-area">Mapped area: <strong>{timing.area_um2.toFixed(1)} µm²</strong> in {timing.cell_count} cells
                    {timing.flip_flops ? `, ${timing.flip_flops} flip-flops` : ''}</div>
                )}
                {timing.cells.length > 0 && (
                  <div className="muted mono">{timing.cells.map(([n, c]) => `${n} ×${c}`).join(', ')}</div>
                )}
                <div className="muted">{timing.library}. {timing.note}</div>
              </div>
            </div>
          )}
          {toggle && (
            <div className="section toggle-section" data-testid="toggle-section">
              <h3><ArrowUpDown size={16} aria-hidden="true" /> Toggle coverage (measured)</h3>
              <div className="section-body">
                <div data-testid="toggle-summary">
                  <strong>{toggle.percent}%</strong> of design signal bits switched both ways
                  <span className="muted"> ({toggle.bits_toggled} of {toggle.bits_total} bits, {toggle.signals} signals)</span>
                </div>
                <div className={`bar ${toggle.percent < 50 ? 'weak' : ''}`} aria-hidden="true">
                  <span style={{ width: `${toggle.percent}%` }} />
                </div>
                {toggle.untoggled.length > 0 && (
                  <div data-testid="toggle-untoggled">
                    <span className="muted">Never switched:</span>
                    <ul className="survivors">
                      {toggle.untoggled.map((u) => (
                        <li key={u.signal}>{describeUntoggled(u)}</li>
                      ))}
                      {toggle.untoggled_more > 0 && <li>and {toggle.untoggled_more} more signal(s)</li>}
                    </ul>
                  </div>
                )}
                <div className="muted">
                  Read from the simulator's waveform file, not reported by the testbench.
                  {toggle.partial ? ' The waveform was cut at the size limit, so this is a lower bound.' : ''}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {groups.length > 0 && (
        <div className="section">
          <h3><ListChecks size={16} aria-hidden="true" /> Test types</h3>
          <div className="type-chips">
            {groups.map((g) => (
              <span key={g.category} className={`type-chip ${g.failed ? 'has-fail' : ''}`}>
                {g.category.replace(/_/g, ' ')}<b>{g.passed}/{g.total}</b>
              </span>
            ))}
            {onOpenTests && (
              <button className="link-btn" onClick={onOpenTests}>Open test cases</button>
            )}
          </div>
        </div>
      )}

      {spec && <SpecSummary spec={spec} />}

      {lint && (lint.errors.length > 0 || lint.warnings.length > 0) && (
        <div className="section lint-section" data-testid="lint-section">
          {/* When the simulator compiled and ran the code, lint findings are advice, not "the Verilog has errors"
              (self-review UX finding: 16 red "errors" sat next to a design that ran 108 checks). */}
          <h3><Search size={16} aria-hidden="true" /> {compiled ? 'Lint (advisory: the simulator compiled and ran this code)' : 'Lint'}{' '}
            {lint.ok ? '(no errors)' : `(${lint.errors.length} finding(s), ${lint.warnings.length} warning(s))`}</h3>
          {lint.errors.slice(0, 5).map((e, i) => (
            <div key={`e-${i}`} className={compiled ? 'lint-warn' : 'error-line'}>
              {e.file ? `${e.file.split('/').pop()} ` : ''}{e.line != null ? `L${e.line}: ` : ''}{e.message}
            </div>
          ))}
          {lint.warnings.slice(0, 5).map((w, i) => (
            <div key={`w-${i}`} className="lint-warn">{w.line != null ? `L${w.line}: ` : ''}{w.message}</div>
          ))}
        </div>
      )}

      {showTimeline && (
        <div className="section iteration-timeline">
          <h3>Self-correction loop</h3>
          {history.map((h) => (
            <div key={h.iteration} className={`iter ${h.status.toLowerCase()}`}>
              <span className="iter-badge">#{h.iteration}</span>
              <span className={`iter-status ${h.status.toLowerCase()}`}>{h.status}</span>
              <span className="iter-summary">{h.fix_summary}</span>
              <span className="iter-counts">{h.pass_count}✓ / {h.fail_count}✗</span>
              {h.diagnosis && (
                <div className="iter-diagnosis" data-testid={`diagnosis-${h.iteration}`}>
                  {h.diagnosis.root_cause && <div><strong>Root cause:</strong> {h.diagnosis.root_cause}</div>}
                  {h.diagnosis.symptom && <div><strong>Symptom:</strong> {h.diagnosis.symptom}</div>}
                  {h.diagnosis.fix_location && <div><strong>Fix location:</strong> {h.diagnosis.fix_location}</div>}
                  {h.diagnosis.confidence && <div className="muted">Confidence: {h.diagnosis.confidence}</div>}
                </div>
              )}
              {!h.diagnosis && h.fix_type === 'offline_scripted' && (
                <div className="iter-diagnosis muted" data-testid={`scripted-${h.iteration}`}>
                  Scripted offline fix: no root-cause diagnosis was produced.
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {result.errors.length > 0 && (
        <div className="section error-list">
          <h3>Errors</h3>
          {result.errors.slice(0, 8).map((e, i) => (
            <div key={i} className="error-line">{e.line != null ? `L${e.line}: ` : ''}{e.message}</div>
          ))}
        </div>
      )}

      <details className="section log-details" open={result.status !== 'PASS'}>
        <summary>Simulation log</summary>
        <pre className="log-pre" tabIndex={0} role="region" aria-label="Simulation log output">{result.log_excerpt.slice(0, 2500)}{result.log_excerpt.length > 2500 ? '\n… truncated (2500 chars shown)' : ''}</pre>
      </details>
    </div>
  )
}

/** "count[0] never rose or fell", "a never fell", "data[7:4] never rose". */
export function describeUntoggled(u: UntoggledSignal): string {
  const span = (bits: number[]) => {
    if (u.width === 1) return ''
    const sorted = [...bits].sort((a, b) => b - a)
    const contiguous = sorted.every((b, i) => i === 0 || sorted[i - 1] - b === 1)
    if (sorted.length === u.width) return ''                       // the whole signal
    if (sorted.length === 1) return `[${sorted[0]}]`
    return contiguous ? `[${sorted[0]}:${sorted[sorted.length - 1]}]` : `[${sorted.join(',')}]`
  }
  const same = u.never_rose.length === u.never_fell.length && u.never_rose.every((b) => u.never_fell.includes(b))
  if (same) return `${u.signal}${span(u.never_rose)} never changed`
  const parts: string[] = []
  if (u.never_rose.length) parts.push(`${u.signal}${span(u.never_rose)} never rose`)
  if (u.never_fell.length) parts.push(`${u.signal}${span(u.never_fell)} never fell`)
  return parts.join('; ')
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className="metric">
      <div className={`metric-value ${tone ?? ''}`}>{value}</div>
      <div className="metric-label">{label}</div>
    </div>
  )
}

/** Formal equivalence of the mapped netlist and the RTL: proven, undecided, or a real mismatch. */
function EquivalenceLine({ status, method }: { status: string | null; method: string }) {
  if (!status)
    return <div data-testid="equivalence" className="equiv undecided"><strong>Netlist not formally checked.</strong> <span className="muted">{method}. The gate-level simulation check still applies.</span></div>
  if (status === 'proven')
    return <div data-testid="equivalence" className="equiv proven"><strong>Netlist formally proven equal to the RTL</strong> <span className="muted">({method})</span></div>
  if (status === 'different')
    return <div data-testid="equivalence" className="equiv different" role="alert"><strong>The mapped netlist does not match the RTL.</strong> {method}. The timing and area above describe a different circuit; treat them as invalid.</div>
  return <div data-testid="equivalence" className="equiv undecided"><strong>Netlist not formally proven equal to the RTL.</strong> <span className="muted">{method}. The gate-level simulation check still applies.</span></div>
}

/** The worst path pin by pin, as in an STA report: where the time goes. */
function CriticalPath({ rows, total: pathDelay, truncated }: { rows: CriticalPathRow[]; total: number | null; truncated: boolean }) {
  // The path's own delay (OpenSTA's data arrival), not the last row shown: rows of a very long path are capped.
  const total = pathDelay ?? rows[rows.length - 1].arrival_ns
  const gates = rows.filter((r) => r.incr_ns > 0).length
  return (
    <details className="critical-path" data-testid="critical-path">
      <summary>Critical path, pin by pin: {truncated ? 'long path, ' : `${gates} delay stages, `}{total.toFixed(3)} ns</summary>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Critical path table">
        <table>
          <thead><tr><th scope="col">Pin</th><th scope="col">Cell</th><th scope="col">Edge</th><th scope="col">Delay (ns)</th><th scope="col">Arrival (ns)</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="mono">{r.point}</td><td className="mono">{r.cell}</td><td>{r.edge}</td>
                <td className="num">{r.incr_ns.toFixed(4)}</td><td className="num">{r.arrival_ns.toFixed(4)}</td>
              </tr>
            )).flatMap((tr, i) => (truncated && i === rows.length - 1)
              ? [<tr key="gap"><td colSpan={5} className="muted">... middle pins omitted (path too long to list) ...</td></tr>, tr]
              : [tr])}
          </tbody>
        </table>
      </div>
    </details>
  )
}
