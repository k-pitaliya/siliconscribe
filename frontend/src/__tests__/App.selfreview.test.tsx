import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ModelInfo, ModelsResponse, RTLDesignSpec, RunResponse, SimulationResult } from '../types'

vi.mock('../api', () => ({
  getModels: vi.fn(), parseSpec: vi.fn(), streamDesign: vi.fn(), reSimulate: vi.fn(), exportUVM: vi.fn(),
  listProjects: vi.fn(), deleteProject: vi.fn(), getProject: vi.fn(),
}))
vi.mock('../components/CodeEditor', () => ({ default: () => <div data-testid="editor" /> }))

import App from '../App'
import * as api from '../api'

const m = (id: string, over: Partial<ModelInfo> = {}): ModelInfo => ({ id, label: id, note: '', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: true, ...over })
const MODELS = [m('opencode/deepseek-v4.1-flash-free'), m('nim/poolside/laguna-xs-2.1', { provider: 'nim', group: 'NVIDIA NIM', free: null })]
const modelsResponse: ModelsResponse = {
  offline: false, current: 'opencode/deepseek-v4.1-flash-free', models: MODELS, paid_hidden: 0,
  providers: [{ id: 'opencode', label: 'OpenCode', available: true, count: 1 }, { id: 'nim', label: 'NVIDIA NIM', available: true, count: 1 }],
}
const SPEC: RTLDesignSpec = {
  module_name: 'counter', parameters: [], behavior: 'Counts up on every clock edge.', constraints: ['reset wins over enable'],
  ports: [{ name: 'clk', direction: 'input', width: 1, description: 'Clock' }, { name: 'count', direction: 'output', width: 4, description: 'Count' }],
}
const sim = (): SimulationResult => ({ status: 'PASS', module_name: 'counter', simulation_time_ns: 1, test_count: 8, pass_count: 8, fail_count: 0,
  coverage: { pass_rate: 100 }, errors: [], waveform_file: null, transcript_file: null, log_excerpt: '' })
const done = (over: Record<string, unknown> = {}) => ({ design_id: 'd1', status: 'PASS', rtl_code: 'module counter; endmodule', testbench_code: 'module testbench; endmodule',
  explanation: 'x', rtl_spec: SPEC, result: sim(), waveform: null, schematic: null, iteration_history: [], iterations: 0, fallback_notice: null,
  model: 'opencode/deepseek-v4.1-flash-free', ...over }) as unknown as RunResponse

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  vi.mocked(api.getModels).mockResolvedValue(modelsResponse)
  vi.mocked(api.listProjects).mockResolvedValue({ total: 0, projects: [] })
  vi.mocked(api.parseSpec).mockResolvedValue(SPEC)
  vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => { onEvent({ stage: 'done', message: 'done', status: 'PASS', response: done() } as never) })
})

async function ready() { await screen.findByRole('combobox', { name: 'Model' }) }
function type(prompt = 'Design a counter') { fireEvent.change(screen.getByLabelText('Describe the block'), { target: { value: prompt } }) }
const generate = () => fireEvent.click(screen.getByRole('button', { name: /Generate RTL/ }))


const project = (id: string, over: Record<string, unknown> = {}) => done({ design_id: id, rtl_code: `module counter; // ${id}\nendmodule`, ...over })

async function openProject(label = 'Open', index = 0) {
  fireEvent.click(screen.getByRole('button', { name: /Projects/ }))
  fireEvent.click((await screen.findAllByRole('button', { name: label }))[index])
}

describe('App: self-review findings (19 Nov)', () => {
  beforeEach(() => {
    vi.mocked(api.listProjects).mockResolvedValue({ total: 2, projects: [
      { design_id: 'p1', prompt: 'a', module_name: 'counter', status: 'PASS', created_at: 1, iterations: 2 },
      { design_id: 'p2', prompt: 'b', module_name: 'counter', status: 'PASS', created_at: 2, iterations: 0 },
    ] })
  })

  it('opening a project clears the previous run lint and shows that project repair loop', async () => {
    vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
      onEvent({ stage: 'lint', message: 'lint', lint: { ok: false, errors: [{ line: 3, message: 'OLD-RUN-LINT' }], warnings: [] } } as never)
      onEvent({ stage: 'done', message: 'done', status: 'PASS', response: done() } as never)
    })
    const hist = [0, 1, 2].map((i) => ({ iteration: i, status: i < 2 ? 'FAIL' : 'PASS', fix_summary: 'f', pass_count: 1, fail_count: 0 }))
    vi.mocked(api.getProject).mockResolvedValue(project('p1', { iteration_history: hist, iterations: undefined }) as never)
    render(<App />); await ready(); type(); generate()
    expect(await screen.findByText(/OLD-RUN-LINT/)).toBeInTheDocument()
    await openProject()
    expect(await screen.findByText('Self-correction loop')).toBeInTheDocument()   // the project is on screen
    expect(screen.queryByTestId('lint-section')).toBeNull()
  })

  it('a slow earlier project load cannot overwrite a newer one', async () => {
    let releaseA: (v: unknown) => void = () => {}
    vi.mocked(api.getProject).mockImplementation((id: string) =>
      id === 'p1' ? new Promise((r) => { releaseA = r }) as never : Promise.resolve(project('p2', { verification_warning: 'FROM-B' })) as never)
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('button', { name: /Projects/ }))
    const opens = await screen.findAllByRole('button', { name: 'Open' })
    fireEvent.click(opens[0])             // A (slow)
    fireEvent.click(opens[1])             // B (fast)
    expect(await screen.findByText(/FROM-B/)).toBeInTheDocument()
    releaseA(project('p1', { verification_warning: 'FROM-A' }))
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/FROM-A/)).toBeNull()
    expect(screen.getByText(/FROM-B/)).toBeInTheDocument()
  })

  it('Stop cancels a re-run', async () => {
    let seenSignal: AbortSignal | undefined
    vi.mocked(api.reSimulate).mockImplementation((_d, _r, _t, signal?: AbortSignal) => new Promise((_res, rej) => {
      seenSignal = signal
      signal?.addEventListener('abort', () => rej(Object.assign(new Error('aborted'), { name: 'AbortError' })))
    }) as never)
    render(<App />); await ready(); type(); generate()
    await screen.findByTestId('verdict-badge')
    fireEvent.click(screen.getByRole('button', { name: /Re-run/ }))
    fireEvent.click(await screen.findByRole('button', { name: /Stop/ }))
    await waitFor(() => expect(seenSignal?.aborted).toBe(true))
    expect(await screen.findByText('Re-run cancelled.')).toBeInTheDocument()
  })

  it('a re-run says what was not recomputed', async () => {
    vi.mocked(api.reSimulate).mockResolvedValue({ ...sim(), waveform: null } as never)
    render(<App />); await ready(); type(); generate()
    await screen.findByTestId('verdict-badge')
    fireEvent.click(screen.getByRole('button', { name: /Re-run/ }))
    expect(await screen.findByText(/only the simulation was repeated/)).toBeInTheDocument()
  })

  it('the Projects menu marks a saved demo run and names the model of a live one', async () => {
    vi.mocked(api.listProjects).mockResolvedValue({ total: 2, projects: [
      { design_id: 'p1', prompt: 'a', module_name: 'counter', status: 'PASS', created_at: 1763550000, iterations: 0, model: 'offline demo', demo: true },
      { design_id: 'p2', prompt: 'b', module_name: 'fifo', status: 'PASS', created_at: 1763550000, iterations: 1, model: 'opencode/hy4-flash-free', demo: false },
    ] })
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('button', { name: /Projects/ }))
    expect(await screen.findByText('demo')).toBeInTheDocument()
    expect(screen.getByText(/opencode\/hy4-flash-free/)).toBeInTheDocument()
  })

  it('a double click on Export UVM starts one export', async () => {
    let release: (v: unknown) => void = () => {}
    vi.mocked(api.exportUVM).mockImplementation(() => new Promise((r) => { release = r }) as never)
    render(<App />); await ready(); type(); generate()
    await screen.findByTestId('verdict-badge')
    const btn = screen.getByRole('button', { name: 'Export UVM bundle' })
    fireEvent.click(btn); fireEvent.click(btn)
    expect(api.exportUVM).toHaveBeenCalledTimes(1)
    release({ module_name: 'counter', file_count: 1, note: '' })
  })

  it('a new run that fails after its RTL arrives cannot re-run the new RTL with the old testbench', async () => {
    vi.mocked(api.streamDesign).mockImplementationOnce(async (_p, onEvent) => {
      onEvent({ stage: 'done', message: 'done', status: 'PASS', response: done({ design_id: 'old1' }) } as never)
    }).mockImplementationOnce(async (_p, onEvent) => {
      onEvent({ stage: 'rtl', message: 'rtl', rtl_code: 'module counter; // NEW\nendmodule' } as never)
      onEvent({ stage: 'error', message: 'The testbench model you chose could not be used' } as never)
    })
    vi.mocked(api.reSimulate).mockResolvedValue({ ...sim(), waveform: null } as never)
    render(<App />); await ready(); type(); generate()
    await screen.findByTestId('verdict-badge')
    generate()
    await screen.findByText(/testbench model you chose/)
    const rerun = screen.getByRole('button', { name: /Re-run/ })
    if (!(rerun as HTMLButtonElement).disabled) fireEvent.click(rerun)
    for (const call of vi.mocked(api.reSimulate).mock.calls) expect(call[0]).not.toBe('old1')   // never the old design id + old testbench
  })

  it('the specification review sits in its own scrollable pane', async () => {
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /Review the specification/ }))
    type(); generate()
    const review = await screen.findByRole('region', { name: 'Review the specification' })
    expect(review.closest('main')).toHaveClass('spec-pane')     // .spec-pane { overflow-y: auto } (a long spec hid the Generate button)
  })

  it('a disputed PASS from the server is shown as disputed', async () => {
    vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
      onEvent({ stage: 'done', message: 'done', status: 'PASS', response: done({ pass_disputed: 'The original testbench still fails the final design.' }) } as never)
    })
    render(<App />); await ready(); type(); generate()
    expect(await screen.findByTestId('verdict-badge')).toHaveTextContent('PASS, disputed')
  })

  it('an unreachable server is reported as such, with a retry, not as an offline mode', async () => {
    vi.mocked(api.getModels).mockRejectedValueOnce(new Error('Failed to fetch')).mockResolvedValue(modelsResponse)
    render(<App />)
    expect(await screen.findByText('Server not reachable')).toBeInTheDocument()
    expect(screen.queryByText('Offline demo')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await ready()
    expect(screen.queryByText('Server not reachable')).toBeNull()
  })
})
