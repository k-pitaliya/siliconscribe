import { render, screen, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import AgentChat, { formatElapsed } from '../AgentChat'

const msgs = (n: number) => Array.from({ length: n }, (_, i) => ({ role: 'ai' as const, text: `step ${i}`, stage: 'rtl' }))

describe('formatElapsed', () => {
  it('shows seconds, then minutes and zero-padded seconds', () => {
    expect(formatElapsed(0)).toBe('0s')
    expect(formatElapsed(59)).toBe('59s')
    expect(formatElapsed(60)).toBe('1m 00s')
    expect(formatElapsed(193)).toBe('3m 13s')
  })
})

describe('AgentChat run timer', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('counts the time since the last update and the total, and restarts the step clock on a new message', () => {
    const { rerender } = render(<AgentChat messages={msgs(1)} running explanation="" />)
    act(() => { vi.advanceTimersByTime(65_000) })
    expect(screen.getByTestId('run-timer').textContent).toContain('1m 05s since the last update, 1m 05s total')

    rerender(<AgentChat messages={msgs(2)} running explanation="" />) // a stage finished
    act(() => { vi.advanceTimersByTime(3_000) })
    expect(screen.getByTestId('run-timer').textContent).toContain('3s since the last update, 1m 08s total')
  })

  it('tells the user a slow step is normal for free models, but not at the start', () => {
    render(<AgentChat messages={msgs(1)} running explanation="" />)
    act(() => { vi.advanceTimersByTime(10_000) })
    expect(screen.getByTestId('run-timer').textContent).not.toContain('Free models')
    act(() => { vi.advanceTimersByTime(40_000) })
    expect(screen.getByTestId('run-timer').textContent).toContain('Free models can take a few minutes per step.')
  })

  it('keeps the ticking clock out of the screen-reader live region announcements', () => {
    render(<AgentChat messages={msgs(1)} running explanation="" />)
    const clock = screen.getByTestId('run-timer').querySelector('[aria-hidden="true"]')
    expect(clock?.textContent).toContain('since the last update')
  })

  it('shows no timer when nothing is running', () => {
    render(<AgentChat messages={msgs(1)} running={false} explanation="" />)
    expect(screen.queryByTestId('run-timer')).toBeNull()
  })
})
