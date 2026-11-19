import { useEffect, useState } from 'react'
import { Minus, Plus, Maximize2, Download } from 'lucide-react'
import type { Schematic, SchematicPort, SynthesisInfo, YosysNetlist } from '../types'

function BlockDiagram({ schematic }: { schematic: Schematic }) {

  const inputs = schematic.inputs
  const outputs = schematic.outputs
  const inouts = schematic.inouts ?? []
  // Include inouts stacked below inputs so total left-side ports fit; avoid overflow clipping
  const leftRows = inputs.length + inouts.length
  const rows = Math.max(leftRows, outputs.length, inouts.length, 1)

  const ROW = 34
  const PAD = 30
  const BOX_W = 220
  const portLabel = (p: SchematicPort) => `${p.name}${p.width > 1 ? `[${p.width - 1}:0]` : ''}`
  // Room for the longest left-hand label (self-review finding: `write_data[31:0]` was clipped to `a[31:0]`).
  const leftChars = Math.max(0, ...[...inputs, ...inouts].map((p) => portLabel(p).length + 2))
  const rightChars = Math.max(0, ...outputs.map((p) => portLabel(p).length))
  const PIN_X = Math.max(60, Math.ceil(leftChars * 7.6) + 14)
  const BOX_X = PIN_X + 140
  const height = PAD * 2 + rows * ROW
  const boxH = rows * ROW
  const width = Math.max(640, BOX_X + BOX_W + 66 + Math.ceil(rightChars * 7.6) + 14)

  return (
    <div className="schematic-view">
      <div className="schematic-scroll" style={{ overflowX: 'auto', overflowY: 'hidden' }}>
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          preserveAspectRatio="xMidYMin meet"
          style={{ display: 'block', minWidth: width, maxWidth: '100%' }}
          role="img"
          aria-label={`Schematic for module ${schematic.module_name}`}
        >
          {/* module box */}
          <rect x={BOX_X} y={PAD} width={BOX_W} height={boxH} rx={10} className="sch-box" />
          <text x={BOX_X + BOX_W / 2} y={PAD + boxH / 2} className="sch-module" textAnchor="middle" dominantBaseline="middle">
            {schematic.module_name}
          </text>

          {/* inputs on the left */}
          {inputs.map((p, i) => {
            const y = PAD + i * ROW + ROW / 2
            return (
              <g key={`in-${p.name}`}>
                <line x1={PIN_X} y1={y} x2={BOX_X} y2={y} className="sch-wire" />
                <circle cx={PIN_X} cy={y} r={4} className="sch-pin in" />
                <text x={PIN_X - 6} y={y + 4} className="sch-port" textAnchor="end">
                  {portLabel(p)}
                </text>
              </g>
            )
          })}

          {/* inouts in middle left (draw as bidirectional) */}
          {inouts.map((p, i) => {
            // Below the inputs, one row each; `rows` already counts them, so none is ever skipped (self-review finding:
            // the last inout was always dropped).
            const yy = PAD + (inputs.length + i) * ROW + ROW / 2
            return (
              <g key={`io-${p.name}`}>
                <line x1={PIN_X} y1={yy} x2={BOX_X} y2={yy} className="sch-wire" strokeDasharray="4 2" />
                <circle cx={PIN_X} cy={yy} r={4} className="sch-pin in" fill="var(--warn-amber)" />
                <text x={PIN_X - 6} y={yy + 4} className="sch-port" textAnchor="end">
                  {portLabel(p)} *
                </text>
              </g>
            )
          })}

          {/* outputs on the right */}
          {outputs.map((p, i) => {
            const y = PAD + i * ROW + ROW / 2
            return (
              <g key={`out-${p.name}`}>
                <line x1={BOX_X + BOX_W} y1={y} x2={BOX_X + BOX_W + 60} y2={y} className="sch-wire" />
                <circle cx={BOX_X + BOX_W + 60} cy={y} r={4} className="sch-pin out" />
                <text x={BOX_X + BOX_W + 66} y={y + 4} className="sch-port" textAnchor="start">
                  {portLabel(p)}
                </text>
              </g>
            )
          })}
        </svg>
      </div>
    </div>
  )
}

type View = 'block' | 'rtl' | 'gate'

/** Above this the drawing turns into a tangle of wires that helps nobody; say so instead of drawing it. */
export const MAX_DRAWN_CELLS = 400

const VIEWS: [View, string][] = [['block', 'Block diagram'], ['rtl', 'RTL cells'], ['gate', 'Gate level']]

const NOTES: Record<View, string> = {
  block: 'Ports of the module, from the specification.',
  rtl: 'Word-level cells after Yosys proc and opt: adders, multiplexers, comparators, flip-flops.',
  gate: 'Single-bit generic gates and flip-flops after Yosys synth (generic cells, not sky130 standard cells).',
}

function cellCount(n: YosysNetlist | undefined): number {
  const m = n ? Object.values(n.modules)[0] : undefined
  return m ? Object.keys(m.cells ?? {}).length : 0
}

type Drawn = { status: 'idle' } | { status: 'loading' } | { status: 'ready'; url: string } | { status: 'error'; message: string }

export default function SchematicView({ schematic, synthesis }: { schematic: Schematic | null; synthesis?: SynthesisInfo | null }) {
  const [view, setView] = useState<View>('block')
  const [zoom, setZoom] = useState(1)
  const [natural, setNatural] = useState(0)
  const [drawn, setDrawn] = useState<Drawn>({ status: 'idle' })

  const available: Record<View, boolean> = { block: !!schematic, rtl: !!synthesis?.rtl_netlist, gate: !!synthesis?.json_netlist }
  // A new run or a loaded project can remove the selected view's data: fall back to a view that exists.
  useEffect(() => {
    if (!available[view]) {
      const next = VIEWS.map(([v]) => v).find((v) => available[v])
      if (next) setView(next)
    }
  }, [view, available.block, available.rtl, available.gate])   // eslint-disable-line react-hooks/exhaustive-deps

  const netlist = view === 'rtl' ? synthesis?.rtl_netlist : view === 'gate' ? synthesis?.json_netlist : undefined
  const cells = cellCount(netlist)
  const tooLarge = cells > MAX_DRAWN_CELLS

  useEffect(() => {
    setZoom(1)
    setNatural(0)
    if (view === 'block' || !netlist || tooLarge) { setDrawn({ status: 'idle' }); return }
    let cancelled = false
    let url = ''
    setDrawn({ status: 'loading' })
    import('../netlistRender')
      .then(({ renderNetlist }) => renderNetlist(netlist))
      .then((svg) => {
        if (cancelled) return
        // Shown through <img>: an SVG image cannot run script, whatever names the design's signals carry.
        url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
        setDrawn({ status: 'ready', url })
      })
      .catch((e: unknown) => { if (!cancelled) setDrawn({ status: 'error', message: e instanceof Error ? e.message : String(e) }) })
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url) }
  }, [view, netlist, tooLarge])

  if (!schematic && !synthesis?.json_netlist) return <div className="empty-state">No schematic yet. Generate a design first.</div>

  const moduleName = schematic?.module_name ?? (netlist ? Object.keys(netlist.modules)[0] : 'design')
  const label = VIEWS.find(([v]) => v === view)?.[1] ?? ''
  const noNetlistHint = synthesis?.available === false
    ? 'Needs Yosys, which is not installed on the server.'
    : synthesis?.error
      ? `Synthesis failed: ${synthesis.error}`
      : 'No netlist for this run yet.'

  return (
    <div className="schematic-view">
      <div className="sch-toolbar">
        <div className="seg sch-views" role="group" aria-label="Schematic view">
          {VIEWS.map(([v, text]) => {
            return (
              <button key={v} type="button" className={view === v ? 'seg-btn on' : 'seg-btn'} aria-pressed={view === v}
                disabled={!available[v]} title={available[v] ? undefined : (v === 'block' ? 'No specification yet' : noNetlistHint)}
                onClick={() => setView(v)}>
                {text}
              </button>
            )
          })}
        </div>
        {view !== 'block' && drawn.status === 'ready' && (
          <div className="sch-zoom">
            <button type="button" className="icon-btn" aria-label="Zoom out" title="Zoom out" onClick={() => setZoom((z) => Math.max(0.5, +(z / 1.25).toFixed(2)))}><Minus size={14} aria-hidden="true" /></button>
            <button type="button" className="icon-btn" aria-label="Fit to panel" title="Fit to panel" onClick={() => setZoom(1)}><Maximize2 size={14} aria-hidden="true" /></button>
            <button type="button" className="icon-btn" aria-label="Zoom in" title="Zoom in" onClick={() => setZoom((z) => Math.min(6, +(z * 1.25).toFixed(2)))}><Plus size={14} aria-hidden="true" /></button>
            <a className="icon-btn" href={drawn.url} download={`${moduleName}_${view}_schematic.svg`} aria-label="Download SVG" title="Download SVG"><Download size={14} aria-hidden="true" /></a>
          </div>
        )}
      </div>

      {view === 'block' && schematic && <BlockDiagram schematic={schematic} />}

      {view !== 'block' && (
        tooLarge ? (
          <div className="sch-message" role="status">
            {cells} cells is too many to draw as a readable schematic (limit {MAX_DRAWN_CELLS}).
            {view === 'gate' && synthesis?.rtl_netlist ? ' The RTL cells view shows the same design in far fewer, larger blocks.' : ''}
          </div>
        ) : drawn.status === 'loading' ? (
          <div className="sch-message" role="status">Laying out {cells} cells...</div>
        ) : drawn.status === 'error' ? (
          <div className="sch-message warn" role="status">Could not draw this netlist: {drawn.message}</div>
        ) : drawn.status === 'ready' ? (
          <div className="netlist-canvas" tabIndex={0} role="region" aria-label={`${label} schematic, scrollable`}>
            {/* 1.6x the drawing's own size reads well; at zoom 1 it never exceeds the panel, zooming in can. */}
            <img src={drawn.url} alt={`${label} schematic of ${moduleName}: ${cells} cells`}
              onLoad={(e) => setNatural(e.currentTarget.naturalWidth)}
              style={natural ? { width: natural * 1.6 * zoom, maxWidth: zoom <= 1 ? '100%' : 'none' } : { maxWidth: '100%' }} />
          </div>
        ) : null
      )}

      <div className="schematic-note">
        {NOTES[view]}
        {view !== 'block' && netlist ? ` ${cells} cells. Drawn with netlistsvg from the Yosys netlist of this run.` : ''}
      </div>
    </div>
  )
}
