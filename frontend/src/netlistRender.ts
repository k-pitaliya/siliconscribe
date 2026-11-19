// Loaded on demand (dynamic import) so the layout engine stays out of the main bundle.
import { render } from 'netlistsvg'
import skin from 'netlistsvg/lib/default.svg?raw'

/** Yosys JSON netlist -> SVG text. netlistsvg logs layout errors and resolves empty, so an empty result is a failure. */
export async function renderNetlist(netlist: unknown): Promise<string> {
  const svg = await render(skin, netlist)
  if (typeof svg !== 'string' || !svg.includes('<svg')) throw new Error('The schematic could not be laid out.')
  return svg
}
