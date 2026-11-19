import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import SchematicView, { MAX_DRAWN_CELLS } from '../SchematicView'
import type { Schematic, SynthesisInfo, YosysNetlist } from '../../types'

const renderNetlist = vi.fn()
vi.mock('../../netlistRender', () => ({ renderNetlist: (n: unknown) => renderNetlist(n) }))

const schematic: Schematic = {
  module_name: 'counter',
  inputs: [{ name: 'clk', width: 1 }, { name: 'enable', width: 1 }],
  outputs: [{ name: 'count', width: 4 }],
} as Schematic

function netlist(n: number, type = '$_AND_'): YosysNetlist {
  const cells: Record<string, { type: string }> = {}
  for (let k = 0; k < n; k++) cells[`c${k}`] = { type }
  return { modules: { counter: { ports: {}, cells } } }
}

const synthesis = (extra: Partial<SynthesisInfo> = {}): SynthesisInfo => ({
  available: true, cell_count: 10, rtl_netlist: netlist(3, '$add'), json_netlist: netlist(10), ...extra,
})

beforeEach(() => {
  renderNetlist.mockReset()
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:schematic')
  globalThis.URL.revokeObjectURL = vi.fn()
})

describe('SchematicView', () => {
  it('starts on the block diagram and does not load the netlist renderer', () => {
    render(<SchematicView schematic={schematic} synthesis={synthesis()} />)
    expect(screen.getByRole('button', { name: 'Block diagram' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('img', { name: 'Schematic for module counter' })).toBeInTheDocument()
    expect(renderNetlist).not.toHaveBeenCalled()
  })

  it('draws the gate-level netlist of this run as an image, with its cell count', async () => {
    renderNetlist.mockResolvedValue('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    const syn = synthesis()
    render(<SchematicView schematic={schematic} synthesis={syn} />)
    fireEvent.click(screen.getByRole('button', { name: 'Gate level' }))
    const img = await screen.findByRole('img', { name: 'Gate level schematic of counter: 10 cells' })
    expect(img).toHaveAttribute('src', 'blob:schematic')
    expect(renderNetlist).toHaveBeenCalledWith(syn.json_netlist)          // the gate netlist, not the RTL one
    expect(screen.getByText(/generic cells, not sky130/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download SVG' })).toHaveAttribute('download', 'counter_gate_schematic.svg')
  })

  it('draws the RTL-cells netlist for the RTL view', async () => {
    renderNetlist.mockResolvedValue('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    const syn = synthesis()
    render(<SchematicView schematic={schematic} synthesis={syn} />)
    fireEvent.click(screen.getByRole('button', { name: 'RTL cells' }))
    await screen.findByRole('img', { name: 'RTL cells schematic of counter: 3 cells' })
    expect(renderNetlist).toHaveBeenCalledWith(syn.rtl_netlist)
  })

  it('refuses to draw a netlist above the size limit and points to the RTL view', () => {
    render(<SchematicView schematic={schematic} synthesis={synthesis({ json_netlist: netlist(MAX_DRAWN_CELLS + 1) })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Gate level' }))
    expect(screen.getByRole('status')).toHaveTextContent(`${MAX_DRAWN_CELLS + 1} cells is too many`)
    expect(screen.getByRole('status')).toHaveTextContent('RTL cells view')
    expect(renderNetlist).not.toHaveBeenCalled()
  })

  it('reports a layout failure instead of showing nothing', async () => {
    renderNetlist.mockRejectedValue(new Error('The schematic could not be laid out.'))
    render(<SchematicView schematic={schematic} synthesis={synthesis()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Gate level' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Could not draw this netlist'))
  })

  it('disables the netlist views and says why when Yosys is missing', () => {
    render(<SchematicView schematic={schematic} synthesis={{ available: false }} />)
    const gate = screen.getByRole('button', { name: 'Gate level' })
    expect(gate).toBeDisabled()
    expect(gate).toHaveAttribute('title', expect.stringContaining('Yosys'))
    expect(screen.getByRole('button', { name: 'RTL cells' })).toBeDisabled()
  })
})

describe('SchematicView: review findings', () => {
  it('falls back to an available view when a new run removes the selected netlist', async () => {
    renderNetlist.mockResolvedValue('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    const { rerender } = render(<SchematicView schematic={schematic} synthesis={synthesis()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Gate level' }))
    await screen.findByRole('img', { name: /Gate level schematic/ })
    rerender(<SchematicView schematic={schematic} synthesis={{ available: true }} />)       // new run: no netlist yet
    await waitFor(() => expect(screen.getByRole('button', { name: 'Block diagram' })).toHaveAttribute('aria-pressed', 'true'))
    expect(screen.getByRole('img', { name: 'Schematic for module counter' })).toBeInTheDocument()
  })

  it('explains a missing netlist with the real synthesis error', () => {
    render(<SchematicView schematic={schematic} synthesis={{ available: true, error: 'ERROR: syntax error near line 4' }} />)
    expect(screen.getByRole('button', { name: 'Gate level' })).toHaveAttribute('title', expect.stringContaining('syntax error near line 4'))
  })
})

describe('SchematicView block diagram (self-review findings)', () => {
  it('draws every inout port and gives long labels room', () => {
    const s = {
      module_name: 'bus_if',
      inputs: [{ name: 'clk', width: 1 }, { name: 'write_data', width: 32 }],
      outputs: [{ name: 'q', width: 1 }],
      inouts: [{ name: 'io0', width: 1 }, { name: 'bidir_bus', width: 8 }],
    } as Schematic
    const { container } = render(<SchematicView schematic={s} synthesis={{ available: false }} />)
    const labels = [...container.querySelectorAll('text.sch-port')].map((t) => t.textContent)
    expect(labels).toEqual(expect.arrayContaining(['clk', 'write_data[31:0]', 'io0 *', 'bidir_bus[7:0] *', 'q']))
    const longest = [...container.querySelectorAll('text.sch-port')].find((t) => t.textContent === 'write_data[31:0]')!
    expect(Number(longest.getAttribute('x'))).toBeGreaterThanOrEqual('write_data[31:0]'.length * 7)
  })
})
