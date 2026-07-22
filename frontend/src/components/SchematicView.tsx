import type { Schematic, SchematicPort } from '../types'

export default function SchematicView({ schematic }: { schematic: Schematic | null }) {
  if (!schematic) return <div className="empty-state">No schematic yet. Generate a design first.</div>

  const inputs = schematic.inputs
  const outputs = schematic.outputs
  const rows = Math.max(inputs.length, outputs.length, 1)

  const ROW = 34
  const PAD = 30
  const BOX_W = 220
  const BOX_X = 200
  const height = PAD * 2 + rows * ROW
  const boxH = rows * ROW
  const width = 640

  const portLabel = (p: SchematicPort) => `${p.name}${p.width > 1 ? `[${p.width - 1}:0]` : ''}`

  return (
    <div className="schematic-view">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" preserveAspectRatio="xMidYMin meet">
        {/* module box */}
        <rect x={BOX_X} y={PAD} width={BOX_W} height={boxH} rx={10} className="sch-box" />
        <text x={BOX_X + BOX_W / 2} y={PAD + boxH / 2} className="sch-module" textAnchor="middle">
          {schematic.module_name}
        </text>

        {/* inputs on the left */}
        {inputs.map((p, i) => {
          const y = PAD + i * ROW + ROW / 2
          return (
            <g key={`in-${p.name}`}>
              <line x1={60} y1={y} x2={BOX_X} y2={y} className="sch-wire" />
              <circle cx={60} cy={y} r={4} className="sch-pin in" />
              <text x={54} y={y + 4} className="sch-port" textAnchor="end">
                {portLabel(p)}
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
      <div className="schematic-note">
        Port-level block diagram. Gate-level synthesis view (yosys) is future work.
      </div>
    </div>
  )
}
