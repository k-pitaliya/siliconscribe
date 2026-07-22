import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import PromptPanel from '../PromptPanel'
import type { ModelInfo } from '../../types'

const models: ModelInfo[] = [
  { id: 'gpt-4o', label: 'GPT-4o', note: 'Accurate', tag: 'accurate' },
  { id: 'gpt-4o-mini', label: 'GPT-4o Mini', note: 'Fast', tag: 'fast' },
]

describe('PromptPanel', () => {
  const defaultProps = {
    onGenerate: vi.fn(),
    running: false,
    models,
    selectedModel: 'gpt-4o',
    onModelChange: vi.fn(),
    offline: false,
  }

  it('renders model selector when online', () => {
    render(<PromptPanel {...defaultProps} />)
    expect(screen.getByText('GPT-4o')).toBeInTheDocument()
    expect(screen.getByText('GPT-4o Mini')).toBeInTheDocument()
  })

  it('shows offline message when offline=true', () => {
    render(<PromptPanel {...defaultProps} offline={true} />)
    expect(screen.getByText(/Offline demo/)).toBeInTheDocument()
  })

  it('shows empty models message when models array is empty', () => {
    render(<PromptPanel {...defaultProps} models={[]} />)
    expect(screen.getByText('No models available.')).toBeInTheDocument()
  })

  it('calls onGenerate with prompt and frequency on submit', () => {
    const onGenerate = vi.fn()
    render(<PromptPanel {...defaultProps} onGenerate={onGenerate} />)
    const textarea = screen.getByPlaceholderText(/e\.g\./)
    fireEvent.change(textarea, { target: { value: 'Design a counter' } })
    fireEvent.click(screen.getByText('Generate RTL'))
    expect(onGenerate).toHaveBeenCalledWith('Design a counter', 100)
  })

  it('shows validation error on empty prompt', () => {
    const onGenerate = vi.fn()
    render(<PromptPanel {...defaultProps} onGenerate={onGenerate} />)
    fireEvent.click(screen.getByText('Generate RTL'))
    expect(onGenerate).not.toHaveBeenCalled()
  })

  it('example chips populate the textarea', () => {
    render(<PromptPanel {...defaultProps} />)
    const chip = screen.getByText(/4-bit ALU/)
    fireEvent.click(chip)
    const textarea = screen.getByPlaceholderText(/e\.g\./) as HTMLTextAreaElement
    expect(textarea.value).toContain('ALU')
  })

  it('disables button when running', () => {
    render(<PromptPanel {...defaultProps} running={true} />)
    expect(screen.getByText('Generating…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
  })

  it('frequency slider updates display', () => {
    render(<PromptPanel {...defaultProps} />)
    const slider = screen.getByRole('slider')
    fireEvent.change(slider, { target: { value: '250' } })
    expect(screen.getByText('250 MHz')).toBeInTheDocument()
  })

  it('calls onModelChange when model selector changes', () => {
    const onModelChange = vi.fn()
    render(<PromptPanel {...defaultProps} onModelChange={onModelChange} />)
    const select = screen.getByRole('combobox')
    fireEvent.change(select, { target: { value: 'gpt-4o-mini' } })
    expect(onModelChange).toHaveBeenCalledWith('gpt-4o-mini')
  })
})
