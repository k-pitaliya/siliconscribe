import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { RunResponse, SimulationResult, Waveform } from '../types'

vi.mock('../api', () => ({
  getModels: vi.fn(),
  streamDesign: vi.fn(),
  reSimulate: vi.fn(),
  exportUVM: vi.fn(),
  listProjects: vi.fn(),
  deleteProject: vi.fn(),
  getProject: vi.fn(),
}))
// CodeMirror is not what is under test here.
vi.mock('../components/CodeEditor', () => ({ default: () => <div data-testid="editor" /> }))

import App from '../App'
import * as api from '../api'

const wave = (name: string): Waveform => ({
  timescale: '1ps', timescale_ps: 1, end_time: 100_000, truncated: false, dropped_signals: 0, changes_truncated: false,
  signals: [{ name, width: 1, role: 'out', wave: [{ t: 0, v: '0' }] }],
})

const simResult = (over: Partial<SimulationResult> = {}): SimulationResult => ({
  status: 'PASS', module_name: 'counter', simulation_time_ns: 100, test_count: 8, pass_count: 8, fail_count: 0,
  coverage: { pass_rate: 100 }, errors: [], waveform_file: null, transcript_file: null, log_excerpt: '', ...over,
})

const firstRun = {
  design_id: 'd1', status: 'PASS', rtl_code: 'module counter; endmodule', testbench_code: 'module testbench; endmodule',
  explanation: 'x', rtl_spec: { module_name: 'counter', ports: [], parameters: [] },
  result: simResult(), waveform: wave('first_run_signal'), schematic: null,
  iteration_history: [{ iteration: 1, status: 'FAIL' }, { iteration: 2, status: 'PASS' }], iterations: 2,
  verification_warning: 'Only 3 checks ran.', fallback_notice: null,
  timing: { available: true, library: 'sky130', target_mhz: 100, period_ns: 10, slack_ns: 9.27, met: true, fmax_mhz: 1370, area_um2: 150.1, cell_count: 11, cells: [], note: 'n' },
  strength: { status: 'ok', total: 6, killed: 5, invalid: 0, survivors: [{ description: '`^` to `|`', line: 7 }], note: '', seconds: 0.4 },
} as unknown as RunResponse

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getModels).mockResolvedValue({ models: [], current: null, offline: true } as never)
  vi.mocked(api.listProjects).mockResolvedValue({ total: 0, projects: [] })
  vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
    onEvent({ stage: 'done', message: 'done', status: 'PASS', response: firstRun } as never)
  })
})

async function generate() {
  render(<App />)
  fireEvent.change(screen.getByLabelText('Describe the block'), { target: { value: 'Design a counter' } })
  fireEvent.click(screen.getByRole('button', { name: /Generate RTL/ }))
  await waitFor(() => expect(screen.getByText(/Only 3 checks ran/)).toBeInTheDocument())
}

describe('App: Re-run refreshes everything that belongs to the run', () => {
  it('replaces the waveform and clears the repair timeline and the weak-evidence warning', async () => {
    await generate()
    expect(screen.getByTestId('strength-summary').textContent).toContain('Caught 5 of 6')
    expect(screen.getByTestId('timing-summary').textContent).toContain('Meets 100 MHz')
    fireEvent.click(screen.getByRole('tab', { name: /Waveform/ }))
    expect(screen.getByText('first_run_signal')).toBeInTheDocument()

    vi.mocked(api.reSimulate).mockResolvedValue({
      ...simResult({ status: 'FAIL', pass_count: 7, fail_count: 1 }),
      waveform: wave('rerun_signal'),
    } as never)
    fireEvent.click(screen.getByRole('button', { name: /Re-run simulation/ }))

    await waitFor(() => expect(screen.getByText('rerun_signal')).toBeInTheDocument())
    expect(screen.queryByText('first_run_signal')).toBeNull() // no stale waveform beside the new verdict

    fireEvent.click(screen.getByRole('tab', { name: /Results/ }))
    expect(screen.queryByText(/Only 3 checks ran/)).toBeNull() // that warning described the old run
    expect(screen.queryByTestId('strength-section')).toBeNull() // it scored the old code, not the edited code
    expect(screen.queryByTestId('timing-section')).toBeNull() // it timed the old code
    expect(screen.getByText('FAIL')).toBeInTheDocument()
  })

  it('shows an empty waveform, not the old one, when the re-run produced none', async () => {
    await generate()
    vi.mocked(api.reSimulate).mockResolvedValue({ ...simResult(), waveform: null } as never)
    fireEvent.click(screen.getByRole('button', { name: /Re-run simulation/ }))
    await waitFor(() => expect(api.reSimulate).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('tab', { name: /Waveform/ }))
    await waitFor(() => expect(screen.getByText(/No waveform/)).toBeInTheDocument())
  })
})


describe('App: a provider failure during a run', () => {
  it('shows the explanation, stops the run timer and lets the user try again', async () => {
    const quota = "The AI provider's free usage limit has been reached. It resets daily: try again after the reset, or switch to the offline demo."
    vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
      onEvent({ stage: 'start', message: 'Parsing requirement…' } as never)
      onEvent({ stage: 'error', message: quota } as never)
    })
    render(<App />)
    fireEvent.change(screen.getByLabelText('Describe the block'), { target: { value: 'Design a counter' } })
    fireEvent.click(screen.getByRole('button', { name: /Generate RTL/ }))

    await waitFor(() => expect(screen.getByText(quota)).toBeInTheDocument())      // the reason is on screen
    expect(screen.queryByTestId('run-timer')).toBeNull()                          // no "Working…" clock left ticking
    expect(screen.getByRole('button', { name: /Generate RTL/ })).not.toBeDisabled() // can retry immediately
    expect(screen.queryByText('Internal server error')).toBeNull()
  })

  it('reports a dropped connection instead of hanging silently', async () => {
    vi.mocked(api.streamDesign).mockRejectedValue(new Error('The connection closed before the run finished. Please try again.'))
    render(<App />)
    fireEvent.change(screen.getByLabelText('Describe the block'), { target: { value: 'Design a counter' } })
    fireEvent.click(screen.getByRole('button', { name: /Generate RTL/ }))
    await waitFor(() => expect(screen.getByText(/connection closed before the run finished/)).toBeInTheDocument())
    expect(screen.queryByTestId('run-timer')).toBeNull()
  })
})


describe('App: layout behaviour', () => {
  it('opens Results when a run finishes and shows the run timeline', async () => {
    await generate()
    expect(screen.getByRole('tab', { name: /Results/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('log', { name: 'Run timeline' }).textContent).toContain('Design a counter')
  })

  it('first visit explains the flow instead of an empty editor', () => {
    render(<App />)
    expect(screen.getByText('Describe a block. Get Verilog and the evidence to judge it.')).toBeInTheDocument()
  })

  it('the theme switch cycles system, light, dark and is remembered', () => {
    localStorage.removeItem('ss-theme')
    render(<App />)
    const btn = screen.getByRole('button', { name: /Theme: system/ })
    fireEvent.click(btn)
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(localStorage.getItem('ss-theme')).toBe('light')
    fireEvent.click(screen.getByRole('button', { name: /Theme: light/ }))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    fireEvent.click(screen.getByRole('button', { name: /Theme: dark/ }))
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem('ss-theme')).toBeNull()
  })

  it('the projects menu closes with Escape', async () => {
    render(<App />)
    fireEvent.click(screen.getByRole('button', { name: /Projects/ }))
    expect(screen.getByRole('dialog', { name: 'Recent projects' })).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Recent projects' })).toBeNull()
  })
})


describe('App: Re-run and the visible tab', () => {
  it('from the Design tab it opens Results; from another tab it stays put', async () => {
    await generate()                                                     // a finished run opens Results
    vi.mocked(api.reSimulate).mockResolvedValue({ ...simResult({ status: 'FAIL', fail_count: 1 }), waveform: wave('x') } as never)
    fireEvent.click(screen.getByRole('tab', { name: /Design/ }))
    fireEvent.click(screen.getByRole('button', { name: /Re-run simulation/ }))
    await waitFor(() => expect(screen.getByRole('tab', { name: /Results/ })).toHaveAttribute('aria-selected', 'true'))

    fireEvent.click(screen.getByRole('tab', { name: /Test cases/ }))
    fireEvent.click(screen.getByRole('button', { name: /Re-run simulation/ }))
    await waitFor(() => expect(api.reSimulate).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('tab', { name: /Test cases/ })).toHaveAttribute('aria-selected', 'true')
  })
})
