// Structural accessibility checks (names, roles, required parents/children, heading order) with
// axe-core. Colour contrast is NOT checked here: jsdom has no layout or computed colours, so that
// rule is covered by the real-browser audit instead.
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import axe from 'axe-core'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import ResultsPanel from '../components/ResultsPanel'
import TestCasesView from '../components/TestCasesView'
import CodeEditor from '../components/CodeEditor'
import type { RunResponse, SimulationResult, Waveform } from '../types'

vi.mock('../api', () => ({
  getModels: vi.fn(), streamDesign: vi.fn(), reSimulate: vi.fn(), exportUVM: vi.fn(),
  listProjects: vi.fn(), deleteProject: vi.fn(), getProject: vi.fn(),
}))

async function violations(container: HTMLElement) {
  const r = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
  return r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(' | ')})`)
}

const wave: Waveform = {
  timescale: '1ps', timescale_ps: 1, end_time: 100_000, truncated: false, dropped_signals: 0, changes_truncated: false,
  signals: [
    { name: 'clk', width: 1, role: 'clock', wave: [{ t: 0, v: '0' }, { t: 10_000, v: '1' }] },
    { name: 'count', width: 4, role: 'out', wave: [{ t: 0, v: 'x' }, { t: 20_000, v: '1' }] },
  ],
}
const result = {
  status: 'FAIL', module_name: 'counter', simulation_time_ns: 100, test_count: 3, pass_count: 2, fail_count: 1,
  coverage: { pass_rate: 66 }, errors: [], waveform_file: null, transcript_file: null, log_excerpt: 'FAIL: x',
  checks: [
    { idx: 1, status: 'PASS', category: 'reset', name: 'a', t: 1000, expected: '0', actual: '0', detail: '', source: 'chk' },
    { idx: 2, status: 'PASS', category: 'directed', name: 'b', t: 2000, expected: '1', actual: '1', detail: '', source: 'chk' },
    { idx: 3, status: 'FAIL', category: 'directed', name: 'c', t: 3000, expected: '2', actual: '4', detail: '', source: 'chk' },
  ],
  check_groups: [{ category: 'reset', total: 1, passed: 1, failed: 0 }, { category: 'directed', total: 2, passed: 1, failed: 1 }],
  checks_source: 'structured', checks_consistent: true, checks_truncated: false, checks_total_logged: 3,
} as SimulationResult

describe('accessibility (axe-core, structural rules)', () => {
  beforeEach(() => vi.clearAllMocks())

  it('every Results tab has no violations, with strength and synthesis cards showing', async () => {
    const { container } = render(
      <ResultsPanel
        result={result} waveform={wave} schematic={null} history={[]}
        synthesis={{ available: true, cell_count: 10, flip_flops: 4, latches: 0, cell_types: [['AND', 5]] }}
        strength={{ status: 'ok', total: 8, killed: 7, invalid: 0, seconds: 1, note: 'n', survivors: [{ description: '`+` to `-`', line: 3 }] }}
      />,
    )
    for (const name of [/Results/, /Test cases/, /Waveform/, /Schematic/]) {
      fireEvent.click(screen.getByRole('tab', { name }))
      expect(await violations(container), String(name)).toEqual([])
    }
  })

  it('the tab list contains only tabs', () => {
    render(<ResultsPanel result={result} waveform={wave} schematic={null} history={[]} design={<div />} />)
    const list = screen.getByRole('tablist')
    expect([...list.children].every((c) => c.getAttribute('role') === 'tab')).toBe(true)
  })

  it('the test cases table has no violations with a row selected', async () => {
    const { container } = render(<TestCasesView result={result} />)
    fireEvent.click(screen.getAllByTestId('check-row')[2])
    expect(await violations(container)).toEqual([])
  })

  it('the code editor names its text box and keeps Copy outside the tab list', async () => {
    const { container } = render(
      <CodeEditor rtl="module m; endmodule" tb="module testbench; endmodule" onRtlChange={() => {}} onTbChange={() => {}} moduleName="m" />,
    )
    await waitFor(() => expect(container.querySelector('.cm-content')).not.toBeNull())
    expect(container.querySelector('.cm-content')?.getAttribute('aria-label')).toBe('RTL source code editor')
    fireEvent.click(screen.getByRole('tab', { name: /tb_m\.sv/ }))
    await waitFor(() => expect(container.querySelector('.cm-content')?.getAttribute('aria-label')).toBe('Testbench source code editor'))
    const list = screen.getByRole('tablist')
    expect([...list.children].every((c) => c.getAttribute('role') === 'tab')).toBe(true)
    expect(await violations(container)).toEqual([])
  })

  it('the page has one h1 and the panel titles are h2', async () => {
    vi.resetModules()
    const api = await import('../api')
    vi.mocked(api.getModels).mockResolvedValue({ models: [], current: null, offline: true } as never)
    vi.mocked(api.listProjects).mockResolvedValue({ total: 0, projects: [] })
    vi.doMock('../components/CodeEditor', () => ({ default: () => <div /> }))
    const { default: App } = await import('../App')
    const { container } = render(<App />)
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim())).toEqual(expect.arrayContaining(['Describe the block']))
    expect(await violations(container)).toEqual([])
  })
})

export type _Unused = RunResponse // keeps the import used if the shape check above is extended
