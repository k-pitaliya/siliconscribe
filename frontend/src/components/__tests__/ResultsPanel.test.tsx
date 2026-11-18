import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ResultsPanel, { describeUntoggled } from '../ResultsPanel'
import type { SimulationResult, IterationRecord, Waveform, Schematic, SynthesisInfo, LintInfo, StrengthReport, TimingReport } from '../../types'

const passResult: SimulationResult = {
  status: 'PASS',
  module_name: 'counter',
  simulation_time_ns: 200,
  test_count: 20,
  pass_count: 20,
  fail_count: 0,
  coverage: { pass_rate: 100 },
  errors: [],
  waveform_file: null,
  transcript_file: null,
  log_excerpt: 'ALL TESTS PASSED',
}

const failResult: SimulationResult = {
  ...passResult,
  status: 'FAIL',
  pass_count: 1,
  fail_count: 19,
  coverage: { pass_rate: 5 },
  errors: [{ file: 'test.v', line: 42, message: 'assertion failed' }],
  log_excerpt: 'FAIL at time 50',
}

const history: IterationRecord[] = [
  { iteration: 0, status: 'FAIL', fix_summary: 'initial', pass_count: 1, fail_count: 19, log_excerpt: '' },
  { iteration: 1, status: 'PASS', fix_summary: 'fixed bug', pass_count: 20, fail_count: 0, log_excerpt: '' },
]

const waveform: Waveform = {
  timescale: '1ns', end_time: 100, truncated: false, dropped_signals: 0, changes_truncated: false,
  signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }, { t: 5, v: '1' }] }],
}

const schematic: Schematic = {
  module_name: 'counter',
  inputs: [{ name: 'clk', direction: 'input', width: 1 }],
  outputs: [{ name: 'count', direction: 'output', width: 4 }],
  inouts: [],
}

describe('ResultsPanel', () => {
  it('shows empty state when no result', () => {
    render(<ResultsPanel result={null} waveform={null} schematic={null} history={[]} />)
    expect(screen.getByText(/No simulation yet/)).toBeInTheDocument()
  })

  it('renders PASS status badge', () => {
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} />)
    expect(screen.getByText('PASS')).toBeInTheDocument()
  })

  it('renders FAIL status badge', () => {
    render(<ResultsPanel result={failResult} waveform={null} schematic={null} history={[]} />)
    expect(screen.getByText('FAIL')).toBeInTheDocument()
  })

  it('shows metric grid with test counts', () => {
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} />)
    expect(screen.getAllByText('20').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('100%')).toBeInTheDocument()
  })

  it('shows iteration timeline when history has >1 entry', () => {
    render(<ResultsPanel result={failResult} waveform={null} schematic={null} history={history} />)
    expect(screen.getByText('Self-correction loop')).toBeInTheDocument()
    expect(screen.getByText('#0')).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
  })

  it('does not show iteration timeline for single iteration', () => {
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[history[0]]} />)
    expect(screen.queryByText('Self-correction loop')).not.toBeInTheDocument()
  })

  it('renders structured diagnosis from a fix iteration', () => {
    const diagHistory: IterationRecord[] = [
      history[0],
      {
        ...history[1],
        fix_type: 'llm_diagnosis',
        diagnosis: {
          symptom: 'expected count 5, got 7 at t=20',
          root_cause: 'counter increments by 2 instead of 1',
          fix_location: 'counter.v:12 (increment expression)',
          confidence: 'high',
        },
      },
    ]
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={diagHistory} />)
    expect(screen.getByText(/increments by 2 instead of 1/)).toBeInTheDocument()
    expect(screen.getByText(/counter\.v:12/)).toBeInTheDocument()
    expect(screen.getByText(/Confidence: high/)).toBeInTheDocument()
  })

  it('labels a scripted offline fix instead of faking a diagnosis', () => {
    const scripted: IterationRecord[] = [
      history[0],
      { ...history[1], fix_type: 'offline_scripted', diagnosis: null },
    ]
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={scripted} />)
    expect(screen.getByText(/Scripted offline fix/)).toBeInTheDocument()
  })

  it('shows errors when present', () => {
    render(<ResultsPanel result={failResult} waveform={null} schematic={null} history={[]} />)
    expect(screen.getByText('Errors')).toBeInTheDocument()
    expect(screen.getByText(/L42:/)).toBeInTheDocument()
  })

  it('switches to waveform tab and shows waveform', () => {
    render(<ResultsPanel result={passResult} waveform={waveform} schematic={schematic} history={[]} />)
    fireEvent.click(screen.getByText(/Waveform/))
    expect(screen.getByText(/1ns/)).toBeInTheDocument()
  })

  it('switches to schematic tab and shows module name', () => {
    render(<ResultsPanel result={passResult} waveform={waveform} schematic={schematic} history={[]} />)
    fireEvent.click(screen.getByText(/Schematic/))
    expect(screen.getByText('counter')).toBeInTheDocument()
  })

  it('shows simulation log', () => {
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} />)
    expect(screen.getByText('ALL TESTS PASSED')).toBeInTheDocument()
  })

  it('shows synthesis section when synthesis available', () => {
    const synthesis: SynthesisInfo = { available: true, cell_count: 42, area_estimate: 123.5 }
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} synthesis={synthesis} />)
    expect(screen.getByTestId('synthesis-section')).toBeInTheDocument()
    expect(screen.getByText(/42/)).toBeInTheDocument()
    expect(screen.getByText(/123.5/)).toBeInTheDocument()
    expect(screen.getByText(/Synthesis/)).toBeInTheDocument()
  })

  it('shows synthesis fallback when not available', () => {
    const synthesis: SynthesisInfo = { available: false, error: 'yosys not found' }
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} synthesis={synthesis} />)
    expect(screen.getByTestId('synthesis-section')).toBeInTheDocument()
    expect(screen.getByText(/yosys not found/)).toBeInTheDocument()
  })

  it('does not show synthesis section when synthesis is null', () => {
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} synthesis={null} />)
    expect(screen.queryByTestId('synthesis-section')).not.toBeInTheDocument()
  })

  it('pass_rate color is green at 100, amber at 85, red at 40', () => {
    const r100: SimulationResult = { ...passResult, coverage: { pass_rate: 100 } }
    const { rerender } = render(<ResultsPanel result={r100} waveform={null} schematic={null} history={[]} />)
    const val100 = screen.getByText('100%')
    expect(val100.className).toContain('ok')

    const r85: SimulationResult = { ...passResult, coverage: { pass_rate: 85 } }
    rerender(<ResultsPanel result={r85} waveform={null} schematic={null} history={[]} />)
    const val85 = screen.getByText('85%')
    expect(val85.className).toContain('warn')

    const r40: SimulationResult = { ...passResult, coverage: { pass_rate: 40 } }
    rerender(<ResultsPanel result={r40} waveform={null} schematic={null} history={[]} />)
    const val40 = screen.getByText('40%')
    expect(val40.className).toContain('bad')
  })

  it('shows lint section when lint has errors/warnings', () => {
    const lint: LintInfo = {
      ok: false,
      errors: [{ file: 'design.v', line: 10, message: 'undeclared signal' }],
      warnings: [{ file: 'design.v', line: 5, message: 'unused port' }],
      output: '',
    }
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} lint={lint} />)
    expect(screen.getByTestId('lint-section')).toBeInTheDocument()
    expect(screen.getByText(/undeclared/)).toBeInTheDocument()
    expect(screen.getByText(/unused port/)).toBeInTheDocument()
  })

  it('does not show lint section when no errors/warnings', () => {
    const lint: LintInfo = { ok: true, errors: [], warnings: [], output: '' }
    render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} lint={lint} />)
    expect(screen.queryByTestId('lint-section')).not.toBeInTheDocument()
  })
})


describe('honesty labels', () => {
  const base = { waveform, schematic, history: [] as IterationRecord[], iterations: 0 }

  it('shows a demo tag when the result came from the built-in fallback', () => {
    render(<ResultsPanel result={passResult} {...base} degraded />)
    expect(screen.getByTestId('demo-result-tag')).toHaveTextContent(/not generated by the AI/i)
  })

  it('shows no demo tag for a normal live result', () => {
    render(<ResultsPanel result={passResult} {...base} />)
    expect(screen.queryByTestId('demo-result-tag')).toBeNull()
  })

  it('shows the weak-evidence warning when provided', () => {
    render(<ResultsPanel result={passResult} {...base} warning="Weak evidence: only 13 checks" />)
    expect(screen.getByTestId('weak-evidence-tag')).toHaveTextContent(/only 13 checks/)
  })
})


describe('ResultsPanel: test cases tab and expand', () => {
  const withChecks: SimulationResult = {
    ...failResult,
    test_count: 2, pass_count: 1, fail_count: 1,
    checks: [
      { idx: 1, status: 'PASS', category: 'reset', name: 'a', t: 1000, expected: '0', actual: '0', detail: '', source: 'chk' },
      { idx: 2, status: 'FAIL', category: 'directed', name: 'b', t: 20_000, expected: '1', actual: '2', detail: '', source: 'chk' },
    ],
    check_groups: [
      { category: 'reset', total: 1, passed: 1, failed: 0 },
      { category: 'directed', total: 1, passed: 0, failed: 1 },
    ],
    checks_source: 'structured', checks_consistent: true, checks_truncated: false, checks_total_logged: 2,
  }
  const wave: Waveform = {
    timescale: '1ps', timescale_ps: 1, end_time: 100_000, truncated: false, dropped_signals: 0, changes_truncated: false,
    signals: [{ name: 'clk', width: 1, role: 'clock', wave: [{ t: 0, v: '0' }] }],
  }
  const panel = (result: SimulationResult | null = withChecks) =>
    render(<ResultsPanel result={result} waveform={wave} schematic={null} history={[]} />)

  it('has a Test cases tab with a count badge that lists the checks', () => {
    panel()
    expect(screen.getByTestId('tests-badge').textContent).toContain('2')
    fireEvent.click(screen.getByRole('tab', { name: /Test cases/ }))
    expect(screen.getAllByTestId('check-row')).toHaveLength(2)
  })

  it('invites a first run when there is no result yet', () => {
    panel(null)
    fireEvent.click(screen.getByRole('tab', { name: /Test cases/ }))
    expect(screen.getByText(/No simulation yet/)).toBeInTheDocument()
  })

  it('jumps from a failed check to its moment in the waveform', () => {
    const { container } = panel()
    fireEvent.click(screen.getByRole('tab', { name: /Test cases/ }))
    fireEvent.click(screen.getAllByTestId('check-row')[1])
    fireEvent.click(screen.getByRole('button', { name: /Show in waveform/ }))
    expect(screen.getByRole('tab', { name: /Waveform/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 20 ns')
    expect(container.querySelectorAll('.wfv-marker')).toHaveLength(1) // the failed check is flagged on the ruler
  })

  it('arrow keys cycle through all four tabs', () => {
    panel()
    const list = screen.getByRole('tablist')
    fireEvent.keyDown(list, { key: 'ArrowRight' })
    expect(screen.getByRole('tab', { name: /Test cases/ })).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    fireEvent.keyDown(list, { key: 'ArrowLeft' })
    expect(screen.getByRole('tab', { name: /Schematic/ })).toHaveAttribute('aria-selected', 'true')
  })

  it('puts the code editor in a Design tab that opens first, and follows tab requests', () => {
    const { rerender } = render(
      <ResultsPanel result={withChecks} waveform={wave} schematic={null} history={[]} design={<div>editor here</div>} />,
    )
    expect(screen.getAllByRole('tab').map((t) => t.textContent?.trim().split(' ')[0])).toEqual(['Design', 'Results', 'Test', 'Waveform', 'Schematic'])
    expect(screen.getByRole('tab', { name: /Design/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('editor here')).toBeInTheDocument()
    rerender(<ResultsPanel result={withChecks} waveform={wave} schematic={null} history={[]} design={<div>editor here</div>} tabRequest={{ tab: 'results', seq: 1 }} />)
    expect(screen.getByRole('tab', { name: /Results/ })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: /Design/ }))
    rerender(<ResultsPanel result={withChecks} waveform={wave} schematic={null} history={[]} design={<div>editor here</div>} tabRequest={{ tab: 'results', seq: 2 }} />)
    expect(screen.getByRole('tab', { name: /Results/ })).toHaveAttribute('aria-selected', 'true')   // a repeated request still counts
  })

  it('every view gets the full height: there is no Expand button any more', () => {
    panel()
    expect(screen.queryByRole('button', { name: /Expand/ })).toBeNull()
  })
})


describe('ResultsPanel: richer synthesis report', () => {
  const base = { result: passResult, waveform: null, schematic: null, history: [] as IterationRecord[] }
  it('shows cell types, flip-flop and latch counts', () => {
    const synthesis: SynthesisInfo = { available: true, cell_count: 20, flip_flops: 4, latches: 0, cell_types: [['AND', 5], ['XOR', 3]] }
    render(<ResultsPanel {...base} synthesis={synthesis} />)
    expect(screen.getByTestId('synth-flops').textContent).toContain('Flip-flops: 4')
    expect(screen.getByTestId('synth-types').textContent).toBe('AND ×5, XOR ×3')
    expect(screen.queryByTestId('synth-latch')).toBeNull()
  })
  it('warns about an inferred latch and shows Yosys warnings', () => {
    const synthesis: SynthesisInfo = { available: true, cell_count: 2, flip_flops: 0, latches: 1, latch_warning: '1 latch(es) inferred: check your if/case', warnings: ['Found 1 problems'] }
    render(<ResultsPanel {...base} synthesis={synthesis} />)
    expect(screen.getByTestId('synth-latch').textContent).toContain('latch')
    expect(screen.getByTestId('synth-warning').textContent).toContain('Found 1 problems')
  })
})


describe('ResultsPanel: testbench strength', () => {
  const base = { result: passResult, waveform: null, schematic: null, history: [] as IterationRecord[] }
  const report = (over: Partial<StrengthReport> = {}): StrengthReport => ({
    status: 'ok', total: 10, killed: 8, invalid: 1, seconds: 1.2,
    survivors: [{ description: '`+` to `-`', line: 12 }, { description: '`posedge` to `negedge`', line: 9 }],
    note: 'A survivor is a change the testbench did not notice; some survivors may be equivalent.', ...over,
  })

  it('shows how many injected bugs were caught and which were missed, with the honest caveat', () => {
    render(<ResultsPanel {...base} strength={report()} />)
    expect(screen.getByTestId('strength-summary').textContent).toContain('Caught 8 of 10 injected bugs')
    const survivors = screen.getByTestId('strength-survivors').textContent ?? ''
    expect(survivors).toContain('line 12: `+` to `-`')
    expect(survivors).toContain('line 9')
    expect(screen.getByTestId('strength-section').textContent).toContain('may be equivalent')
  })

  it('omits the survivor list when every bug was caught', () => {
    render(<ResultsPanel {...base} strength={report({ killed: 10, survivors: [] })} />)
    expect(screen.getByTestId('strength-summary').textContent).toContain('Caught 10 of 10')
    expect(screen.queryByTestId('strength-survivors')).toBeNull()
  })

  it('colours the bar amber only below the weak-testbench threshold (half caught)', () => {
    const bar = () => screen.getByTestId('strength-section').querySelector('.bar') as HTMLElement
    const { rerender } = render(<ResultsPanel {...base} strength={report({ killed: 7, total: 8 })} />)
    expect(bar().classList.contains('weak')).toBe(false)
    rerender(<ResultsPanel {...base} strength={report({ killed: 3, total: 8 })} />)
    expect(bar().classList.contains('weak')).toBe(true)
  })

  it('says when the run stopped at the time limit', () => {
    render(<ResultsPanel {...base} strength={report({ status: 'partial' })} />)
    expect(screen.getByTestId('strength-summary').textContent).toContain('stopped early')
  })

  it('shows nothing when strength was skipped or absent', () => {
    const { rerender } = render(<ResultsPanel {...base} strength={report({ status: 'skipped', total: 0, killed: 0 })} />)
    expect(screen.queryByTestId('strength-section')).toBeNull()
    rerender(<ResultsPanel {...base} strength={null} />)
    expect(screen.queryByTestId('strength-section')).toBeNull()
  })
})


describe('ResultsPanel: measured toggle coverage', () => {
  const withToggle = (over = {}): SimulationResult => ({
    ...passResult,
    measured_toggle: {
      percent: 85.7, bits_total: 7, bits_toggled: 6, signals: 4, untoggled_more: 0, partial: false,
      untoggled: [{ signal: 'count', width: 4, never_rose: [0], never_fell: [0] }], ...over,
    },
  })

  it('shows the measured percentage, the counts and which bits never switched', () => {
    render(<ResultsPanel result={withToggle()} waveform={null} schematic={null} history={[]} />)
    const summary = screen.getByTestId('toggle-summary').textContent ?? ''
    expect(summary).toContain('85.7%')
    expect(summary).toContain('6 of 7 bits, 4 signals')
    expect(screen.getByTestId('toggle-untoggled').textContent).toContain('count[0] never changed')
    expect(screen.getByTestId('toggle-section').textContent).toContain('not reported by the testbench')
  })

  it('says when the waveform was cut and when more signals are not listed', () => {
    render(<ResultsPanel result={withToggle({ partial: true, untoggled_more: 3 })} waveform={null} schematic={null} history={[]} />)
    const text = screen.getByTestId('toggle-section').textContent ?? ''
    expect(text).toContain('lower bound')
    expect(text).toContain('and 3 more signal(s)')
  })

  it('shows no section when nothing was measured, and no list at 100%', () => {
    const { rerender } = render(<ResultsPanel result={passResult} waveform={null} schematic={null} history={[]} />)
    expect(screen.queryByTestId('toggle-section')).toBeNull()
    rerender(<ResultsPanel result={withToggle({ percent: 100, bits_toggled: 7, untoggled: [] })} waveform={null} schematic={null} history={[]} />)
    expect(screen.getByTestId('toggle-summary').textContent).toContain('100%')
    expect(screen.queryByTestId('toggle-untoggled')).toBeNull()
  })

  it('describes untoggled bits in plain words', () => {
    expect(describeUntoggled({ signal: 'a', width: 1, never_rose: [], never_fell: [0] })).toBe('a never fell')
    expect(describeUntoggled({ signal: 'en', width: 1, never_rose: [0], never_fell: [0] })).toBe('en never changed')
    expect(describeUntoggled({ signal: 'data', width: 8, never_rose: [7, 6, 5, 4], never_fell: [] })).toBe('data[7:4] never rose')
    expect(describeUntoggled({ signal: 'q', width: 4, never_rose: [3, 2, 1, 0], never_fell: [3, 2, 1, 0] })).toBe('q never changed')
    expect(describeUntoggled({ signal: 'q', width: 4, never_rose: [3, 1], never_fell: [0] })).toBe('q[3,1] never rose; q[0] never fell')
  })
})


describe('ResultsPanel: timing and mapped area', () => {
  const base = { result: passResult, waveform: null, schematic: null, history: [] as IterationRecord[] }
  const timing = (over: Partial<TimingReport> = {}): TimingReport => ({
    available: true, library: 'sky130_fd_sc_hd, typical corner (25 C, 1.8 V)', clock: 'clk', target_mhz: 100, period_ns: 10,
    slack_ns: 9.27, met: true, fmax_mhz: 1369.9, critical_start: '_14_', critical_end: '_17_', critical_delay_ns: 0.6,
    area_um2: 150.144, cell_count: 11, flip_flops: 4, cells: [['dfrtp_1', 4], ['xnor2_1', 3]],
    note: 'Pre-layout estimate on one typical corner. Not sign-off timing.', ...over,
  })

  it('says whether the target clock is met, with slack, maximum frequency, path and real area', () => {
    render(<ResultsPanel {...base} timing={timing()} />)
    const s = screen.getByTestId('timing-summary').textContent ?? ''
    expect(s).toContain('Meets 100 MHz')
    expect(s).toContain('+9.27 ns slack')
    expect(s).toContain('maximum about 1370 MHz')
    expect(screen.getByTestId('timing-area').textContent).toContain('150.1 µm² in 11 cells, 4 flip-flops')
    const all = screen.getByTestId('timing-section').textContent ?? ''
    expect(all).toContain('_14_')
    expect(all).toContain('Not sign-off timing')                  // the limits are always shown
  })

  it('shows a missed target with negative slack', () => {
    render(<ResultsPanel {...base} timing={timing({ met: false, slack_ns: -2.19, fmax_mhz: 371.7, target_mhz: 2000 })} />)
    const s = screen.getByTestId('timing-summary').textContent ?? ''
    expect(s).toContain('Misses 2000 MHz')
    expect(s).toContain('-2.19 ns slack')
  })

  it('replaces the made-up area proxy once real mapped area exists', () => {
    const synthesis: SynthesisInfo = { available: true, cell_count: 10, area_estimate: 50 }
    const { rerender } = render(<ResultsPanel {...base} synthesis={synthesis} />)
    expect(screen.getByTestId('synthesis-section').textContent).toContain('Relative area proxy')
    rerender(<ResultsPanel {...base} synthesis={synthesis} timing={timing()} />)
    expect(screen.getByTestId('synthesis-section').textContent).not.toContain('Relative area proxy')
  })

  it('words a clockless design as an input-to-output path, not as meeting a clock', () => {
    const { rerender } = render(<ResultsPanel {...base} timing={timing({ clock: 'virtual (combinational design)', slack_ns: 7.51, period_ns: 10, met: true, fmax_mhz: 401.6 })} />)
    const s = screen.getByTestId('timing-summary').textContent ?? ''
    expect(s).toContain('Longest input-to-output path: 2.49 ns.')
    expect(s).toContain('It fits the 10 ns budget (100 MHz) with 7.51 ns to spare.')
    expect(s).toContain('no clock')
    expect(s).not.toMatch(/Meets|Misses/)
    rerender(<ResultsPanel {...base} timing={timing({ clock: 'virtual (combinational design)', slack_ns: -2.19, period_ns: 0.5, met: false, target_mhz: 2000, fmax_mhz: 371.7 })} />)
    const bad = screen.getByTestId('timing-summary').textContent ?? ''
    expect(bad).toContain('Longest input-to-output path: 2.69 ns.')
    expect(bad).toContain('It is 2.19 ns over the 0.5 ns budget (2000 MHz).')
  })

  it('keeps the real area visible when the timing itself was refused', () => {
    render(<ResultsPanel {...base} timing={timing({ slack_ns: null, met: null, fmax_mhz: null, error: 'The design contains latches; timing of latch-based logic is not estimated.' })} />)
    expect(screen.getByTestId('timing-summary').textContent).toContain('contains latches')
    expect(screen.getByTestId('timing-summary').textContent).not.toMatch(/Meets|Misses/)
    expect(screen.getByTestId('timing-area').textContent).toContain('150.1 µm²')
  })

  it('shows the reason when no path could be timed, and nothing when timing is unavailable', () => {
    const { rerender } = render(<ResultsPanel {...base} timing={timing({ slack_ns: null, met: null, fmax_mhz: null, error: 'OpenSTA reported no constrained path.' })} />)
    expect(screen.getByTestId('timing-summary').textContent).toContain('no constrained path')
    rerender(<ResultsPanel {...base} timing={timing({ available: false })} />)
    expect(screen.queryByTestId('timing-section')).toBeNull()
    rerender(<ResultsPanel {...base} timing={null} />)
    expect(screen.queryByTestId('timing-section')).toBeNull()
  })
})

describe('ResultsPanel: who wrote what, and the second opinion', () => {
  const base = { result: passResult, waveform: null, schematic: null, history: [] as IterationRecord[] }
  it('names a separate testbench model next to the design model', () => {
    render(<ResultsPanel {...base} model="opencode/hy4-flash-free" testbenchModel="nim/poolside/laguna-xs-2.1" />)
    const line = screen.getByTestId('model-used').textContent ?? ''
    expect(line).toContain('Written by opencode/hy4-flash-free')
    expect(line).toContain('Testbench written by nim/poolside/laguna-xs-2.1, a separate model')
  })

  it('says nothing about a separate testbench when one model wrote both', () => {
    render(<ResultsPanel {...base} model="opencode/hy4-flash-free" />)
    expect(screen.getByTestId('model-used').textContent).not.toContain('Testbench written by')
  })

  it('shows an agreeing second opinion plainly', () => {
    render(<ResultsPanel {...base} secondOpinion={{ status: 'PASS', pass_count: 120, fail_count: 0, test_count: 120, note: '' }} />)
    const t = screen.getByTestId('second-opinion').textContent ?? ''
    expect(t).toContain('Second opinion agrees')
    expect(t).toContain('passes all 120 of 120 checks')
  })

  it('warns when a fresh testbench disagrees with a PASS that followed a rewrite', () => {
    render(<ResultsPanel {...base} secondOpinion={{ status: 'FAIL', pass_count: 100, fail_count: 20, test_count: 120, note: '' }} />)
    const el = screen.getByTestId('second-opinion')
    expect(el.textContent).toContain('Second opinion disagrees')
    expect(el.textContent).toContain('fails 20 of 120 checks')
    expect(el.textContent).toContain('do not trust this PASS')
    expect(el.className).toContain('weak-tag')
  })

  it('reports an unobtainable second opinion without alarm', () => {
    render(<ResultsPanel {...base} secondOpinion={{ status: 'unavailable', pass_count: 0, fail_count: 0, test_count: 0, note: 'the model did not answer.' }} />)
    const el = screen.getByTestId('second-opinion')
    expect(el.textContent).toContain('Second opinion not obtained: the model did not answer.')
    expect(el.className).not.toContain('weak-tag')
  })

  it('shows no second-opinion line when there was none', () => {
    render(<ResultsPanel {...base} />)
    expect(screen.queryByTestId('second-opinion')).toBeNull()
  })
})

