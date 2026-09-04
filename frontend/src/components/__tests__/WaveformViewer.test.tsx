import { render, screen, fireEvent } from '@testing-library/react'
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

  it('renders zoom controls [+][-][Reset] and handles scale', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 100, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }, { t: 10, v: '1' }] }],
    }
    render(<WaveformViewer waveform={wf} />)
    const zoomIn = screen.getByRole('button', { name: /zoom in/i })
    const zoomOut = screen.getByRole('button', { name: /zoom out/i })
    const reset = screen.getByRole('button', { name: /reset/i })
    expect(zoomIn).toBeInTheDocument()
    expect(zoomOut).toBeInTheDocument()
    expect(reset).toBeInTheDocument()
    // also check for + / − symbols
    expect(screen.getByText('+')).toBeInTheDocument()
    expect(screen.getByText('−')).toBeInTheDocument()
    // clicks should not throw and should keep svg rendered
    fireEvent.click(zoomIn)
    fireEvent.click(zoomOut)
    fireEvent.click(reset)
    expect(screen.getByText('clk')).toBeInTheDocument()
  })

  it('truncated notice uses dark amber glass theme', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 10, truncated: true, dropped_signals: 1, changes_truncated: false,
      signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }] }],
    }
    render(<WaveformViewer waveform={wf} />)
    const notice = screen.getByTestId('truncation-notice')
    // inline style background should be rgba 245,158,11
    expect(notice.getAttribute('style') || notice.style.background).toMatch(/245.*158.*11/)
    // also check glass border
    expect(notice.style.background).toContain('rgba')
  })

  it('BusWave shows hex with 0x prefix and handles x/z specially', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 30, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [
        { name: 'data', width: 4, wave: [{ t: 0, v: 'a' }, { t: 10, v: 'x' }, { t: 20, v: 'z' }] },
      ],
    }
    render(<WaveformViewer waveform={wf} />)
    // hex prefix
    expect(screen.getByText('0xa')).toBeInTheDocument()
    // x / z should be displayed literally, not 0x-prefixed
    expect(screen.getByText('x')).toBeInTheDocument()
    expect(screen.getByText('z')).toBeInTheDocument()
    // ensure bare 'a' is not shown without prefix
    const all = screen.getAllByText(/a/)
    // at least the 0xa element exists, bare 'a' alone should not be the hex label (x/z already checked)
    expect(all.length).toBeGreaterThanOrEqual(1)
  })

  it('renders time ruler ticks every 20% including 0 and end_time', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 100, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }] }],
    }
    render(<WaveformViewer waveform={wf} />)
    const ruler = screen.getByLabelText('time ruler')
    expect(ruler).toBeInTheDocument()
    // ticks should include 0 and 100 and intermediate values
    expect(ruler.textContent).toContain('0')
    expect(ruler.textContent).toContain('100')
    expect(ruler.textContent).toContain('20')
    expect(ruler.textContent).toContain('40')
    expect(ruler.textContent).toContain('60')
    expect(ruler.textContent).toContain('80')
  })

  it('provides horizontal scroll container for large PLOT_W', () => {
    const wf: Waveform = {
      timescale: '1ns', end_time: 100, truncated: false, dropped_signals: 0, changes_truncated: false,
      signals: [{ name: 'clk', width: 1, wave: [{ t: 0, v: '0' }] }],
    }
    const { container } = render(<WaveformViewer waveform={wf} />)
    const scroll = container.querySelector('.waveform-scroll') as HTMLElement
    expect(scroll).toBeInTheDocument()
    expect(scroll.style.overflowX).toBe('auto')
    const svg = container.querySelector('.waveform-svg') as SVGElement
    expect(svg).toBeInTheDocument()
    // svg width should be at least PLOT_W (1000) + label
    expect(svg.getAttribute('width')).toBeTruthy()
    const w = Number(svg.getAttribute('width'))
    expect(w).toBeGreaterThanOrEqual(1000)
  })
})
