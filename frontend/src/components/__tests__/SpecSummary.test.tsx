import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import SpecSummary from '../SpecSummary'
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

describe('SpecSummary', () => {
  it('shows the module name, port names and behaviour text', () => {
    render(<SpecSummary spec={spec} />)
    expect(screen.getByText('counter')).toBeInTheDocument()
    expect(screen.getByText('clk')).toBeInTheDocument()
    expect(screen.getByText('count')).toBeInTheDocument()
    expect(screen.getByText('Counts up on every clock edge.')).toBeInTheDocument()
  })

  it('lists constraints as list items', () => {
    render(<SpecSummary spec={spec} />)
    const items = screen.getAllByRole('listitem').map((li) => li.textContent)
    expect(items).toEqual(['async active-low reset', 'wraps at 15'])
  })

  it('renders no list when there are no constraints', () => {
    render(<SpecSummary spec={{ ...spec, constraints: [] }} />)
    expect(screen.queryByRole('list')).toBeNull()
    expect(screen.queryByRole('listitem')).toBeNull()
  })

  it('is closed by default', () => {
    render(<SpecSummary spec={spec} />)
    const details = screen.getByTestId('spec-summary')
    expect(details.tagName).toBe('DETAILS')
    expect(details).not.toHaveAttribute('open')
    expect(screen.getByText('Specification the design was built from')).toBeInTheDocument()
  })

  it('does not crash on a specification with missing lists (older saved projects)', () => {
    const partial = { module_name: 'counter' } as unknown as RTLDesignSpec
    render(<SpecSummary spec={partial} />)
    expect(screen.getByText('counter')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
  })
})
