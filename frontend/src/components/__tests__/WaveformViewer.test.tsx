import { render, screen } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import WaveformViewer from '../WaveformViewer'
import type { Waveform } from '../../types'

describe('WaveformViewer', () => {
  it('shows empty state when waveform is null', () => {
    render(<WaveformViewer waveform={null} />)
    expect(screen.getByText(/No waveform/)).toBeInTheDocument()
  })

  it('shows empty state when signals array is empty', () => {
    const wf: Waveform = { timescale: '1ns', end_time: 100, signals: [], truncated: false, dropped_signals: 0, changes_truncated: false }
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText(/No waveform/)).toBeInTheDocument()
  })

  it('renders signal names and timescale', () => {
    const wf: Waveform = {
      timescale: '10ns', end_time: 50, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [
        { name: 'clk', width: 1, wave: [{ t: 0, v: '0' }, { t: 5, v: '1' }] },
        { name: 'data', width: 4, wave: [{ t: 0, v: '0' }, { t: 10, v: 'a' }] },
      ],
    }
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText(/10ns/)).toBeInTheDocument()
    expect(screen.getByText(/2 signals/)).toBeInTheDocument()
    expect(screen.getByText('clk')).toBeInTheDocument()
    expect(screen.getByText(/data/)).toBeInTheDocument()
  })

  it('shows bus width annotation for multi-bit signals', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 10, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [{ name: 'data', width: 8, wave: [{ t: 0, v: 'ff' }] }],
    }
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText(/data/)).toBeInTheDocument()
    expect(screen.getByText(/\[7:0\]/)).toBeInTheDocument()
  })

  it('shows truncation notice when truncated=true', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 10, truncated: true, dropped_signals: 5, changes_truncated: true,
      signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }] }],
    }
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText(/5 signal\(s\) hidden/)).toBeInTheDocument()
    expect(screen.getByText(/truncated/)).toBeInTheDocument()
  })

  it('does not show truncation notice when truncated=false', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 10, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }] }],
    }
    render(<WaveformViewer waveform={wf} />)
    expect(screen.queryByText(/hidden/)).not.toBeInTheDocument()
  })
})
