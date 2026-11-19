import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { CheckResult, SimulationResult } from '../types'
import { differingBits, formatTime, formatValue, type Radix } from '../waveformUtils'

const ROW_H = 30
// Rows are windowed against a generous height, so the list stays full when the pane is expanded.
const VIEW_H = 1400
const OVERSCAN = 6

type StatusFilter = 'all' | 'fail' | 'pass'
type SortBy = 'order' | 'status' | 'category'

interface Props {
  result: SimulationResult
  /** One VCD time unit in picoseconds, so check times can be shown in ns. */
  timescalePs?: number | null
  /** Jump the waveform cursor to the simulation time of a check. */
  onShowInWaveform?: (t: number) => void
}

const label = (c: string) => c.replace(/_/g, ' ')

function binString(hex: string): string {
  return hex
    .toLowerCase()
    .split('')
    .map((ch) => (ch === 'x' ? 'xxxx' : ch === 'z' ? 'zzzz' : /[0-9a-f]/.test(ch) ? parseInt(ch, 16).toString(2).padStart(4, '0') : '????'))
    .join('')
}

/** Binary text of `hex` with the bit positions in `diff` (0 = LSB) highlighted. */
function BitsView({ hex, diff, width }: { hex: string; diff: Set<number>; width: number }) {
  const bits = binString(hex).padStart(width, '0')
  return (
    <span className="tcv-bits">
      {bits.split('').map((b, i) => {
        const pos = bits.length - 1 - i
        const group = pos > 0 && pos % 4 === 0 ? ' ' : ''
        return (
          <span key={i}>
            <span className={diff.has(pos) ? 'tcv-bit-diff' : undefined}>{b}</span>
            {group}
          </span>
        )
      })}
    </span>
  )
}

export default function TestCasesView({ result, timescalePs = null, onShowInWaveform }: Props) {
  const checks = useMemo<CheckResult[]>(() => result.checks ?? [], [result.checks])
  const groups = result.check_groups ?? []
  const source = result.checks_source ?? 'none'

  const [status, setStatus] = useState<StatusFilter>('all')
  const [cats, setCats] = useState<Set<string>>(new Set())
  const [query, setQuery] = useState('')
  const [sortBy, setSortBy] = useState<SortBy>('order')
  const [radix, setRadix] = useState<Radix>('hex')
  const [selected, setSelected] = useState<number | null>(null)
  const [scrollTop, setScrollTop] = useState(0)

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    const out = checks.filter(
      (c) =>
        (status === 'all' || (status === 'fail' ? c.status === 'FAIL' : c.status === 'PASS')) &&
        (cats.size === 0 || cats.has(c.category)) &&
        (!q || c.name.toLowerCase().includes(q) || c.category.toLowerCase().includes(q)),
    )
    if (sortBy === 'status') out.sort((a, b) => (a.status === b.status ? a.idx - b.idx : a.status === 'FAIL' ? -1 : 1))
    else if (sortBy === 'category') out.sort((a, b) => a.category.localeCompare(b.category) || a.idx - b.idx)
    else out.sort((a, b) => a.idx - b.idx)
    return out
  }, [checks, status, cats, query, sortBy])

  const total = result.test_count
  const passed = result.pass_count
  const failed = result.fail_count
  const passPct = total > 0 ? (100 * passed) / total : 0

  if (source === 'none' && checks.length === 0 && groups.length === 0) {
    return (
      <div className="tcv" data-testid="tests-empty">
        <div className="tcv-summary">
          <span className="tcv-stat ok">{passed} passed</span>
          <span className={`tcv-stat ${failed ? 'bad' : ''}`}>{failed} failed</span>
          <span>of {total} checks</span>
        </div>
        <div className="tcv-note">
          This testbench did not log its individual checks, so only the totals are known. Testbenches that print one
          <code> CHK|…</code> line per comparison (the standard <code>chk</code> task) get a full per-test list here.
        </div>
      </div>
    )
  }

  const loggedPass = groups.reduce((n, g) => n + g.passed, 0)
  const loggedFail = groups.reduce((n, g) => n + g.failed, 0)
  const toggleCat = (c: string) =>
    setCats((prev) => {
      const next = new Set(prev)
      if (next.has(c)) next.delete(c)
      else next.add(c)
      return next
    })

  const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN)
  const end = Math.min(rows.length, Math.ceil((scrollTop + VIEW_H) / ROW_H) + OVERSCAN)
  const visible = rows.slice(start, end)
  const sel = selected != null ? checks.find((c) => c.idx === selected) ?? null : null
  const fmt = (v: string | null) => (v == null ? '—' : formatValue(v, Math.max(2, v.length * 4), radix))
  const when = (t: number | null) => (t == null ? '—' : formatTime(t, timescalePs))

  // One tab stop for the whole list, arrow keys move within it (self-review finding: every rendered row was a tab stop,
  // and rows outside the rendered window could not be reached from the keyboard at all).
  const viewportRef = useRef<HTMLDivElement>(null)
  const focusIdx = useRef<number | null>(null)
  const activeIdx = selected != null && rows.some((r) => r.idx === selected) ? selected : rows[0]?.idx
  useEffect(() => {
    if (focusIdx.current == null) return
    viewportRef.current?.querySelector<HTMLElement>(`[data-idx="${focusIdx.current}"]`)?.focus()
    focusIdx.current = null
  })
  const onRowKey = (e: KeyboardEvent<HTMLDivElement>, c: CheckResult) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setSelected(c.idx)
      return
    }
    const pos = rows.findIndex((r) => r.idx === c.idx)
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: 10, PageUp: -10 }[e.key]
    const target = e.key === 'Home' ? 0 : e.key === 'End' ? rows.length - 1 : step != null ? pos + step : null
    if (target == null) return
    e.preventDefault()
    const next = rows[Math.max(0, Math.min(rows.length - 1, target))]
    if (!next) return
    const nextPos = rows.indexOf(next)
    const vp = viewportRef.current
    if (vp) {
      const top = nextPos * ROW_H
      if (top < vp.scrollTop) vp.scrollTop = top
      else if (top + ROW_H > vp.scrollTop + vp.clientHeight) vp.scrollTop = top + ROW_H - vp.clientHeight
      setScrollTop(vp.scrollTop)
    }
    focusIdx.current = next.idx
    setSelected(next.idx)
  }

  return (
    <div className="tcv" data-testid="tests-view">
      <div className="tcv-summary">
        <span className="tcv-stat ok">{passed} passed</span>
        <span className={`tcv-stat ${failed ? 'bad' : ''}`}>{failed} failed</span>
        <span>of {total} checks</span>
        <div className="tcv-bar" role="img" aria-label={`${passed} of ${total} checks passed`}>
          <div className="tcv-bar-pass" style={{ width: `${passPct}%` }} />
        </div>
      </div>

      {groups.length > 0 && (
        <div className="tcv-chips" role="group" aria-label="Test types">
          {groups.map((g) => (
            <button
              key={g.category}
              className={`tcv-chip ${g.failed ? 'has-fail' : ''}`}
              aria-pressed={cats.has(g.category)}
              onClick={() => toggleCat(g.category)}
            >
              {label(g.category)}
              <span className="tcv-chip-n">
                {g.passed}/{g.total}
              </span>
            </button>
          ))}
          {cats.size > 0 && (
            <button className="tcv-chip" onClick={() => setCats(new Set())}>
              clear filter
            </button>
          )}
        </div>
      )}

      {source === 'legacy' && (
        <div className="tcv-note" data-testid="legacy-note">
          This testbench does not use the standard check lines, so only the failing checks are listed
          ({passed} passing checks are counted but not listed individually).
        </div>
      )}
      {source === 'structured' && result.checks_consistent === false && (
        <div className="tcv-note" data-testid="inconsistent-note">
          The testbench logged {loggedPass} passing and {loggedFail} failing check lines, but its own summary says{' '}
          {passed} passed and {failed} failed. The summary decides the verdict; treat the list as incomplete.
        </div>
      )}
      {result.checks_truncated && (
        <div className="tcv-note" data-testid="truncated-note">
          Showing {checks.length} of {result.checks_total_logged ?? total} checks. Every failure is listed first; the counts above are exact.
        </div>
      )}

      <div className="tcv-controls">
        <div className="tcv-seg" role="group" aria-label="Result filter">
          {(['all', 'fail', 'pass'] as StatusFilter[]).map((s) => (
            <button key={s} aria-pressed={status === s} onClick={() => setStatus(s)}>
              {s === 'all' ? 'All' : s === 'fail' ? 'Failed' : 'Passed'}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="Search tests"
          aria-label="Search tests"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setScrollTop(0)
          }}
        />
        <label>
          <span className="wfv-sr">Value format</span>
          <select aria-label="Value format" value={radix} onChange={(e) => setRadix(e.target.value as Radix)}>
            <option value="hex">hex</option>
            <option value="bin">bin</option>
            <option value="dec">dec</option>
          </select>
        </label>
        <span className="waveform-meta" style={{ marginBottom: 0 }}>
          {rows.length} shown
        </span>
      </div>

      <div className="tcv-table">
        <div className="tcv-headrow">
          <button onClick={() => setSortBy('order')} title="Sort by run order">#</button>
          <button onClick={() => setSortBy('category')} title="Sort by type">Type</button>
          <span>Test</span>
          <span>Time</span>
          <span>Expected</span>
          <span>Actual</span>
          <button onClick={() => setSortBy('status')} title="Failures first">Result</button>
        </div>
        <div
          className="tcv-viewport"
          ref={viewportRef}
          role="listbox"
          aria-label="Test cases"
          onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        >
          <div style={{ height: rows.length * ROW_H, position: 'relative' }}>
            {rows.length === 0 && (
              <div className="empty-state">
                {checks.length === 0 && groups.length > 0
                  ? 'The per-check detail was not kept for this run (it ended before the final report), so only the totals above are available.'
                  : 'No checks match this filter.'}
              </div>
            )}
            {visible.map((c, i) => (
              <div
                key={c.idx}
                role="option"
                aria-selected={selected === c.idx}
                tabIndex={c.idx === activeIdx ? 0 : -1}
                data-idx={c.idx}
                className={`tcv-row ${c.status === 'FAIL' ? 'fail' : ''}`}
                style={{ top: (start + i) * ROW_H }}
                onClick={() => setSelected(c.idx)}
                onKeyDown={(e) => onRowKey(e, c)}
                data-testid="check-row"
              >
                <span className="tcv-cell">{c.idx}</span>
                <span className="tcv-cell">{label(c.category)}</span>
                <span className="tcv-cell" title={c.name}>{c.name}</span>
                <span className="tcv-cell">{when(c.t)}</span>
                <span className="tcv-cell">{fmt(c.expected)}</span>
                <span className="tcv-cell">{fmt(c.actual)}</span>
                <span className={`tcv-cell ${c.status === 'PASS' ? 'tcv-pass' : 'tcv-fail'}`}>{c.status === 'PASS' ? '✓ pass' : '✗ FAIL'}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {sel && (
        <div className="tcv-detail" data-testid="check-detail">
          <div>
            <strong>{sel.name}</strong> · {label(sel.category)} · {when(sel.t)} ·{' '}
            <span className={sel.status === 'PASS' ? 'tcv-pass' : 'tcv-fail'}>{sel.status}</span>
          </div>
          {sel.expected != null && sel.actual != null && (
            <>
              {(() => {
                const diff = new Set(sel.status === 'FAIL' ? differingBits(sel.expected, sel.actual) : [])
                const width = Math.max(binString(sel.expected).length, binString(sel.actual).length)
                return (
                  <>
                    <div>
                      expected <BitsView hex={sel.expected} diff={diff} width={width} />
                    </div>
                    <div>
                      actual&nbsp;&nbsp;&nbsp;<BitsView hex={sel.actual} diff={diff} width={width} />
                    </div>
                    {diff.size > 0 && (
                      <div className="waveform-meta" style={{ marginBottom: 0 }}>
                        differing bits: {[...diff].sort((a, b) => b - a).join(', ')}
                      </div>
                    )}
                  </>
                )
              })()}
            </>
          )}
          {sel.detail && <div>{sel.detail}</div>}
          {sel.t != null && onShowInWaveform && (
            <div>
              <button className="btn btn-secondary wfv-btn" onClick={() => onShowInWaveform(sel.t as number)}>
                Show in waveform
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
