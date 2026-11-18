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
  { id: 'nim/poolside/laguna-xs-2.1', label: 'poolside/laguna-xs-2.1', note: 'NVIDIA NIM hosted API', tag: 'balanced', provider: 'nim', group: 'NVIDIA NIM', free: null },
  { id: 'nim/nvidia/nemotron-3-ultra-550b-a55b', label: 'nvidia/nemotron-3-ultra-550b-a55b', note: '', tag: 'balanced', provider: 'nim', group: 'NVIDIA NIM', free: null },
]

const providers: ProviderInfo[] = [
  { id: 'opencode', label: 'OpenCode', available: true, count: 3 },
  { id: 'cloudflare', label: 'Cloudflare', available: true, count: 1 },
  { id: 'nim', label: 'NVIDIA NIM', available: true, count: 2 },
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

  it('renders three source radios named OpenCode, Cloudflare and NVIDIA NIM inside the Model source radiogroup', () => {
    renderPicker()
    const group = screen.getByRole('radiogroup', { name: 'Model source' })
    expect(within(group).getAllByRole('radio')).toHaveLength(3)
    expect(within(group).getByRole('radio', { name: 'OpenCode' })).toBeInTheDocument()
    expect(within(group).getByRole('radio', { name: 'Cloudflare' })).toBeInTheDocument()
    expect(within(group).getByRole('radio', { name: 'NVIDIA NIM' })).toBeInTheDocument()
  })

  it('clicking NVIDIA NIM while an OpenCode model is selected selects the first NIM model', () => {
    const props = renderPicker()
    fireEvent.click(screen.getByRole('radio', { name: 'NVIDIA NIM' }))
    expect(props.onModelChange).toHaveBeenCalledWith('nim/poolside/laguna-xs-2.1')
  })

  it('with a nim model selected, the NIM view lists only the two NIM options in one NVIDIA NIM optgroup and no other-models checkbox', () => {
    renderPicker({ selectedModel: 'nim/poolside/laguna-xs-2.1' })
    expect(screen.getByRole('radio', { name: 'NVIDIA NIM' })).toHaveAttribute('aria-checked', 'true')
    const select = screen.getByRole('combobox', { name: 'Model' })
    const groups = Array.from(select.querySelectorAll('optgroup')).map((g) => g.getAttribute('label'))
    expect(groups).toEqual(['NVIDIA NIM'])
    const options = within(select).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual([
      'poolside/laguna-xs-2.1',
      'nvidia/nemotron-3-ultra-550b-a55b',
    ])
    expect(screen.queryByRole('option', { name: /deepseek|big-pickle|kimi|gpt-oss/ })).toBeNull()
    expect(screen.queryByRole('checkbox', { name: /Show other models/ })).toBeNull()
  })

  it('clicking OpenCode while a nim model is selected picks the first free OpenCode model', () => {
    const props = renderPicker({ selectedModel: 'nim/poolside/laguna-xs-2.1' })
    fireEvent.click(screen.getByRole('radio', { name: 'OpenCode' }))
    expect(props.onModelChange).toHaveBeenCalledWith('opencode/deepseek-v4.1-flash-free')
  })

  it('shows the NIM provider hint with role status and no combobox when NVIDIA NIM is unavailable', () => {
    renderPicker({
      providers: [
        { id: 'opencode', label: 'OpenCode', available: true, count: 3 },
        { id: 'cloudflare', label: 'Cloudflare', available: true, count: 1 },
        { id: 'nim', label: 'NVIDIA NIM', available: false, hint: 'Set the NIM variable.', count: 0 },
      ],
    })
    fireEvent.click(screen.getByRole('radio', { name: 'NVIDIA NIM' }))
    const status = screen.getByRole('status')
    expect(status).toHaveTextContent('Set the NIM variable.')
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('shows the default NIM hint when the nim provider is missing from providers', () => {
    renderPicker({
      providers: [
        { id: 'opencode', label: 'OpenCode', available: true, count: 3 },
        { id: 'cloudflare', label: 'Cloudflare', available: true, count: 1 },
      ],
    })
    fireEvent.click(screen.getByRole('radio', { name: 'NVIDIA NIM' }))
    expect(screen.getByRole('status')).toHaveTextContent(
      'NVIDIA NIM is not set up. Start the backend with NVIDIA_NIM_API_KEY set.',
    )
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('shows an available NIM provider hint as role status under the select', () => {
    renderPicker({
      providers: [
        { id: 'opencode', label: 'OpenCode', available: true, count: 3 },
        { id: 'cloudflare', label: 'Cloudflare', available: true, count: 1 },
        { id: 'nim', label: 'NVIDIA NIM', available: true, hint: 'Showing suggested models.', count: 2 },
      ],
    })
    fireEvent.click(screen.getByRole('radio', { name: 'NVIDIA NIM' }))
    expect(screen.getByRole('combobox', { name: 'Model' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Showing suggested models.')
  })
})
