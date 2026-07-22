import { useMemo } from 'react'
import type { Waveform } from '../types'

const LABEL_W = 90
const PLOT_W = 1000
const ROW_H = 30
const ROW_GAP = 10
const PAD_Y = 8

export default function WaveformViewer({ waveform }: { waveform: Waveform | null }) {
  if (!waveform || waveform.signals.length === 0) {
    return <div className="empty-state">No waveform. Run a simulation to capture a VCD.</div>
  }

  const end = Math.max(waveform.end_time, 1)
  const rows = waveform.signals
  const height = PAD_Y * 2 + rows.length * (ROW_H + ROW_GAP)
  const x = (t: number) => LABEL_W + (t / end) * PLOT_W

  return (
    <div className="waveform-viewer">
      <div className="waveform-meta">
        timescale {waveform.timescale} · {end} time units · {rows.length} signals
      </div>
      <svg
        className="waveform-svg"
        viewBox={`0 0 ${LABEL_W + PLOT_W + 20} ${height}`}
        width="100%"
        preserveAspectRatio="xMinYMin meet"
      >
        {rows.map((sig, i) => {
          const top = PAD_Y + i * (ROW_H + ROW_GAP)
          return (
            <g key={sig.name}>
              <text x={6} y={top + ROW_H / 2 + 4} className="wf-label">
                {sig.name}
                {sig.width > 1 ? `[${sig.width - 1}:0]` : ''}
              </text>
              {sig.width === 1 ? (
                <BitWave wave={sig.wave} top={top} x={x} end={end} />
              ) : (
                <BusWave wave={sig.wave} top={top} x={x} end={end} />
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function BitWave({
  wave,
  top,
  x,
  end,
}: {
  wave: { t: number; v: string }[]
  top: number
  x: (t: number) => number
  end: number
}) {
  const hi = top + 4
  const lo = top + ROW_H - 4
  const yFor = (v: string) => (v === '1' ? hi : v === '0' ? lo : (hi + lo) / 2)

  if (wave.length === 0) return null
  const pts: string[] = []
  let prevY = yFor(wave[0].v)
  pts.push(`M ${x(wave[0].t)} ${prevY}`)
  for (let i = 1; i < wave.length; i++) {
    const xi = x(wave[i].t)
    pts.push(`L ${xi} ${prevY}`) // hold
    const ny = yFor(wave[i].v)
    pts.push(`L ${xi} ${ny}`) // transition
    prevY = ny
  }
  pts.push(`L ${x(end)} ${prevY}`)
  return <path d={pts.join(' ')} className="wf-bit" fill="none" />
}

function BusWave({
  wave,
  top,
  x,
  end,
}: {
  wave: { t: number; v: string }[]
  top: number
  x: (t: number) => number
  end: number
}) {
  const hi = top + 4
  const lo = top + ROW_H - 4
  const mid = (hi + lo) / 2
  const segs = useMemo(() => {
    const out: { x0: number; x1: number; v: string }[] = []
    for (let i = 0; i < wave.length; i++) {
      const x0 = x(wave[i].t)
      const x1 = i + 1 < wave.length ? x(wave[i + 1].t) : x(end)
      if (x1 > x0) out.push({ x0, x1, v: wave[i].v })
    }
    return out
  }, [wave, x, end])

  return (
    <>
      {segs.map((s, i) => {
        const k = 3 // crossover slant
        const d = `M ${s.x0} ${mid} L ${s.x0 + k} ${hi} L ${s.x1 - k} ${hi} L ${s.x1} ${mid} L ${s.x1 - k} ${lo} L ${s.x0 + k} ${lo} Z`
        return (
          <g key={i}>
            <path d={d} className="wf-bus" />
            <text x={(s.x0 + s.x1) / 2} y={mid + 4} className="wf-bus-label" textAnchor="middle">
              {s.v}
            </text>
          </g>
        )
      })}
    </>
  )
}
