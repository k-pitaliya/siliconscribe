import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import TestCasesView from '../TestCasesView'
import type { CheckResult, SimulationResult } from '../../types'

const row = (idx: number, over: Partial<CheckResult> = {}): CheckResult => ({
  idx, status: 'PASS', category: 'directed', name: `check_${idx}`, t: idx * 10_000,
  expected: '4', actual: '4', detail: '', source: 'chk', ...over,
})

function result(over: Partial<SimulationResult> = {}): SimulationResult {
  const checks = [
    row(1, { category: 'reset', name: 'power_up_reset' }),
    row(2, { category: 'directed', name: 'count_up_to_1', expected: '1', actual: '1' }),
    row(3, { category: 'directed', name: 'count_up_to_2', status: 'FAIL', expected: '2', actual: '4' }),
    row(4, { category: 'hold', name: 'enable_low_holds' }),
  ]
  return {
    status: 'FAIL', module_name: 'counter', simulation_time_ns: 100, test_count: 4, pass_count: 3, fail_count: 1,
    coverage: { pass_rate: 75 }, errors: [], waveform_file: null, transcript_file: null, log_excerpt: '',
    checks, checks_source: 'structured', checks_consistent: true, checks_truncated: false, checks_total_logged: 4,
    check_groups: [
      { category: 'reset', total: 1, passed: 1, failed: 0 },
      { category: 'directed', total: 2, passed: 1, failed: 1 },
      { category: 'hold', total: 1, passed: 1, failed: 0 },
    ],
    ...over,
  } as SimulationResult
}

describe('TestCasesView', () => {
  it('summarises totals and lists every test type with its pass ratio', () => {
    render(<TestCasesView result={result()} />)
    expect(screen.getByText('3 passed')).toBeInTheDocument()
    expect(screen.getByText('1 failed')).toBeInTheDocument()
    expect(screen.getByText(/of 4 checks/)).toBeInTheDocument()
    const chips = screen.getByRole('group', { name: 'Test types' })
    expect(within(chips).getByText('reset')).toBeInTheDocument()
    expect(within(chips).getByText('1/2')).toBeInTheDocument() // directed: 1 of 2 passed
    expect(screen.getAllByTestId('check-row')).toHaveLength(4)
  })

  it('shows which checks failed and in what way', () => {
    render(<TestCasesView result={result()} />)
    const failing = screen.getAllByTestId('check-row').find((r) => r.textContent?.includes('count_up_to_2'))!
    expect(failing.className).toContain('fail')
    expect(failing.textContent).toContain('FAIL')
    expect(failing.textContent).toContain('0x2')
    expect(failing.textContent).toContain('0x4')
  })

  it('filters by result, by test type, and by search text', () => {
    render(<TestCasesView result={result()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Failed' }))
    expect(screen.getAllByTestId('check-row')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'All' }))

    fireEvent.click(within(screen.getByRole('group', { name: 'Test types' })).getByText('directed'))
    expect(screen.getAllByTestId('check-row')).toHaveLength(2)

    fireEvent.change(screen.getByLabelText('Search tests'), { target: { value: 'up_to_2' } })
    expect(screen.getAllByTestId('check-row')).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('Search tests'), { target: { value: 'zzz' } })
    expect(screen.getByText(/No checks match/)).toBeInTheDocument()
  })

  it('explains a failure bit by bit and can jump to the waveform at that time', () => {
    const onShow = vi.fn()
    render(<TestCasesView result={result()} timescalePs={1} onShowInWaveform={onShow} />)
    fireEvent.click(screen.getAllByTestId('check-row').find((r) => r.textContent?.includes('count_up_to_2'))!)
    const detail = screen.getByTestId('check-detail')
    expect(detail.textContent).toContain('differing bits: 2, 1') // 0b0010 vs 0b0100
    fireEvent.click(within(detail).getByRole('button', { name: /Show in waveform/ }))
    expect(onShow).toHaveBeenCalledWith(30_000)
  })

  it('switches the number format of expected and actual values', () => {
    render(<TestCasesView result={result()} />)
    fireEvent.change(screen.getByLabelText('Value format'), { target: { value: 'dec' } })
    const failing = screen.getAllByTestId('check-row').find((r) => r.textContent?.includes('count_up_to_2'))!
    expect(failing.textContent).toContain('2')
    expect(failing.textContent).not.toContain('0x')
  })

  it('only renders a window of a very large list', () => {
    const many = Array.from({ length: 1000 }, (_, i) => row(i + 1))
    render(<TestCasesView result={result({ checks: many, test_count: 1000, pass_count: 1000, fail_count: 0,
      check_groups: [{ category: 'directed', total: 1000, passed: 1000, failed: 0 }] })} />)
    expect(screen.getAllByTestId('check-row').length).toBeLessThan(100)
    expect(screen.getByText('1000 shown')).toBeInTheDocument()
  })

  it('says plainly when only the totals are known', () => {
    render(<TestCasesView result={result({ checks: [], check_groups: [], checks_source: 'none' })} />)
    expect(screen.getByTestId('tests-empty')).toBeInTheDocument()
    expect(screen.getByText(/did not log its individual checks/)).toBeInTheDocument()
    expect(screen.queryByTestId('check-row')).toBeNull()
  })

  it('is honest about a legacy testbench that only reports failures', () => {
    render(<TestCasesView result={result({ checks_source: 'legacy' })} />)
    expect(screen.getByTestId('legacy-note').textContent).toContain('only the failing checks are listed')
  })

  it('warns when the logged checks disagree with the testbench summary', () => {
    render(<TestCasesView result={result({ checks_consistent: false, pass_count: 10, fail_count: 0, test_count: 10 })} />)
    expect(screen.getByTestId('inconsistent-note').textContent).toContain('summary decides the verdict')
  })

  it('says when the list is truncated, while the totals stay exact', () => {
    render(<TestCasesView result={result({ checks_truncated: true, checks_total_logged: 2122, test_count: 2122, pass_count: 2118 })} />)
    expect(screen.getByTestId('truncated-note').textContent).toContain('Showing 4 of 2122')
  })
})

describe('TestCasesView keyboard (self-review finding)', () => {
  it('has one tab stop and moves with the arrow keys, also beyond the rendered window', async () => {
    const checks = Array.from({ length: 300 }, (_, i) => row(i + 1, { category: 'random' }))
    render(<TestCasesView result={result({ checks, check_groups: [{ category: 'random', total: 300, passed: 300, failed: 0 }],
      test_count: 300, pass_count: 300, fail_count: 0, status: 'PASS' })} />)
    const rows = screen.getAllByTestId('check-row')
    expect(rows.filter((r) => r.getAttribute('tabindex') === '0')).toHaveLength(1)
    rows[0].focus()
    fireEvent.keyDown(rows[0], { key: 'End' })
    await waitFor(() => expect(document.activeElement?.getAttribute('data-idx')).toBe('300'))
  })
})

describe('TestCasesView for a run stopped before its summary', () => {
  it('counts the logged checks and labels them as progress, not a verdict', () => {
    render(<TestCasesView result={result({ status: 'TIMEOUT', test_count: 0, pass_count: 0, fail_count: 0 })} />)
    expect(screen.getByText('3 passed')).toBeInTheDocument()
    expect(screen.getByText(/of 4 checks/)).toBeInTheDocument()
    expect(screen.getByTestId('unfinished-note').textContent).toMatch(/stopped before the testbench finished/)
    expect(screen.queryByTestId('inconsistent-note')).not.toBeInTheDocument()
  })

  it('does not show the note for a finished run', () => {
    render(<TestCasesView result={result()} />)
    expect(screen.queryByTestId('unfinished-note')).not.toBeInTheDocument()
  })
})
