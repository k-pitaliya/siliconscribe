import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
import type { Waveform, WaveformSignal } from '../types'
import {
  bitPath,
  busSegments,
  formatTime,
  formatValue,
  groupSignals,
  timeTicks,
  unitPs,
  valueAt,
  type Radix,
} from '../waveformUtils'

const NAME_W = 224
const ROW_H = 28
const GROUP_H = 24
const HEAD_H = 38
const FALLBACK_PLOT_W = 1000 // used until the container has been measured (and in jsdom)
const MIN_PLOT_W = 420
const MIN_ZOOM = 1 // 1 = the whole run fits the pane; zooming out further only wastes space
const MAX_ZOOM = 64
const CHAR_PX = 6.4

/** A point on the time axis worth flagging, e.g. the simulation time of a failed check. */
export interface WaveformMarker {
  t: number
  label?: string
}

interface Props {
  waveform: Waveform | null
  /** Flags drawn on the time ruler (clickable). Typically the failed checks. */
  markers?: WaveformMarker[]
  /** When set, the viewer pins cursor A at this time and scrolls to it. */
  focusTime?: number | null
  /** Changes on every request so the same time can be re-focused. */
  focusSeq?: number
  onMarkerClick?: (t: number) => void
}

type Item =
  | { kind: 'group'; key: string; label: string; count: number; y: number; open: boolean }
  | { kind: 'sig'; key: string; sig: WaveformSignal; y: number; index: number }

export default function WaveformViewer({ waveform, markers = [], focusTime = null, focusSeq = 0, onMarkerClick }: Props) {
  const [zoom, setZoom] = useState(1)
  const [radix, setRadix] = useState<Radix>('hex')
  const [hover, setHover] = useState<number | null>(null)
  const [pinA, setPinA] = useState<number | null>(null)
  const [pinB, setPinB] = useState<number | null>(null)
  const [showHidden, setShowHidden] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [filter, setFilter] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<SVGSVGElement>(null)
  const [viewW, setViewW] = useState(0)

  // All hooks must run on every render, so compute safe values first and guard afterwards.
  const signals = useMemo(() => waveform?.signals ?? [], [waveform])
  const end = Math.max(waveform?.end_time ?? 1, 1)
  const ps = unitPs(waveform?.timescale ?? '', waveform?.timescale_ps)
  // Zoom 1 fits the whole run into the visible pane, so nothing is hidden off to the right by default.
  const basePlotW = viewW > 0 ? Math.max(MIN_PLOT_W, viewW - NAME_W - 2) : FALLBACK_PLOT_W
  const plotW = basePlotW * zoom
  const x = useCallback((t: number) => (t / end) * plotW, [end, plotW])

  const groups = useMemo(() => groupSignals(signals, filter), [signals, filter])
  const hiddenCount = useMemo(
    () => groups.filter((g) => g.hiddenByDefault).reduce((n, g) => n + g.signals.length, 0),
    [groups],
  )
  const visibleGroups = useMemo(() => groups.filter((g) => showHidden || !g.hiddenByDefault), [groups, showHidden])
  const showHeaders = visibleGroups.length > 1

  const { items, bodyH } = useMemo(() => {
    let y = HEAD_H
    let index = 0
    const out: Item[] = []
    for (const g of visibleGroups) {
      const open = !collapsed.has(g.key)
      if (showHeaders) {
        out.push({ kind: 'group', key: `g-${g.key}`, label: g.label, count: g.signals.length, y, open })
        y += GROUP_H
      }
      if (open) {
        for (const sig of g.signals) {
          out.push({ kind: 'sig', key: `${sig.path ?? sig.name}-${index}`, sig, y, index })
          y += ROW_H
          index += 1
        }
      }
    }
    return { items: out, bodyH: y + 4 }
  }, [visibleGroups, collapsed, showHeaders])

  const ticks = useMemo(() => timeTicks(end, plotW), [end, plotW])
  const markerTimes = useMemo(() => markers.map((m) => m.t).sort((a, b) => a - b), [markers])

  const zoomAt = useCallback(
    (factor: number, clientX?: number) => {
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number((zoom * factor).toFixed(3))))
      if (next === zoom) return
      const el = scrollRef.current
      if (!el) {
        setZoom(next)
        return
      }
      const rect = el.getBoundingClientRect()
      const anchor = clientX != null ? clientX - rect.left : NAME_W + (el.clientWidth - NAME_W) / 2
      const tAnchor = ((el.scrollLeft + anchor - NAME_W) / plotW) * end
      setZoom(next)
      requestAnimationFrame(() => {
        el.scrollLeft = Math.max(0, (tAnchor / end) * basePlotW * next + NAME_W - anchor)
      })
    },
    [zoom, plotW, end, basePlotW],
  )

  const resetView = useCallback(() => {
    setZoom(1)
    if (scrollRef.current) scrollRef.current.scrollLeft = 0
  }, [])

  const scrollToTime = useCallback(
    (t: number) => {
      const el = scrollRef.current
      if (el) el.scrollLeft = Math.max(0, x(t) + NAME_W - (el.clientWidth + NAME_W) / 2)
    },
    [x],
  )

  // Track the pane width so zoom 1 always means "fit". The scroll container only exists once there is a waveform.
  const hasWave = signals.length > 0
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return undefined
    setViewW(el.clientWidth)
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(() => setViewW(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [hasWave])

  // Ctrl/Cmd + wheel zooms about the pointer. Needs a non-passive native listener to stop page zoom.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return undefined
    const onWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return
      e.preventDefault()
      zoomAt(e.deltaY < 0 ? 1.25 : 1 / 1.25, e.clientX)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, hasWave])

  // A request from outside (clicking a check in the Test cases tab) pins cursor A and scrolls to it.
  useEffect(() => {
    if (focusTime == null) return
    setPinA(focusTime)
    scrollToTime(focusTime)
    // Only when the requested time changes; zooming afterwards must not re-scroll.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusTime, focusSeq])

  if (!waveform || signals.length === 0) {
    return <div className="empty-state">No waveform. Run a simulation to capture a VCD.</div>
  }

  const timeAt = (e: MouseEvent) => {
    const r = plotRef.current?.getBoundingClientRect()
    if (!r) return null
    return Math.round(Math.min(end, Math.max(0, ((e.clientX - r.left) / plotW) * end)))
  }

  const stepMarker = (dir: 1 | -1) => {
    const cur = pinA ?? (dir > 0 ? -1 : Infinity)
    const next = dir > 0 ? markerTimes.find((t) => t > cur) : [...markerTimes].reverse().find((t) => t < cur)
    if (next != null) {
      setPinA(next)
      scrollToTime(next)
    }
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const tag = (e.target as HTMLElement).tagName
    if (tag === 'INPUT' || tag === 'SELECT') return
    if (e.key === '+' || e.key === '=') zoomAt(1.25)
    else if (e.key === '-') zoomAt(1 / 1.25)
    else if (e.key === '0') resetView()
    else if (e.key === ']') stepMarker(1)
    else if (e.key === '[') stepMarker(-1)
    else if (e.key === 'Escape') {
      setPinA(null)
      setPinB(null)
    } else return
    e.preventDefault()
  }

  const cursorT = hover ?? pinA
  const fmt = (t: number) => formatTime(t, ps)
  const allCount = signals.length
  const markerSet = markers
  const readout =
    cursorT == null
      ? ''
      : `Cursor at ${fmt(cursorT)}: ` +
        signals
          .filter((s) => (s.role ?? 'internal') !== 'aux' && (s.role ?? 'internal') !== 'param')
          .slice(0, 8)
          .map((s) => `${s.name}=${formatValue(valueAt(s.wave, cursorT) ?? 'x', s.width, radix)}`)
          .join(', ')

  const widthTag = (s: WaveformSignal) =>
    s.width > 1 ? `[${s.msb != null && s.lsb != null ? `${s.msb}:${s.lsb}` : `${s.width - 1}:0`}]` : ''

  return (
    <div className="waveform-viewer wfv" tabIndex={0} onKeyDown={onKeyDown} aria-label="Waveform viewer">
      <div className="waveform-toolbar wfv-toolbar">
        <div className="waveform-meta" style={{ marginBottom: 0, flex: '1 1 auto' }}>
          {`timescale ${waveform.timescale} · ${ps == null ? `${end} time units` : fmt(end)} · ${allCount} signals`}
        </div>
        <label className="wfv-field">
          <span className="wfv-sr">Radix</span>
          <select aria-label="Radix" value={radix} onChange={(e) => setRadix(e.target.value as Radix)}>
            <option value="hex">hex</option>
            <option value="bin">bin</option>
            <option value="dec">dec</option>
          </select>
        </label>
        <input
          className="wfv-filter"
          type="search"
          placeholder="Filter signals"
          aria-label="Filter signals"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <div className="waveform-controls" style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button className="btn btn-secondary wfv-btn" onClick={() => zoomAt(1 / 1.25)} aria-label="Zoom out">
            <span>−</span>
          </button>
          <button className="btn btn-secondary wfv-btn" onClick={resetView} aria-label="Reset zoom">
            Reset
          </button>
          <button className="btn btn-secondary wfv-btn" onClick={() => zoomAt(1.25)} aria-label="Zoom in">
            <span>+</span>
          </button>
        </div>
      </div>

      <div className="wfv-subbar">
        {hiddenCount > 0 && (
          <button className="wfv-link" onClick={() => setShowHidden((v) => !v)} aria-pressed={showHidden}>
            {showHidden ? 'Hide' : 'Show'} testbench variables, task locals and parameters ({hiddenCount})
          </button>
        )}
        {(pinA != null || pinB != null) && (
          <span className="wfv-pins" data-testid="pin-readout">
            {pinA != null && <span className="wfv-pin-a">A {fmt(pinA)}</span>}
            {pinB != null && <span className="wfv-pin-b">B {fmt(pinB)}</span>}
            {pinA != null && pinB != null && <span>Δ {fmt(Math.abs(pinB - pinA))}</span>}
            <button
              className="wfv-link"
              onClick={() => {
                setPinA(null)
                setPinB(null)
              }}
            >
              Clear
            </button>
          </span>
        )}
        <span className="wfv-hint">Click: place A · Shift+click: place B · Ctrl/Cmd+scroll: zoom · [ ] jump between failed checks</span>
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

      <div className="wfv-sr" aria-live="polite">
        {readout}
      </div>

      <div className="waveform-scroll wfv-scroll" ref={scrollRef} style={{ overflowX: 'auto', overflowY: 'auto' }}>
        <div className="wfv-body" style={{ width: NAME_W + plotW }}>
          <div className="wfv-names" style={{ width: NAME_W, height: bodyH }}>
            <div className="wfv-head" style={{ height: HEAD_H }}>
              {cursorT != null ? `⌖ ${fmt(cursorT)}` : 'signal'}
            </div>
            {items.map((it) =>
              it.kind === 'group' ? (
                <button
                  key={it.key}
                  className="wfv-group"
                  style={{ top: it.y, height: GROUP_H }}
                  aria-expanded={it.open}
                  onClick={() =>
                    setCollapsed((prev) => {
                      const next = new Set(prev)
                      const k = it.key.slice(2)
                      if (next.has(k)) next.delete(k)
                      else next.add(k)
                      return next
                    })
                  }
                >
                  <span aria-hidden="true">{it.open ? '▾' : '▸'}</span> {it.label} <span className="wfv-count">{it.count}</span>
                </button>
              ) : (
                <div key={it.key} className="wfv-name" style={{ top: it.y, height: ROW_H }} title={it.sig.path || it.sig.name}>
                  <span className="wf-label wfv-sig-name">{it.sig.name}</span>
                  {widthTag(it.sig) && <span className="wfv-width">{widthTag(it.sig)}</span>}
                  {cursorT != null && (
                    <span className="wfv-val" data-testid="cursor-value">
                      {formatValue(valueAt(it.sig.wave, cursorT) ?? 'x', it.sig.width, radix)}
                    </span>
                  )}
                </div>
              ),
            )}
          </div>

          <svg
            className="waveform-svg wfv-plot"
            ref={plotRef}
            width={plotW}
            height={bodyH}
            viewBox={`0 0 ${plotW} ${bodyH}`}
            role="group"
            aria-label={`Waveform plot with ${allCount} signals`}
            onMouseMove={(e) => setHover(timeAt(e))}
            onMouseLeave={() => setHover(null)}
            onClick={(e) => {
              const t = timeAt(e)
              if (t == null) return
              if (e.shiftKey) setPinB(t)
              else setPinA(t)
            }}
          >
            <defs>
              <pattern id="wfv-hatch-x" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="rgba(239,68,68,0.18)" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="#ff6b6b" strokeWidth="2" />
              </pattern>
              <pattern id="wfv-hatch-trunc" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="8" height="8" fill="rgba(148,163,184,0.10)" />
                <line x1="0" y1="0" x2="0" y2="8" stroke="rgba(148,163,184,0.5)" strokeWidth="1.5" />
              </pattern>
            </defs>

            {/* time ruler, drawn with the SAME x() as the signals so they can never drift apart */}
            <g aria-label="time ruler" className="wfv-ruler">
              <rect x={0} y={0} width={plotW} height={HEAD_H} className="wfv-ruler-bg" />
              {ticks.map((t) => (
                <g key={`tk-${t}`}>
                  <line x1={x(t)} x2={x(t)} y1={HEAD_H - 8} y2={bodyH} className="wfv-grid" />
                  <text x={x(t) + 4} y={14} className="wfv-tick">
                    {fmt(t)}
                  </text>
                </g>
              ))}
              {markerSet.map((m, i) => (
                <g
                  key={`mk-${i}-${m.t}`}
                  className={`wfv-marker${m.t === markerTimes[0] ? ' first' : ''}`}
                  role="img" /* informative flag; keyboard users step between failures with [ and ] */
                  aria-label={`Failed check at ${fmt(m.t)}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    setPinA(m.t)
                    onMarkerClick?.(m.t)
                  }}
                >
                  {m.t === markerTimes[0] && (
                    <line x1={x(m.t)} x2={x(m.t)} y1={HEAD_H - 4} y2={bodyH} className="wfv-marker-line" />
                  )}
                  <title>{`${m.t === markerTimes[0] ? 'First failed check' : 'Failed check'}${m.label ? `: ${m.label}` : ''} at ${fmt(m.t)}`}</title>
                  <polygon points={`${x(m.t) - 4},${HEAD_H - 14} ${x(m.t) + 4},${HEAD_H - 14} ${x(m.t)},${HEAD_H - 5}`} />
                </g>
              ))}
            </g>

            {items.map((it) => {
              if (it.kind === 'group') {
                return <rect key={it.key} x={0} y={it.y} width={plotW} height={GROUP_H} className="wfv-group-bg" />
              }
              const s = it.sig
              const hi = it.y + 5
              const lo = it.y + ROW_H - 5
              const mid = (hi + lo) / 2
              const sigEnd = s.truncated_at != null ? s.truncated_at : end
              const endX = x(sigEnd)
              return (
                <g key={it.key} className="wfv-row">
                  <rect x={0} y={it.y} width={plotW} height={ROW_H} className={it.index % 2 ? 'wfv-stripe' : 'wfv-stripe-alt'} />
                  {s.width === 1 ? (
                    <BitRow wave={s.wave} x={x} hi={hi} lo={lo} endX={endX} />
                  ) : (
                    <BusRow wave={s.wave} x={x} hi={hi} lo={lo} mid={mid} endX={endX} width={s.width} radix={radix} />
                  )}
                  {s.truncated_at != null && (
                    <g>
                      <rect x={endX} y={it.y + 2} width={Math.max(0, x(end) - endX)} height={ROW_H - 4} fill="url(#wfv-hatch-trunc)" />
                      <title>value history truncated here</title>
                    </g>
                  )}
                </g>
              )
            })}

            {hover != null && <line x1={x(hover)} x2={x(hover)} y1={HEAD_H} y2={bodyH} className="wfv-cursor" />}
            {pinA != null && <line x1={x(pinA)} x2={x(pinA)} y1={0} y2={bodyH} className="wfv-cursor-a" />}
            {pinB != null && <line x1={x(pinB)} x2={x(pinB)} y1={0} y2={bodyH} className="wfv-cursor-b" />}
          </svg>
        </div>
      </div>
    </div>
  )
}

type Wave = { t: number; v: string }[]

function BitRow({ wave, x, hi, lo, endX }: { wave: Wave; x: (t: number) => number; hi: number; lo: number; endX: number }) {
  const { d, dense } = useMemo(() => bitPath(wave, x, hi, lo, endX), [wave, x, hi, lo, endX])
  if (wave.length === 0) return null
  // Unknown / high-impedance stretches get their own look so they cannot be mistaken for a level.
  const unknown: { x0: number; x1: number; z: boolean }[] = []
  for (let i = 0; i < wave.length; i++) {
    const v = wave[i].v
    if (v !== 'x' && v !== 'z') continue
    unknown.push({ x0: x(wave[i].t), x1: i + 1 < wave.length ? x(wave[i + 1].t) : endX, z: v === 'z' })
  }
  return (
    <>
      <path d={d} className="wf-bit wfv-bit" fill="none" />
      {dense.map((b, i) => (
        <rect key={`d-${i}`} x={b.x0} y={hi} width={Math.max(1, b.x1 - b.x0)} height={lo - hi} className="wfv-dense" />
      ))}
      {unknown.map((u, i) => (
        <rect
          key={`u-${i}`}
          x={u.x0}
          y={hi}
          width={Math.max(1, u.x1 - u.x0)}
          height={lo - hi}
          fill={u.z ? 'rgba(251,191,36,0.25)' : 'url(#wfv-hatch-x)'}
        />
      ))}
    </>
  )
}

function BusRow({
  wave,
  x,
  hi,
  lo,
  mid,
  endX,
  width,
  radix,
}: {
  wave: Wave
  x: (t: number) => number
  hi: number
  lo: number
  mid: number
  endX: number
  width: number
  radix: Radix
}) {
  const segs = useMemo(() => busSegments(wave, x, endX), [wave, x, endX])
  return (
    <>
      {segs.map((s, i) => {
        if (s.dense) {
          return <rect key={i} x={s.x0} y={hi} width={Math.max(1, s.x1 - s.x0)} height={lo - hi} className="wfv-dense" />
        }
        const w = s.x1 - s.x0
        const k = Math.min(3, w / 3)
        const d = `M ${s.x0} ${mid} L ${s.x0 + k} ${hi} L ${s.x1 - k} ${hi} L ${s.x1} ${mid} L ${s.x1 - k} ${lo} L ${s.x0 + k} ${lo} Z`
        const hasX = s.v.includes('x')
        const allZ = s.v === 'z'
        const label = formatValue(s.v, width, radix)
        const fits = w > label.length * CHAR_PX + 12
        return (
          <g key={i}>
            <path d={d} className={hasX ? 'wfv-bus-x' : allZ ? 'wfv-bus-z' : 'wf-bus'} fill={hasX ? 'url(#wfv-hatch-x)' : undefined} />
            {fits && (
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
