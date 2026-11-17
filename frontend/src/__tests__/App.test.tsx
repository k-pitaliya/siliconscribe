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
  fireEvent.change(screen.getByLabelText('Natural Language Requirement'), { target: { value: 'Design a counter' } })
  fireEvent.click(screen.getByRole('button', { name: /Generate RTL/ }))
  await waitFor(() => expect(screen.getByText(/Only 3 checks ran/)).toBeInTheDocument())
}

describe('App: Re-run refreshes everything that belongs to the run', () => {
  it('replaces the waveform and clears the repair timeline and the weak-evidence warning', async () => {
    await generate()
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
