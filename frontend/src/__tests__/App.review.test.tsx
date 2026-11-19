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

describe('App: reviewing the specification first', () => {
  it('does not review by default: Generate runs straight away without a spec', async () => {
    render(<App />); await ready(); type(); generate()
    await waitFor(() => expect(api.streamDesign).toHaveBeenCalled())
    expect(api.parseSpec).not.toHaveBeenCalled()
    expect(vi.mocked(api.streamDesign).mock.calls[0][0].spec).toBeUndefined()
  })

  it('shows the parsed specification and generates nothing until it is confirmed', async () => {
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /Review the specification/ }))
    type(); generate()
    expect(await screen.findByRole('region', { name: 'Review the specification' })).toBeInTheDocument()
    expect(api.parseSpec).toHaveBeenCalledWith('Design a counter', 'opencode/deepseek-v4.1-flash-free', undefined)
    expect(api.streamDesign).not.toHaveBeenCalled()
    expect(screen.getByText('counter')).toBeInTheDocument()
  })

  it('runs with exactly the specification the user edited', async () => {
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /Review the specification/ }))
    type(); generate()
    await screen.findByRole('region', { name: 'Review the specification' })
    fireEvent.change(screen.getByLabelText('Behaviour'), { target: { value: 'EDITED: wraps at 15.' } })
    fireEvent.change(screen.getByLabelText('Constraints (one per line)'), { target: { value: 'first\n\n second ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate with this specification' }))
    await waitFor(() => expect(api.streamDesign).toHaveBeenCalled())
    const sent = vi.mocked(api.streamDesign).mock.calls[0][0].spec!
    expect(sent.behavior).toBe('EDITED: wraps at 15.')
    expect(sent.constraints).toEqual(['first', 'second'])
    expect(sent.module_name).toBe('counter')
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Review the specification' })).toBeNull())
  })

  it('cancelling the review runs nothing and brings the results back', async () => {
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /Review the specification/ }))
    type(); generate()
    await screen.findByRole('region', { name: 'Review the specification' })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('region', { name: 'Review the specification' })).toBeNull()
    expect(api.streamDesign).not.toHaveBeenCalled()
  })

  it('says why when the specification could not be read, and does not start a run', async () => {
    vi.mocked(api.parseSpec).mockRejectedValue(new Error('The AI model did not answer in time.'))
    render(<App />); await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /Review the specification/ }))
    type(); generate()
    expect(await screen.findByText(/Could not read the specification: The AI model did not answer in time\./)).toBeInTheDocument()
    expect(api.streamDesign).not.toHaveBeenCalled()
  })

  it('remembers the choice to review', async () => {
    const first = render(<App />); await ready()
    fireEvent.click(screen.getByRole('checkbox', { name: /Review the specification/ }))
    first.unmount()
    render(<App />); await ready()
    expect(screen.getByRole('checkbox', { name: /Review the specification/ })).toBeChecked()
  })
})

describe('App: a separate model for the testbench', () => {
  it('sends it with the run and remembers it for next time', async () => {
    const first = render(<App />); await ready()
    fireEvent.change(screen.getByRole('combobox', { name: 'Testbench written by' }), { target: { value: 'nim/poolside/laguna-xs-2.1' } })
    type(); generate()
    await waitFor(() => expect(api.streamDesign).toHaveBeenCalled())
    expect(vi.mocked(api.streamDesign).mock.calls[0][0].testbench_model).toBe('nim/poolside/laguna-xs-2.1')
    first.unmount()
    render(<App />); await ready()
    expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toHaveValue('nim/poolside/laguna-xs-2.1')
  })

  it('falls back to the same model when the remembered testbench model is no longer offered', async () => {
    window.localStorage.setItem('ss-tb-model', 'nim/poolside/laguna-xs-2.1')
    vi.mocked(api.getModels).mockResolvedValue({ ...modelsResponse, models: [MODELS[0]] })      // NIM went away
    render(<App />); await ready()
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toHaveValue(''))
  })

  it('sends nothing extra when the same model writes both', async () => {
    render(<App />); await ready(); type(); generate()
    await waitFor(() => expect(api.streamDesign).toHaveBeenCalled())
    expect(vi.mocked(api.streamDesign).mock.calls[0][0].testbench_model).toBeUndefined()
  })

  it('names the testbench model on the result when it was independent, and shows the second opinion', async () => {
    vi.mocked(api.streamDesign).mockImplementation(async (_p, onEvent) => {
      onEvent({ stage: 'done', message: 'done', status: 'PASS', response: done({ testbench_model: 'nim/poolside/laguna-xs-2.1', independent_testbench: true,
        second_opinion: { status: 'FAIL', pass_count: 90, fail_count: 10, test_count: 100, model: 'nim/poolside/laguna-xs-2.1', note: '' } }) } as never)
    })
    render(<App />); await ready(); type(); generate()
    expect(await screen.findByTestId('model-used')).toHaveTextContent('Testbench written by nim/poolside/laguna-xs-2.1, a separate model')
    expect(screen.getByTestId('second-opinion')).toHaveTextContent('Second opinion disagrees')
    expect(screen.getByTestId('spec-summary')).toBeInTheDocument()
  })
})
