import { useState, useMemo } from 'react'
import type { Waveform } from '../types'

const LABEL_W = 90
const PLOT_W = 1000
const ROW_H = 30
const ROW_GAP = 10
const PAD_Y = 8
const MIN_SCALE = 0.5
const MAX_SCALE = 4

function formatBusValue(v: string): string {
  if (v === 'x' || v === 'z' || v === 'X' || v === 'Z') return v.toLowerCase()
  if (/^[xz]+$/i.test(v)) return v.toLowerCase()
  if (v.startsWith('0x') || v.startsWith('0X')) return v.toLowerCase()
  return `0x${v}`
}

export default function WaveformViewer({ waveform }: { waveform: Waveform | null }) {
  const [scale, setScale] = useState(1)
  const [translateX, setTranslateX] = useState(0)

  const handleZoomIn = () => setScale((s) => Math.min(MAX_SCALE, Number((s * 1.25).toFixed(2))))
  const handleZoomOut = () => setScale((s) => Math.max(MIN_SCALE, Number((s / 1.25).toFixed(2))))
  const handleReset = () => {
    setScale(1)
    setTranslateX(0)
  }

  if (!waveform || waveform.signals.length === 0) {
    return <div className="empty-state">No waveform. Run a simulation to capture a VCD.</div>
  }

  const end = Math.max(waveform.end_time, 1)
  const rows = waveform.signals
  const height = PAD_Y * 2 + rows.length * (ROW_H + ROW_GAP)
  const scaledPlotW = PLOT_W * scale
  const totalW = LABEL_W + scaledPlotW + 20
  // memoize x() so BusWave/BitWave deps stay stable – avoids recreating on each render
  const x = useMemo(
    () => (t: number) => LABEL_W + (t / end) * scaledPlotW + translateX,
    [end, scaledPlotW, translateX],
  )

  const ticks = useMemo(() => Array.from({ length: 6 }, (_, i) => Math.round((i / 5) * end)), [end])

  return (
    <div className="waveform-viewer">
      <div className="waveform-toolbar" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <div className="waveform-meta" style={{ marginBottom: 0, flex: '1 1 auto' }}>
          timescale {waveform.timescale} · {end} time units · {rows.length} signals
        </div>
        <div className="waveform-controls" style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.55rem', fontSize: '0.8rem' }} onClick={handleZoomOut} aria-label="Zoom out">
            <i className="fa-solid fa-minus" /> <span>−</span>
          </button>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.55rem', fontSize: '0.8rem' }} onClick={handleReset} aria-label="Reset zoom">
            Reset
          </button>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.55rem', fontSize: '0.8rem' }} onClick={handleZoomIn} aria-label="Zoom in">
            <i className="fa-solid fa-plus" /> <span>+</span>
          </button>
        </div>
      </div>
      {waveform.truncated && (
        <div
          className="waveform-truncation-notice"
          data-testid="truncation-notice"
          style={{
            padding: '6px 12px',
            marginBottom: 8,
            borderRadius: 8,
            background: 'rgba(245,158,11,0.15)',
            color: '#f59e0b',
            fontSize: 13,
            border: '1px solid rgba(245,158,11,0.35)',
          }}
        >
          {waveform.dropped_signals > 0 && `${waveform.dropped_signals} signal(s) hidden (max 40 shown). `}
          {waveform.changes_truncated && 'Some signals have value changes truncated (max 2000 per signal).'}
        </div>
      )}

      {/* Time ruler / minimap */}
      <div
        className="waveform-ruler"
        style={{
          display: 'flex',
          alignItems: 'center',
          marginLeft: LABEL_W,
          width: scaledPlotW,
          minWidth: scaledPlotW,
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          padding: '2px 0 6px',
          borderBottom: '1px dashed rgba(255,255,255,0.08)',
          marginBottom: 4,
          boxSizing: 'border-box',
        }}
        aria-label="time ruler"
      >
        {ticks.map((t, idx) => (
          <span
            key={idx}
            style={{
              flex: 1,
              textAlign: idx === 0 ? 'left' : idx === 5 ? 'right' : 'center',
              borderLeft: idx !== 0 ? '1px solid rgba(255,255,255,0.08)' : 'none',
              paddingLeft: idx !== 0 ? 4 : 0,
            }}
          >
            {t}
          </span>
        ))}
      </div>

      <div className="waveform-scroll" style={{ overflowX: 'auto', overflowY: 'hidden', paddingBottom: 4 }}>
        <svg
          className="waveform-svg"
          viewBox={`0 0 ${totalW} ${height}`}
          width={totalW}
          height={height}
          preserveAspectRatio="xMinYMin meet"
          style={{ display: 'block', minWidth: totalW }}
        >
          {/* ruler tick lines inside SVG */}
          {ticks.map((t, idx) => {
            const xt = x(t)
            return (
              <line
                key={`tick-${idx}`}
                x1={xt}
                x2={xt}
                y1={PAD_Y - 2}
                y2={height - 2}
                stroke="rgba(255,255,255,0.06)"
                strokeWidth={0.8}
                strokeDasharray={idx === 0 || idx === 5 ? undefined : '3 4'}
              />
            )
          })}
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

      {/* Hidden pan helper: keeps translateX state useful for future drag; Reset already clears it */}
      <div style={{ display: 'none' }} data-scale={scale} data-translate-x={translateX} />
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
        const label = formatBusValue(s.v)
        const segW = s.x1 - s.x0
        const showLabel = segW > 28
        return (
          <g key={i}>
            <path d={d} className="wf-bus" />
            {showLabel && (
              <text x={(s.x0 + s.x1) / 2} y={mid + 4} className="wf-bus-label" textAnchor="middle">
                {label}
              </text>
            )}
          </g>
        )
      })}
    </>
  )
}
