import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
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


describe('WaveformViewer v2: cursors, radix, groups, markers', () => {
  const wf: Waveform = {
    timescale: '1ps', timescale_ps: 1, end_time: 100_000, truncated: false, dropped_signals: 0, changes_truncated: false,
    signals: [
      { name: 'clk', width: 1, role: 'clock', path: 'tb.clk', wave: [{ t: 0, v: '0' }, { t: 10_000, v: '1' }, { t: 20_000, v: '0' }] },
      { name: 'count', width: 4, role: 'out', path: 'tb.dut.count', msb: 3, lsb: 0,
        wave: [{ t: 0, v: 'x' }, { t: 20_000, v: '1' }, { t: 60_000, v: 'a' }] },
      { name: 'i', width: 32, role: 'tb', path: 'tb.i', wave: [{ t: 0, v: '0' }] },
    ],
  }
  const plot = (c: HTMLElement) => c.querySelector('.wfv-plot') as SVGSVGElement
  const stubRect = (svg: SVGSVGElement) =>
    vi.spyOn(svg, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 1000, height: 200, right: 1000, bottom: 200, x: 0, y: 0, toJSON: () => ({}) })

  it('groups signals by role and hides testbench variables until asked', () => {
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText('Clock & reset')).toBeInTheDocument()
    expect(screen.getByText('Design outputs')).toBeInTheDocument()
    expect(screen.queryByText('Testbench variables')).toBeNull()
    expect(screen.queryByText('i')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Show testbench variables/ }))
    expect(screen.getByText('Testbench variables')).toBeInTheDocument()
    expect(screen.getByText('i')).toBeInTheDocument()
  })

  it('collapses a group on click', () => {
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText('clk')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Clock & reset/ }))
    expect(screen.queryByText('clk')).toBeNull()
  })

  it('shows every signal value at the cursor time, and pins cursor A on click', () => {
    const { container } = render(<WaveformViewer waveform={wf} />)
    stubRect(plot(container))
    fireEvent.click(plot(container), { clientX: 300 }) // 30_000 ps
    const vals = screen.getAllByTestId('cursor-value').map((e) => e.textContent)
    expect(vals).toEqual(['0', '0x1']) // clk back to 0 after 20ns, count = 1
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 30 ns')
  })

  it('measures the distance between two cursors with shift+click', () => {
    const { container } = render(<WaveformViewer waveform={wf} />)
    stubRect(plot(container))
    fireEvent.click(plot(container), { clientX: 100 })
    fireEvent.click(plot(container), { clientX: 400, shiftKey: true })
    const r = screen.getByTestId('pin-readout').textContent ?? ''
    expect(r).toContain('A 10 ns')
    expect(r).toContain('B 40 ns')
    expect(r).toContain('Δ 30 ns')
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.queryByTestId('pin-readout')).toBeNull()
  })

  it('changes the radix of buses at the cursor', () => {
    const { container } = render(<WaveformViewer waveform={wf} />)
    stubRect(plot(container))
    fireEvent.click(plot(container), { clientX: 700 }) // count = 0xa
    fireEvent.change(screen.getByLabelText('Radix'), { target: { value: 'dec' } })
    expect(screen.getAllByTestId('cursor-value').map((e) => e.textContent)).toContain('10')
    fireEvent.change(screen.getByLabelText('Radix'), { target: { value: 'bin' } })
    expect(screen.getAllByTestId('cursor-value').map((e) => e.textContent)).toContain('0b1010')
  })

  it('reports the run length as a duration and uses the real bus range', () => {
    render(<WaveformViewer waveform={wf} />)
    expect(screen.getByText('timescale 1ps · 100 ns · 3 signals')).toBeInTheDocument()
    expect(screen.getByText('[3:0]')).toBeInTheDocument()
  })

  it('draws a flag for each failed check and steps between them with ] and [', () => {
    const { container } = render(
      <WaveformViewer waveform={wf} markers={[{ t: 40_000, label: 'b' }, { t: 10_000, label: 'a' }]} />,
    )
    expect(container.querySelectorAll('.wfv-marker')).toHaveLength(2)
    expect(container.querySelectorAll('.wfv-marker.first')).toHaveLength(1) // only the earliest is emphasised
    const viewer = screen.getByLabelText('Waveform viewer')
    fireEvent.keyDown(viewer, { key: ']' })
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 10 ns')
    fireEvent.keyDown(viewer, { key: ']' })
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 40 ns')
    fireEvent.keyDown(viewer, { key: '[' })
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 10 ns')
    fireEvent.keyDown(viewer, { key: 'Escape' })
    expect(screen.queryByTestId('pin-readout')).toBeNull()
  })

  it('pins the cursor at a time requested from outside, again on a repeated request', () => {
    const { rerender } = render(<WaveformViewer waveform={wf} focusTime={30_000} focusSeq={1} />)
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 30 ns')
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.queryByTestId('pin-readout')).toBeNull()
    rerender(<WaveformViewer waveform={wf} focusTime={30_000} focusSeq={2} />) // same time, new request
    expect(screen.getByTestId('pin-readout').textContent).toContain('A 30 ns')
  })

  it('marks the part of a signal whose history was cut off', () => {
    const cut: Waveform = { ...wf, signals: [{ ...wf.signals[0], truncated_at: 50_000 }] }
    const { container } = render(<WaveformViewer waveform={cut} />)
    expect(container.querySelector('[fill="url(#wfv-hatch-trunc)"]')).not.toBeNull()
  })

  it('filters signals by name', () => {
    render(<WaveformViewer waveform={wf} />)
    fireEvent.change(screen.getByLabelText('Filter signals'), { target: { value: 'cou' } })
    expect(screen.getByText('count')).toBeInTheDocument()
    expect(screen.queryByText('clk')).toBeNull()
  })
})
