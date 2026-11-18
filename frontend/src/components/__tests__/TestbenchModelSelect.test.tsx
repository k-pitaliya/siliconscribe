import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import TestbenchModelSelect from '../TestbenchModelSelect'
import type { ModelInfo } from '../../types'

const models: ModelInfo[] = [
  { id: 'opencode/big-pickle', label: 'big-pickle', note: '', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: true },
  { id: 'opencode-go/kimi-k3', label: 'kimi-k3', note: '', tag: 'balanced', provider: 'opencode-go', group: 'OpenCode Go', free: false },
  { id: '@cf/openai/gpt-oss-120b', label: 'gpt-oss-120b', note: '', tag: 'balanced', provider: 'cloudflare', group: 'Cloudflare Workers AI', free: null },
]

function renderSelect(overrides: Partial<{ value: string; disabled: boolean }> = {}) {
  const onChange = vi.fn()
  render(<TestbenchModelSelect models={models} value="" onChange={onChange} {...overrides} />)
  return { onChange }
}

describe('TestbenchModelSelect', () => {
  it('has the accessible name "Testbench written by"', () => {
    renderSelect()
    expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toBeInTheDocument()
  })

  it('first option is "Same model as the design" with an empty value', () => {
    renderSelect()
    const select = screen.getByRole('combobox', { name: 'Testbench written by' }) as HTMLSelectElement
    const first = within(select).getAllByRole('option')[0]
    expect(first).toHaveTextContent('Same model as the design')
    expect(first).toHaveValue('')
  })

  it('groups models in optgroups and shows "(free)" only on free models', () => {
    renderSelect()
    const select = screen.getByRole('combobox', { name: 'Testbench written by' })
    const groups = Array.from(select.querySelectorAll('optgroup')).map((g) => g.getAttribute('label'))
    expect(groups).toEqual(['OpenCode', 'OpenCode Go', 'Cloudflare Workers AI'])

    const texts = within(select).getAllByRole('option').map((o) => o.textContent)
    expect(texts).toEqual([
      'Same model as the design',
      'big-pickle (free)',
      'kimi-k3',
      'gpt-oss-120b',
    ])
    expect(screen.getByRole('option', { name: 'kimi-k3' })).toHaveAttribute('title', 'opencode-go/kimi-k3')
  })

  it('choosing a model calls onChange with its id', () => {
    const { onChange } = renderSelect()
    fireEvent.change(screen.getByRole('combobox', { name: 'Testbench written by' }), {
      target: { value: 'opencode-go/kimi-k3' },
    })
    expect(onChange).toHaveBeenCalledWith('opencode-go/kimi-k3')
  })

  it('choosing the first option calls onChange with an empty string', () => {
    const { onChange } = renderSelect({ value: 'opencode-go/kimi-k3' })
    fireEvent.change(screen.getByRole('combobox', { name: 'Testbench written by' }), {
      target: { value: '' },
    })
    expect(onChange).toHaveBeenCalledWith('')
  })

  it('note explains the same model writes both when value is empty', () => {
    renderSelect({ value: '' })
    expect(
      screen.getByText('The same model writes the design and its testbench. Pick another to make the check independent.'),
    ).toBeInTheDocument()
  })

  it('note changes to the independence explanation when a separate model is chosen', () => {
    renderSelect({ value: 'opencode/big-pickle' })
    expect(
      screen.getByText('A separate model writes the testbench, so a failing check cannot be rewritten away by the design model.'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/The same model writes/)).toBeNull()
  })

  it('disables the select when disabled', () => {
    renderSelect({ disabled: true })
    expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toBeDisabled()
  })

  it('is controlled: it shows the value it is given and follows it when it changes', () => {
    const { rerender } = render(<TestbenchModelSelect models={models} value="opencode-go/kimi-k3" onChange={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toHaveValue('opencode-go/kimi-k3')
    rerender(<TestbenchModelSelect models={models} value="@cf/openai/gpt-oss-120b" onChange={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toHaveValue('@cf/openai/gpt-oss-120b')
    rerender(<TestbenchModelSelect models={models} value="" onChange={vi.fn()} />)
    expect(screen.getByRole('combobox', { name: 'Testbench written by' })).toHaveValue('')
  })
})
