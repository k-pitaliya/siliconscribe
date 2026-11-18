import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { ModelInfo, ModelsResponse, RunResponse, SimulationResult } from '../types'

vi.mock('../api', () => ({
  getModels: vi.fn(),
  streamDesign: vi.fn(),
  reSimulate: vi.fn(),
  exportUVM: vi.fn(),
  listProjects: vi.fn(),
  deleteProject: vi.fn(),
  getProject: vi.fn(),
}))
vi.mock('../components/CodeEditor', () => ({ default: () => <div data-testid="editor" /> }))

import App from '../App'
import * as api from '../api'

const m = (id: string, over: Partial<ModelInfo> = {}): ModelInfo => ({
  id, label: id.split('/').slice(1).join('/') || id, note: '', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: true, ...over,
})
const FREE = [m('opencode/deepseek-v4.1-flash-free', { note: 'Marked free by its name' }), m('opencode/beam-free'), m('opencode/hy4-flash-free')]
const OTHER = [m('opencode/gpt-5.5', { free: null }), m('nvidia/x/y', { free: null, provider: 'nvidia', group: 'NVIDIA' })]
const CF = [m('@cf/openai/gpt-oss-120b', { provider: 'cloudflare', group: 'Cloudflare Workers AI', free: null })]

const response = (over: Partial<ModelsResponse> = {}): ModelsResponse => ({
  offline: false, current: 'opencode/deepseek-v4.1-flash-free', models: FREE, paid_hidden: 2,
  providers: [{ id: 'opencode', label: 'OpenCode', available: true, count: 3 },
    { id: 'cloudflare', label: 'Cloudflare', available: false, count: 0, hint: 'Cloudflare is not set up. Set CLOUDFLARE_ACCOUNT_ID.' }],
  ...over,
})

const simResult = (): SimulationResult => ({
  status: 'PASS', module_name: 'counter', simulation_time_ns: 100, test_count: 8, pass_count: 8, fail_count: 0,
  coverage: { pass_rate: 100 }, errors: [], waveform_file: null, transcript_file: null, log_excerpt: '',
})
const run = (model: string | null) => ({
  design_id: 'd1', status: 'PASS', rtl_code: 'module counter; endmodule', testbench_code: 'module testbench; endmodule', explanation: 'x',
  rtl_spec: { module_name: 'counter', ports: [], parameters: [] }, result: simResult(), waveform: null, schematic: null,
  iteration_history: [], iterations: 0, fallback_notice: null, model,
}) as unknown as RunResponse

beforeEach(() => {
  vi.clearAllMocks()
  window.localStorage.clear()
  vi.mocked(api.getModels).mockResolvedValue(response())
  vi.mocked(api.listProjects).mockResolvedValue({ total: 0, projects: [] })
  vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
    onEvent({ stage: 'done', message: 'done', status: 'PASS', response: run('opencode/deepseek-v4.1-flash-free') } as never)
  })
})

const picker = () => screen.findByRole('combobox', { name: 'Model' })
async function generate() {
  fireEvent.change(screen.getByLabelText('Describe the block'), { target: { value: 'Design a counter' } })
  fireEvent.click(screen.getByRole('button', { name: /Generate RTL/ }))
  await waitFor(() => expect(api.streamDesign).toHaveBeenCalled())
}

describe('App: the model menu', () => {
  it('starts on the server default and lists the free OpenCode models', async () => {
    render(<App />)
    const select = await picker()
    expect(select).toHaveValue('opencode/deepseek-v4.1-flash-free')
    expect(within(select).getAllByRole('option')).toHaveLength(3)
    expect(screen.getByText(/Show other models \(2 hidden\)/)).toBeInTheDocument()
    expect(api.getModels).toHaveBeenCalledWith({ includePaid: false, refresh: false })
  })

  it('sends the chosen model with the run and remembers it for next time', async () => {
    const first = render(<App />)
    fireEvent.change(await picker(), { target: { value: 'opencode/hy4-flash-free' } })
    await generate()
    expect(vi.mocked(api.streamDesign).mock.calls[0][0].model).toBe('opencode/hy4-flash-free')
    first.unmount()
    render(<App />)
    expect(await picker()).toHaveValue('opencode/hy4-flash-free')                  // restored
  })

  it('falls back to the server default when the remembered model is no longer offered', async () => {
    window.localStorage.setItem('ss-model', '@cf/openai/gpt-oss-120b')              // Cloudflare was set up before, not now
    render(<App />)
    expect(await picker()).toHaveValue('opencode/deepseek-v4.1-flash-free')
  })

  it('"Show other models" asks the server for them and the choice is remembered', async () => {
    vi.mocked(api.getModels).mockImplementation(async (o) => response(o?.includePaid ? { models: [...FREE, ...OTHER], paid_hidden: 0 } : {}))
    const first = render(<App />)
    await picker()
    fireEvent.click(screen.getByRole('checkbox', { name: /Show other models/ }))
    await waitFor(() => expect(within(screen.getByRole('combobox', { name: 'Model' })).getAllByRole('option')).toHaveLength(5))
    expect(api.getModels).toHaveBeenLastCalledWith({ includePaid: true, refresh: false })
    expect(screen.getByText(/may use credits/)).toBeInTheDocument()
    first.unmount()
    render(<App />)
    await waitFor(() => expect(api.getModels).toHaveBeenLastCalledWith({ includePaid: true, refresh: false }))
  })

  it('the refresh button re-reads the lists from the server', async () => {
    render(<App />)
    await picker()
    fireEvent.click(screen.getByRole('button', { name: 'Refresh model list' }))
    await waitFor(() => expect(api.getModels).toHaveBeenLastCalledWith({ includePaid: false, refresh: true }))
  })

  it('switches to a Cloudflare model when Cloudflare is set up, and sends its id', async () => {
    vi.mocked(api.getModels).mockResolvedValue(response({
      models: [...FREE, ...CF], providers: [{ id: 'opencode', label: 'OpenCode', available: true, count: 3 }, { id: 'cloudflare', label: 'Cloudflare', available: true, count: 1 }],
    }))
    render(<App />)
    await picker()
    fireEvent.click(screen.getByRole('radio', { name: 'Cloudflare' }))
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Model' })).toHaveValue('@cf/openai/gpt-oss-120b'))
    await generate()
    expect(vi.mocked(api.streamDesign).mock.calls[0][0].model).toBe('@cf/openai/gpt-oss-120b')
  })

  it('says how to set Cloudflare up when it is not, instead of offering models that cannot run', async () => {
    render(<App />)
    await picker()
    fireEvent.click(screen.getByRole('radio', { name: 'Cloudflare' }))
    expect(screen.getByText(/Cloudflare is not set up/)).toHaveAttribute('role', 'status')
    expect(screen.queryByRole('combobox', { name: 'Model' })).toBeNull()
  })
})

describe('App: which model wrote the result', () => {
  it('names the model on the result, and not for the scripted offline demo', async () => {
    const first = render(<App />)
    await picker()
    await generate()
    expect(await screen.findByTestId('model-used')).toHaveTextContent('Written by opencode/deepseek-v4.1-flash-free')
    first.unmount()
    vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
      onEvent({ stage: 'done', message: 'done', status: 'PASS', response: run('offline demo') } as never)
    })
    render(<App />)
    await picker()
    await generate()
    await waitFor(() => expect(screen.getByText('PASS')).toBeInTheDocument())
    expect(screen.queryByTestId('model-used')).toBeNull()
  })
})
