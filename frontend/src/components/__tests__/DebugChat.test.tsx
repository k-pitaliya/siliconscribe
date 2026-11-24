import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { AgentEvent, SimulationRerun, Waveform } from '../../types'

const { askAgent } = vi.hoisted(() => ({ askAgent: vi.fn() }))
vi.mock('../../api', () => ({ askAgent }))

import DebugChat from '../DebugChat'

const waveform = { timescale: '1ps', timescale_ps: 1, end_time: 100000, signals: [] } as unknown as Waveform
const run = { status: 'FAIL', pass_count: 9, fail_count: 48, test_count: 57 } as unknown as SimulationRerun

function setup(events: AgentEvent[], props: Partial<Parameters<typeof DebugChat>[0]> = {}) {
  askAgent.mockImplementation(async (_p: unknown, onEvent: (e: AgentEvent) => void) => { events.forEach(onEvent) })
  const handlers = { onShowTime: vi.fn(), onApplyFix: vi.fn(), onEvidenceRun: vi.fn() }
  render(<DebugChat rtl="module c; endmodule" tb="module testbench; endmodule" busy={false} waveform={waveform} {...handlers} {...props} />)
  return handlers
}

const tool: AgentEvent = { type: 'tool', tool: 'cycle_table', args: { signals: ['count'], from_ns: 0, to_ns: 50 }, thought: 'look at the first cycles', ok: true, summary: 'posedge', result: 'cycle | time\n1 | 15ns | 4\'h0 (0) -> 4\'h2 (2)' }
const answer = (extra: Partial<Extract<AgentEvent, { type: 'answer' }>> = {}): AgentEvent => ({
  type: 'answer', text: '`count` jumps to 2 @15ns.\n\nLine 14 adds **2**.', suspect: 'design', confidence: 'high', fix: null, rule_based: false, steps: 2, model: 'opencode/m', ...extra,
})

describe('DebugChat', () => {
  beforeEach(() => { askAgent.mockReset() }) // braces: a returned function would be run as a cleanup hook

  it('sends the question with the editor code and shows the evidence steps and the answer', async () => {
    const h = setup([{ type: 'status', message: 'Simulating…' }, { type: 'run', result: run }, tool, answer()])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    await screen.findByTestId('agent-answer')
    expect(askAgent.mock.calls[0][0]).toMatchObject({ rtl_code: 'module c; endmodule', testbench_code: 'module testbench; endmodule', question: 'Why did the first check fail?', history: [] })
    expect(h.onEvidenceRun).toHaveBeenCalledWith(run, 'module c; endmodule', 'module testbench; endmodule')
    expect(screen.getByText(/Built a cycle-by-cycle table/)).toBeTruthy()
    expect(screen.getByText('AI answer')).toBeTruthy()
    expect(screen.getByText('opencode/m')).toBeTruthy()
    expect(screen.getByText('Design')).toBeTruthy()
    expect(screen.getByText('count').tagName).toBe('CODE')
    expect(screen.getByText('2').tagName).toBe('STRONG')
  })

  it('turns a cited time into a waveform jump in VCD ticks', async () => {
    const h = setup([answer()])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    fireEvent.click(await screen.findByRole('button', { name: '@15ns' }))
    expect(h.onShowTime).toHaveBeenCalledWith(15000) // 1 tick = 1 ps
  })

  it('also links a time written without the @, and leaves other numbers alone', async () => {
    const h = setup([answer({ text: 'At 25ns and 1.5 ns the count is 4; period 10ns; 4ns2 is not a time.' })])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    fireEvent.click(await screen.findByRole('button', { name: '25ns' }))
    fireEvent.click(screen.getByRole('button', { name: '1.5 ns' }))
    expect(h.onShowTime.mock.calls).toEqual([[25000], [1500]])
    expect(screen.queryByRole('button', { name: '4' })).toBeNull()
    expect(screen.queryByRole('button', { name: /4ns2/ })).toBeNull()
  })

  it('shows the server verdict of a fix and applies it on request', async () => {
    const fix = { file: 'rtl' as const, code: 'module fixed; endmodule', status: 'PASS' as const, pass_count: 57, fail_count: 0, test_count: 57, summary: '' }
    const h = setup([answer({ fix })])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    const card = await screen.findByTestId('agent-fix')
    expect(card.textContent).toContain('the server re-simulated it, PASS (57 of 57 checks passed)')
    fireEvent.click(screen.getByRole('button', { name: 'Apply to the editor' }))
    expect(h.onApplyFix).toHaveBeenCalledWith('rtl', 'module fixed; endmodule')
    expect((screen.getByRole('button', { name: 'Applied to the editor' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('warns that a testbench fix changes the checker, and shows a failing fix as failing', async () => {
    const fix = { file: 'testbench' as const, code: 'module testbench; endmodule', status: 'FAIL' as const, pass_count: 3, fail_count: 2, test_count: 5, summary: 'Server re-simulation: FAIL' }
    setup([answer({ fix })])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    const card = await screen.findByTestId('agent-fix')
    expect(card.className).toContain('bad')
    expect(card.textContent).toContain('changes the checker itself')
  })

  it('labels rule-based evidence as not AI', async () => {
    setup([answer({ rule_based: true, model: null, text: '**No AI model is connected.** evidence' })])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    expect(await screen.findByText('Rule-based evidence (no AI)')).toBeTruthy()
  })

  it('shows an error event and keeps earlier answers as history for the next question', async () => {
    setup([answer()])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    await screen.findByTestId('agent-answer')
    askAgent.mockImplementation(async (_p: unknown, onEvent: (e: AgentEvent) => void) => onEvent({ type: 'error', message: 'quota reached' }))
    const box = screen.getByLabelText('Question about this run')
    fireEvent.change(box, { target: { value: 'and why line 14?' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect((await screen.findByRole('alert')).textContent).toBe('quota reached')
    expect(askAgent.mock.calls[1][0].history).toEqual([{ question: 'Why did the first check fail?', answer: '`count` jumps to 2 @15ns.\n\nLine 14 adds **2**.' }])
  })

  it('renders model text as text, never as HTML', async () => {
    setup([answer({ text: '<img src=x onerror="alert(1)"> done' })])
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    const ans = await screen.findByTestId('agent-answer')
    expect(ans.querySelector('img')).toBeNull()
    expect(ans.textContent).toContain('<img src=x')
  })

  it('waits while a generation is running', () => {
    setup([], { busy: true })
    expect((screen.getByLabelText('Question about this run') as HTMLTextAreaElement).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    expect(askAgent).not.toHaveBeenCalled()
  })

  it('reports a failed request', async () => {
    askAgent.mockRejectedValue(new Error('Rate limit exceeded.'))
    render(<DebugChat rtl="a" tb="b" busy={false} waveform={null} onShowTime={vi.fn()} onApplyFix={vi.fn()} onEvidenceRun={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Why did the first check fail?' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('Rate limit exceeded.'))
  })
})
