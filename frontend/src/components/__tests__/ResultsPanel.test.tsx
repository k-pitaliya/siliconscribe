import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import ResultsPanel from '../ResultsPanel'
import type { SimulationResult, IterationRecord, Waveform, Schematic } from '../../types'

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
})
