import { describe, it, expect } from 'vitest'
import {
  bitPath,
  busSegments,
  differingBits,
  formatTime,
  formatValue,
  groupSignals,
  niceStep,
  timeTicks,
  unitPs,
  valueAt,
} from '../waveformUtils'
import type { WaveformSignal } from '../types'

describe('time units', () => {
  it('prefers the numeric timescale and falls back to parsing the string', () => {
    expect(unitPs('1ps', 1)).toBe(1)
    expect(unitPs('10ns', null)).toBe(10_000)
    expect(unitPs('1 us')).toBe(1_000_000)
    expect(unitPs('garbage')).toBeNull()
  })

  it('formats times in the largest unit that keeps the number readable', () => {
    expect(formatTime(0, 1)).toBe('0 ns')
    expect(formatTime(500, 1)).toBe('500 ps')
    expect(formatTime(20_000, 1)).toBe('20 ns')
    expect(formatTime(3_505_000, 1)).toBe('3.505 us')
    expect(formatTime(7, 1_000)).toBe('7 ns') // 1ns timescale, t in ns
    expect(formatTime(42, null)).toBe('42') // unknown unit: never invent one
  })

  it('rounds tick steps to 1/2/5 x 10^n and always starts at zero', () => {
    expect(niceStep(11.1)).toBe(20)
    expect(niceStep(0.7)).toBe(1)
    expect(niceStep(0)).toBe(1)
    const ticks = timeTicks(560_000, 900)
    expect(ticks[0]).toBe(0)
    expect(ticks.length).toBeGreaterThan(2)
    expect(ticks.length).toBeLessThan(15)
  })
})

describe('valueAt', () => {
  const wave = [
    { t: 0, v: 'x' },
    { t: 10, v: '1' },
    { t: 30, v: '0' },
  ]
  it('returns the last change at or before t', () => {
    expect(valueAt(wave, 0)).toBe('x')
    expect(valueAt(wave, 9)).toBe('x')
    expect(valueAt(wave, 10)).toBe('1')
    expect(valueAt(wave, 29)).toBe('1')
    expect(valueAt(wave, 1_000)).toBe('0')
  })
  it('is undefined before the first sample and for an empty wave', () => {
    expect(valueAt([{ t: 5, v: '1' }], 4)).toBeUndefined()
    expect(valueAt([], 4)).toBeUndefined()
  })
})

describe('formatValue', () => {
  it('leaves scalars and whole-signal x/z untouched', () => {
    expect(formatValue('1', 1, 'dec')).toBe('1')
    expect(formatValue('x', 8, 'bin')).toBe('x')
    expect(formatValue('z', 8, 'hex')).toBe('z')
  })
  it('renders hex, binary at the signal width, and decimal', () => {
    expect(formatValue('a', 4, 'hex')).toBe('0xa')
    expect(formatValue('a', 4, 'bin')).toBe('0b1010')
    expect(formatValue('5', 8, 'bin')).toBe('0b00000101')
    expect(formatValue('ff', 8, 'dec')).toBe('255')
    expect(formatValue('ffffffffffffffff', 64, 'dec')).toBe('18446744073709551615') // beyond 2^53
  })
  it('never turns unknown bits into a number', () => {
    expect(formatValue('1x', 8, 'bin')).toBe('0b0001xxxx')
    expect(formatValue('1x', 8, 'dec')).toBe('0x1x')
  })
})

describe('groupSignals', () => {
  const mk = (name: string, role: WaveformSignal['role'], path = name): WaveformSignal => ({
    name, width: 1, wave: [], role, path,
  })
  const sigs = [
    mk('clk', 'clock'), mk('rst_n', 'reset'), mk('a', 'in'), mk('y', 'out'), mk('tmp', 'dut_internal'),
    mk('i', 'tb'), mk('exp', 'aux'), mk('WIDTH', 'param'),
  ]
  it('orders groups and marks testbench bookkeeping as hidden by default', () => {
    const g = groupSignals(sigs)
    expect(g.map((x) => x.key)).toEqual(['clk', 'in', 'out', 'int', 'tb', 'aux', 'param'])
    expect(g.filter((x) => x.hiddenByDefault).map((x) => x.key)).toEqual(['tb', 'aux', 'param'])
    expect(g[0].signals.map((s) => s.name)).toEqual(['clk', 'rst_n'])
  })
  it('treats a signal without a role as an ordinary internal signal', () => {
    const g = groupSignals([{ name: 'q', width: 1, wave: [] }])
    expect(g).toHaveLength(1)
    expect(g[0].key).toBe('int')
  })
  it('filters by name or hierarchical path and drops empty groups', () => {
    expect(groupSignals(sigs, 'CLK').map((x) => x.key)).toEqual(['clk'])
    expect(groupSignals([mk('q', 'out', 'tb.dut.q')], 'dut')).toHaveLength(1)
    expect(groupSignals(sigs, 'nomatch')).toEqual([])
  })
})

describe('level of detail', () => {
  const x = (t: number) => t // 1 px per time unit

  it('draws every edge of a slow bit signal and reports nothing dense', () => {
    const { d, dense } = bitPath([{ t: 0, v: '0' }, { t: 10, v: '1' }, { t: 20, v: '0' }], x, 5, 25, 30)
    expect(dense).toEqual([])
    expect(d.startsWith('M 0 25')).toBe(true)
    expect(d).toContain('L 10 25 L 10 5') // vertical edge at the change
    expect(d.endsWith('L 30 25')).toBe(true)
  })

  it('collapses sub-pixel toggling into one dense band instead of thousands of edges', () => {
    const wave = Array.from({ length: 2000 }, (_, i) => ({ t: i * 0.1, v: i % 2 ? '1' : '0' }))
    const { d, dense } = bitPath(wave, x, 5, 25, 200)
    expect(dense.length).toBeGreaterThan(0)
    // Path size is bounded by the pixel width (about 2 segments per 0.6 px), not by the 2000 changes.
    const segments = d.split('L').length - 1
    expect(segments).toBeLessThanOrEqual(2 * Math.ceil(200 / 0.6) + 4)
    expect(segments).toBeLessThan(2 * wave.length / 3)
  })

  it('merges narrow bus segments into one dense block but keeps wide ones readable', () => {
    const wave = [
      { t: 0, v: '1' }, // 0..100: wide, kept
      { t: 100, v: '2' }, // 100..200: wide, kept
      { t: 200, v: '3' }, // 200..200.2: 0.2px, dense
      { t: 200.2, v: '4' }, // 200.2..200.4: 0.2px, dense
      { t: 200.4, v: '5' }, // 200.4..400: wide again
    ]
    const segs = busSegments(wave, x, 400)
    expect(segs.map((s) => [s.v, s.dense])).toEqual([['1', false], ['2', false], ['', true], ['5', false]])
    expect(segs[2].x0).toBe(200) // the block spans exactly the squeezed region
    expect(segs[2].x1).toBe(200.4)
  })

  it('keeps a lone narrow tail as a dense block ending at the run end', () => {
    const segs = busSegments([{ t: 0, v: '1' }, { t: 99.9, v: '2' }], x, 100)
    expect(segs[segs.length - 1]).toMatchObject({ dense: true, x1: 100 })
  })
})

describe('differingBits', () => {
  it('lists differing bit positions, LSB = 0', () => {
    expect(differingBits('4', '6')).toEqual([1])
    expect(differingBits('f', '0')).toEqual([3, 2, 1, 0])
    expect(differingBits('ff', '0f')).toEqual([7, 6, 5, 4])
  })
  it('aligns different lengths and is empty for equal or missing values', () => {
    expect(differingBits('1', '11')).toEqual([4])
    expect(differingBits('a', 'a')).toEqual([])
    expect(differingBits(null, 'a')).toEqual([])
  })
  it('treats an unknown bit as different from a known one', () => {
    expect(differingBits('4', 'x')).toEqual([3, 2, 1, 0])
  })
})

describe('formatValue never throws (self-review: an upper-case X0 from Icarus blanked the page in "dec")', () => {
  it.each([['X0', 8], ['Zf', 8], ['-3', 8], ["8'hFF", 8], ['0x1F', 8], ['1.5', 8], ['N/A', 8], ['r3.14', 64], ['', 8]])(
    '%s', (v, w) => {
      for (const radix of ['hex', 'bin', 'dec'] as const) expect(() => formatValue(v, w, radix)).not.toThrow()
    })
  it('reads upper-case hex and keeps unknown bits visible', () => {
    expect(formatValue('FF', 8, 'dec')).toBe('255')
    expect(formatValue('X0', 8, 'dec')).toBe('0xx0')
  })
  it('shows text that is not a hex value unchanged (not as a fake 0x number)', () => {
    expect(formatValue('N/A', 8, 'hex')).toBe('N/A')
    expect(formatValue("8'hFF", 8, 'dec')).toBe("8'hFF")
  })
})
