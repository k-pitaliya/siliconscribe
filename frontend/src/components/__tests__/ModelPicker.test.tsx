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

describe('ModelPicker: keyboard, focus order and honest states', () => {
  it('has one tab stop in the source switch: the checked source', () => {
    renderPicker()
    const radios = screen.getAllByRole('radio')
    expect(radios.map((r) => r.getAttribute('tabindex'))).toEqual(['0', '-1', '-1'])
  })

  it('arrow keys move between sources, wrap around, and move focus with them', () => {
    const props = renderPicker()
    const opencode = screen.getByRole('radio', { name: 'OpenCode' })
    fireEvent.keyDown(opencode, { key: 'ArrowRight' })
    expect(props.onModelChange).toHaveBeenLastCalledWith('@cf/openai/gpt-oss-120b')
    expect(screen.getByRole('radio', { name: 'Cloudflare' })).toHaveFocus()
    fireEvent.keyDown(opencode, { key: 'ArrowLeft' })                    // wraps from the first to the last
    expect(props.onModelChange).toHaveBeenLastCalledWith('nim/poolside/laguna-xs-2.1')
    expect(screen.getByRole('radio', { name: 'NVIDIA NIM' })).toHaveFocus()
  })

  it('Home and End jump to the first and last source', () => {
    const props = renderPicker({ selectedModel: '@cf/openai/gpt-oss-120b' })
    fireEvent.keyDown(screen.getByRole('radio', { name: 'Cloudflare' }), { key: 'End' })
    expect(props.onModelChange).toHaveBeenLastCalledWith('nim/poolside/laguna-xs-2.1')
    fireEvent.keyDown(screen.getByRole('radio', { name: 'Cloudflare' }), { key: 'Home' })
    expect(props.onModelChange).toHaveBeenLastCalledWith('opencode/deepseek-v4.1-flash-free')
  })

  it('other keys and a disabled picker do nothing', () => {
    const props = renderPicker({ disabled: true })
    fireEvent.keyDown(screen.getByRole('radio', { name: 'OpenCode' }), { key: 'ArrowRight' })
    expect(props.onModelChange).not.toHaveBeenCalled()
    const enabled = renderPicker()
    fireEvent.keyDown(screen.getAllByRole('radio', { name: 'OpenCode' })[1], { key: 'a' })
    expect(enabled.onModelChange).not.toHaveBeenCalled()
  })

  it('the refresh button follows the source switch in the DOM, matching where it appears', () => {
    renderPicker()
    const group = screen.getByRole('radiogroup', { name: 'Model source' })
    expect(group.nextElementSibling).toBe(screen.getByRole('button', { name: 'Refresh model list' }))
  })

  it('does not pretend a model is selected when the selection is not in the list', () => {
    const props = renderPicker({ selectedModel: 'opencode/not-offered-any-more' })
    const select = screen.getByRole('combobox', { name: 'Model' })
    expect(select).toHaveValue('')
    const placeholder = select.querySelector('option[value=""]') as HTMLOptionElement
    expect(placeholder.textContent).toBe('Choose a model')
    expect(placeholder.disabled).toBe(true)
    fireEvent.change(select, { target: { value: 'opencode/big-pickle' } })
    expect(props.onModelChange).toHaveBeenCalledWith('opencode/big-pickle')
  })

  it('has no placeholder when the selection is valid', () => {
    renderPicker()
    expect(screen.getByRole('combobox', { name: 'Model' }).querySelector('option[value=""]')).toBeNull()
  })

  it('shows the server\'s own explanation when the OpenCode list is empty', () => {
    renderPicker({ models: [], selectedModel: '', providers: [{ id: 'opencode', label: 'OpenCode', available: true, count: 0, hint: 'No models were found. Is the OpenCode app installed and signed in?' }] })
    expect(screen.getByRole('status')).toHaveTextContent('No models were found. Is the OpenCode app installed and signed in?')
  })

  it('does not leave a label pointing at a control that is not there', () => {
    const { container } = render(<ModelPicker models={models} providers={[{ id: 'opencode', label: 'OpenCode', available: true, count: 3 }]} selectedModel="opencode/big-pickle"
      onModelChange={vi.fn()} includePaid={false} onIncludePaidChange={vi.fn()} paidHidden={0} onRefresh={vi.fn()} />)
    fireEvent.click(screen.getByRole('radio', { name: 'NVIDIA NIM' }))            // provider missing: only a hint is shown
    expect(container.querySelector('label[for="model-select"]')).toBeNull()
    expect(screen.getByText('Model')).toBeInTheDocument()
  })
})

describe('ModelPicker: behaviours the first tests did not pin down', () => {
  it('recognises a Cloudflare model by its id alone when the server sent no provider', () => {
    const bare: ModelInfo[] = [{ id: '@cf/qwen/qwen2.5-coder-32b-instruct', label: 'qwen2.5-coder-32b-instruct', note: '', tag: 'balanced' }, models[0]]
    renderPicker({ models: bare, selectedModel: '@cf/qwen/qwen2.5-coder-32b-instruct' })
    expect(screen.getByRole('radio', { name: 'Cloudflare' })).toHaveAttribute('aria-checked', 'true')
  })

  it('switching to OpenCode picks a FREE model even when a non-free one is listed first', () => {
    const reordered: ModelInfo[] = [
      { id: 'opencode/gpt-5.5', label: 'gpt-5.5', note: '', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: null },
      { id: 'opencode/big-pickle-free', label: 'big-pickle-free', note: '', tag: 'balanced', provider: 'opencode', group: 'OpenCode', free: true },
      models[3],
    ]
    const props = renderPicker({ models: reordered, selectedModel: '@cf/openai/gpt-oss-120b' })
    fireEvent.click(screen.getByRole('radio', { name: 'OpenCode' }))
    expect(props.onModelChange).toHaveBeenCalledWith('opencode/big-pickle-free')
  })

  it('clicking the source that is already selected does not change the model', () => {
    const props = renderPicker()
    fireEvent.click(screen.getByRole('radio', { name: 'OpenCode' }))
    expect(props.onModelChange).not.toHaveBeenCalled()
  })

  it('shows the selected model\'s note under the menu', () => {
    renderPicker()
    expect(screen.getByText('Free', { selector: '.model-note' })).toBeInTheDocument()
  })
})

