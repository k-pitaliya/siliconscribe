import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import SpecReview from '../SpecReview'
import type { RTLDesignSpec } from '../../types'

const spec: RTLDesignSpec = {
  module_name: 'counter',
  parameters: [{ name: 'WIDTH', type: 'integer', default: 4 }],
  ports: [
    { name: 'clk', direction: 'input', width: 1, description: 'Clock' },
    { name: 'count', direction: 'output', width: 4, description: 'Count' },
  ],
  behavior: 'Counts up on every clock edge.',
  constraints: ['async active-low reset', 'wraps at 15'],
}

function renderReview(overrides: Partial<{ busy: boolean }> = {}) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(<SpecReview spec={spec} onConfirm={onConfirm} onCancel={onCancel} {...overrides} />)
  return { onConfirm, onCancel }
}

describe('SpecReview', () => {
  it('shows the module name, every port and the parameters', () => {
    renderReview()
    expect(screen.getByRole('region', { name: 'Review the specification' })).toBeInTheDocument()
    expect(screen.getByText('counter')).toBeInTheDocument()

    const table = screen.getByRole('table')
    expect(table.querySelector('caption')).toHaveTextContent('Ports')
    const rows = Array.from(table.querySelectorAll('tbody tr')).map((tr) =>
      Array.from(tr.querySelectorAll('td')).map((td) => td.textContent),
    )
    expect(rows).toEqual([
      ['clk', 'input', '1', 'Clock'],
      ['count', 'output', '4', 'Count'],
    ])

    expect(screen.getByText('WIDTH = 4')).toBeInTheDocument()
  })

  it('fills the Behaviour and Constraints textareas from the spec', () => {
    renderReview()
    expect(screen.getByRole('textbox', { name: 'Behaviour' })).toHaveValue('Counts up on every clock edge.')
    expect(screen.getByRole('textbox', { name: 'Constraints (one per line)' })).toHaveValue(
      'async active-low reset\nwraps at 15',
    )
  })

  it('confirms the edited behaviour and parsed constraints, leaving module, ports and parameters unchanged', () => {
    const { onConfirm } = renderReview()
    fireEvent.change(screen.getByRole('textbox', { name: 'Behaviour' }), {
      target: { value: 'Counts down on every clock edge.' },
    })
    fireEvent.change(screen.getByRole('textbox', { name: 'Constraints (one per line)' }), {
      target: { value: '  first rule  \n\n   \nsecond rule\n' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Generate with this specification' }))

    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onConfirm).toHaveBeenCalledWith({
      module_name: 'counter',
      parameters: [{ name: 'WIDTH', type: 'integer', default: 4 }],
      ports: spec.ports,
      behavior: 'Counts down on every clock edge.',
      constraints: ['first rule', 'second rule'],
    })
  })

  it('keeps at most 30 constraints when given 31 non-empty lines', () => {
    const { onConfirm } = renderReview()
    const lines = Array.from({ length: 31 }, (_, i) => `rule ${i + 1}`).join('\n')
    fireEvent.change(screen.getByRole('textbox', { name: 'Constraints (one per line)' }), {
      target: { value: lines },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Generate with this specification' }))

    const confirmed = onConfirm.mock.calls[0][0] as RTLDesignSpec
    expect(confirmed.constraints).toHaveLength(30)
    expect(confirmed.constraints[29]).toBe('rule 30')
  })

  it('cuts a 600-character constraint line to 500 characters', () => {
    const { onConfirm } = renderReview()
    fireEvent.change(screen.getByRole('textbox', { name: 'Constraints (one per line)' }), {
      target: { value: 'a'.repeat(600) },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Generate with this specification' }))

    const confirmed = onConfirm.mock.calls[0][0] as RTLDesignSpec
    expect(confirmed.constraints).toHaveLength(1)
    expect(confirmed.constraints[0]).toBe('a'.repeat(500))
  })

  it('Cancel calls onCancel', () => {
    const { onCancel, onConfirm } = renderReview()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('disables both buttons when busy', () => {
    renderReview({ busy: true })
    expect(screen.getByRole('button', { name: 'Generate with this specification' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })

  it('gives the textareas the accessible names Behaviour and Constraints (one per line)', () => {
    renderReview()
    expect(screen.getByRole('textbox', { name: 'Behaviour' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Constraints (one per line)' })).toBeInTheDocument()
  })

  it('cuts a behaviour text longer than the server accepts instead of letting the run be refused', () => {
    const onConfirm = vi.fn()
    render(<SpecReview spec={{ ...spec, behavior: 'b'.repeat(4500) }} onConfirm={onConfirm} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Generate with this specification' }))
    expect(onConfirm.mock.calls[0][0].behavior).toHaveLength(4000)
  })

  it('does not crash on a specification with missing lists and still confirms', () => {
    const onConfirm = vi.fn()
    render(<SpecReview spec={{ module_name: 'counter' } as unknown as RTLDesignSpec} onConfirm={onConfirm} onCancel={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Generate with this specification' }))
    expect(onConfirm.mock.calls[0][0]).toMatchObject({ module_name: 'counter', behavior: '', constraints: [] })
  })
})
