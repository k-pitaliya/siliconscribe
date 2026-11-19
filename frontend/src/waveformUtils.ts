// Pure helpers for the waveform viewer: time formatting, value lookup, radix, grouping and
// level-of-detail path building. No React in here so every rule can be unit-tested.

import type { SignalRole, WaveformSignal } from './types'

const UNIT_PS: Record<string, number> = { fs: 1e-3, ps: 1, ns: 1e3, us: 1e6, ms: 1e9, s: 1e12 }

/** One VCD time unit in picoseconds: from `timescale_ps`, else parsed from a "1ns" style string. */
export function unitPs(timescale: string, timescalePs?: number | null): number | null {
  if (timescalePs && timescalePs > 0) return timescalePs
  const m = /^(\d+)\s*(fs|ps|ns|us|ms|s)$/.exec((timescale ?? '').trim())
  return m ? Number(m[1]) * UNIT_PS[m[2]] : null
}

/** "120 ns" style label for a time given in VCD units. Falls back to the raw number. */
export function formatTime(t: number, ps: number | null): string {
  if (ps == null) return String(t)
  const totalPs = t * ps
  const abs = Math.abs(totalPs)
  const [div, unit]: [number, string] =
    abs >= 1e9 ? [1e9, 'ms'] : abs >= 1e6 ? [1e6, 'us'] : abs >= 1e3 || abs === 0 ? [1e3, 'ns'] : [1, 'ps']
  const v = totalPs / div
  return `${Number.isInteger(v) ? v : Number(v.toFixed(3))} ${unit}`
}

/** Round a raw step up to 1, 2 or 5 times a power of ten. */
export function niceStep(raw: number): number {
  if (!(raw > 0) || !Number.isFinite(raw)) return 1
  const pow = 10 ** Math.floor(Math.log10(raw))
  const f = raw / pow
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow
}

/** Tick positions (VCD units) so labels are about `minPx` apart. Always includes 0. */
export function timeTicks(end: number, plotW: number, minPx = 110): number[] {
  const step = niceStep(end / Math.max(1, Math.floor(plotW / minPx)))
  const out: number[] = []
  for (let t = 0; t <= end && out.length < 200; t += step) out.push(t)
  return out
}

/** Value of a signal at time t: the last change at or before t (binary search), or undefined. */
export function valueAt(wave: { t: number; v: string }[], t: number): string | undefined {
  let lo = 0
  let hi = wave.length - 1
  let ans = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (wave[mid].t <= t) {
      ans = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return ans < 0 ? undefined : wave[ans].v
}

export type Radix = 'hex' | 'bin' | 'dec'

/** Format a bus value (hex digits, `x`/`z` allowed per nibble) in the chosen radix. */
export function formatValue(v: string, width: number, radix: Radix): string {
  if (width === 1 || v === 'x' || v === 'z') return v
  if (radix === 'hex') return `0x${v}`
  const bits = v
    .split('')
    .map((ch) => (ch === 'x' ? 'xxxx' : ch === 'z' ? 'zzzz' : parseInt(ch, 16).toString(2).padStart(4, '0')))
    .join('')
  const sized = bits.length >= width ? bits.slice(bits.length - width) : bits.padStart(width, '0')
  if (radix === 'bin') return `0b${sized}`
  if (/[xz]/.test(sized)) return `0x${v}` // a decimal number would hide the unknown bits
  return BigInt(`0x${v}`).toString()
}

// ----------------------------------------------------------------------------- grouping
export interface SignalGroup {
  key: string
  label: string
  /** Hidden until the user asks (testbench bookkeeping, task locals, parameters). */
  hiddenByDefault: boolean
  signals: WaveformSignal[]
}

const GROUP_DEFS: { key: string; label: string; roles: SignalRole[]; hidden: boolean }[] = [
  { key: 'clk', label: 'Clock & reset', roles: ['clock', 'reset'], hidden: false },
  { key: 'in', label: 'Design inputs', roles: ['in'], hidden: false },
  { key: 'out', label: 'Design outputs', roles: ['out', 'io'], hidden: false },
  { key: 'int', label: 'Signals', roles: ['dut_internal', 'internal'], hidden: false },
  { key: 'tb', label: 'Testbench variables', roles: ['tb'], hidden: true },
  { key: 'aux', label: 'Task locals', roles: ['aux'], hidden: true },
  { key: 'param', label: 'Parameters', roles: ['param'], hidden: true },
]

/** Split signals into role groups (in a fixed, sensible order), applying a name filter. */
export function groupSignals(signals: WaveformSignal[], filter = ''): SignalGroup[] {
  const q = filter.trim().toLowerCase()
  const matches = (s: WaveformSignal) => !q || s.name.toLowerCase().includes(q) || (s.path ?? '').toLowerCase().includes(q)
  return GROUP_DEFS.map((g) => ({
    key: g.key,
    label: g.label,
    hiddenByDefault: g.hidden,
    signals: signals.filter((s) => g.roles.includes(s.role ?? 'internal') && matches(s)),
  })).filter((g) => g.signals.length > 0)
}

// ----------------------------------------------------------------------------- level of detail
export interface BitPath {
  d: string
  /** Pixel ranges where changes were closer than a pixel and are drawn as a band instead. */
  dense: { x0: number; x1: number }[]
}

/** SVG path for a 1-bit signal. Changes less than ~0.6 px apart collapse into a dense band. */
export function bitPath(
  wave: { t: number; v: string }[],
  x: (t: number) => number,
  hi: number,
  lo: number,
  endX: number,
  minPx = 0.6,
): BitPath {
  if (wave.length === 0) return { d: '', dense: [] }
  const mid = (hi + lo) / 2
  const yFor = (v: string) => (v === '1' ? hi : v === '0' ? lo : mid)
  let lastX = x(wave[0].t)
  let emittedY = yFor(wave[0].v)
  let curY = emittedY
  const parts = [`M ${lastX} ${emittedY}`]
  const dense: { x0: number; x1: number }[] = []
  let denseStart: number | null = null
  for (let i = 1; i < wave.length; i++) {
    const xi = x(wave[i].t)
    const ny = yFor(wave[i].v)
    if (xi - lastX < minPx) {
      if (denseStart === null) denseStart = lastX
      curY = ny
      continue
    }
    if (denseStart !== null) {
      dense.push({ x0: denseStart, x1: xi })
      denseStart = null
    }
    parts.push(`L ${xi} ${emittedY}`, `L ${xi} ${ny}`)
    emittedY = ny
    curY = ny
    lastX = xi
  }
  if (denseStart !== null) dense.push({ x0: denseStart, x1: endX })
  parts.push(`L ${endX} ${curY}`)
  return { d: parts.join(' '), dense }
}

export interface BusSeg {
  x0: number
  x1: number
  v: string
  dense: boolean
}

/** Segments of a bus signal. Runs of segments narrower than `minPx` merge into one dense block. */
export function busSegments(
  wave: { t: number; v: string }[],
  x: (t: number) => number,
  endX: number,
  minPx = 0.8,
): BusSeg[] {
  const out: BusSeg[] = []
  let denseStart: number | null = null
  for (let i = 0; i < wave.length; i++) {
    const x0 = x(wave[i].t)
    const x1 = i + 1 < wave.length ? x(wave[i + 1].t) : endX
    if (x1 - x0 < minPx) {
      if (denseStart === null) denseStart = x0
      continue
    }
    if (denseStart !== null) {
      out.push({ x0: denseStart, x1: x0, v: '', dense: true })
      denseStart = null
    }
    out.push({ x0, x1, v: wave[i].v, dense: false })
  }
  if (denseStart !== null) out.push({ x0: denseStart, x1: endX, v: '', dense: true })
  return out
}

/** Differing bit positions (0 = LSB) between two hex strings; used to explain a failed check. */
export function differingBits(expected: string | null, actual: string | null): number[] {
  if (!expected || !actual) return []
  const toBits = (h: string) =>
    h
      .toLowerCase()
      .split('')
      .map((c) => (c === 'x' ? 'xxxx' : c === 'z' ? 'zzzz' : /[0-9a-f]/.test(c) ? parseInt(c, 16).toString(2).padStart(4, '0') : '????'))
      .join('')
  const a = toBits(expected)
  const b = toBits(actual)
  const n = Math.max(a.length, b.length)
  const pa = a.padStart(n, '0')
  const pb = b.padStart(n, '0')
  const diff: number[] = []
  for (let i = 0; i < n; i++) if (pa[i] !== pb[i]) diff.push(n - 1 - i)
  return diff
}
