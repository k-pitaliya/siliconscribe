import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ResultsPanel from '../ResultsPanel'
import type { SimulationResult, IterationRecord, Waveform, Schematic, SynthesisInfo, LintInfo } from '../../types'

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
