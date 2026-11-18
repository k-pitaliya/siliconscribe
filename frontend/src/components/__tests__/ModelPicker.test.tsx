import { render, screen, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import ModelPicker from '../ModelPicker'
import type { ComponentProps } from 'react'
import type { ModelInfo, ProviderInfo } from '../../types'

const models: ModelInfo[] = [
  { id: 'opencode/deepseek-v4.1-flash-free', label: 'deepseek-v4.1-flash-free', note: 'Free', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: true },
  { id: 'opencode/big-pickle', label: 'big-pickle', note: '', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: true },
  { id: 'opencode-go/kimi-k3', label: 'kimi-k3', note: '', tag: 'balanced', provider: 'opencode-go', group: 'OpenCode Go', free: false },
  { id: '@cf/openai/gpt-oss-120b', label: 'gpt-oss-120b', note: 'Cloudflare Workers AI', tag: 'balanced', provider: 'cloudflare', group: 'Cloudflare Workers AI', free: null },
]

const providers: ProviderInfo[] = [
  { id: 'opencode', label: 'OpenCode', available: true, count: 3 },
  { id: 'cloudflare', label: 'Cloudflare', available: true, count: 1 },
]

function renderPicker(overrides: Partial<ComponentProps<typeof ModelPicker>> = {}) {
  const props = {
    models,
    providers,
    selectedModel: 'opencode/deepseek-v4.1-flash-free',
    onModelChange: vi.fn(),
    includePaid: false,
    onIncludePaidChange: vi.fn(),
    paidHidden: 0,
    onRefresh: vi.fn(),
    refreshing: false,
    disabled: false,
    ...overrides,
  }
  render(<ModelPicker {...props} />)
  return props
}

describe('ModelPicker', () => {
  it('OpenCode view lists only the OpenCode models in two optgroups, marking free ones', () => {
    renderPicker()
    const select = screen.getByRole('combobox', { name: 'Model' })
    const groups = Array.from(select.querySelectorAll('optgroup')).map((g) => g.getAttribute('label'))
    expect(groups).toEqual(['OpenCode', 'OpenCode Go'])

    const options = within(select).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual([
      'deepseek-v4.1-flash-free (free)',
      'big-pickle (free)',
      'kimi-k3',
    ])
    expect(screen.queryByRole('option', { name: /gpt-oss/ })).toBeNull()
    expect(screen.getByRole('option', { name: 'kimi-k3' })).toHaveAttribute('title', 'opencode-go/kimi-k3')
  })

  it('calls onModelChange with the id of the chosen option', () => {
    const { onModelChange } = renderPicker()
    fireEvent.change(screen.getByRole('combobox', { name: 'Model' }), {
      target: { value: 'opencode-go/kimi-k3' },
    })
    expect(onModelChange).toHaveBeenCalledWith('opencode-go/kimi-k3')
  })

  it('clicking Cloudflare while an OpenCode model is selected selects the first Cloudflare model', () => {
    const first = renderPicker()
    fireEvent.click(screen.getByRole('radio', { name: 'Cloudflare' }))
    expect(first.onModelChange).toHaveBeenCalledWith('@cf/openai/gpt-oss-120b')
  })

  it('switching to OpenCode while a Cloudflare model is selected picks the first free OpenCode model', () => {
    const props = renderPicker({ selectedModel: '@cf/openai/gpt-oss-120b' })
    expect(screen.getByRole('radio', { name: 'Cloudflare' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: 'OpenCode' }))
    expect(props.onModelChange).toHaveBeenCalledWith('opencode/deepseek-v4.1-flash-free')
  })

  it('other-models checkbox reports changes and shows the hidden count or the credits note', () => {
    const hidden = renderPicker({ paidHidden: 7, includePaid: false })
    const checkbox = screen.getByRole('checkbox', { name: /Show other models/ })
    expect(screen.getByText(/Show other models \(7 hidden\)/)).toBeInTheDocument()
    fireEvent.click(checkbox)
    expect(hidden.onIncludePaidChange).toHaveBeenCalledWith(true)
    expect(screen.queryByText(/Models not marked free may use credits/)).toBeNull()
  })

  it('other-models checkbox calls onIncludePaidChange(false) when unticked and shows the credits note when on', () => {
    const on = renderPicker({ includePaid: true, paidHidden: 7 })
    const checkbox = screen.getByRole('checkbox', { name: /Show other models/ })
    expect(checkbox).toBeChecked()
    expect(screen.queryByText(/hidden\)/)).toBeNull()
    expect(screen.getByText('Models not marked free may use credits on your OpenCode account.')).toBeInTheDocument()
    fireEvent.click(checkbox)
    expect(on.onIncludePaidChange).toHaveBeenCalledWith(false)
  })

  it('shows the provider hint with role status and no combobox when Cloudflare is unavailable', () => {
    renderPicker({
      providers: [
        { id: 'opencode', label: 'OpenCode', available: true, count: 3 },
        { id: 'cloudflare', label: 'Cloudflare', available: false, hint: 'Set the Cloudflare variables.', count: 0 },
      ],
    })
    fireEvent.click(screen.getByRole('radio', { name: 'Cloudflare' }))
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Set the Cloudflare variables.')
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('refresh button has an accessible name and calls onRefresh when clicked', () => {
    const idle = renderPicker()
    const button = screen.getByRole('button', { name: 'Refresh model list' })
    expect(button).toBeEnabled()
    fireEvent.click(button)
    expect(idle.onRefresh).toHaveBeenCalledTimes(1)
  })

  it('refresh button is disabled while refreshing', () => {
    renderPicker({ refreshing: true })
    expect(screen.getByRole('button', { name: 'Refresh model list' })).toBeDisabled()
  })

  it('refresh button is disabled when the picker is disabled', () => {
    renderPicker({ disabled: true })
    expect(screen.getByRole('button', { name: 'Refresh model list' })).toBeDisabled()
  })

  it('names the select "Model" and the radiogroup "Model source"', () => {
    renderPicker()
    expect(screen.getByRole('combobox', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByRole('radiogroup', { name: 'Model source' })).toBeInTheDocument()
  })

  it('disables the select, both radios and the checkbox when disabled', () => {
    renderPicker({ disabled: true })
    expect(screen.getByRole('combobox', { name: 'Model' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'OpenCode' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Cloudflare' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: /Show other models/ })).toBeDisabled()
  })
})
