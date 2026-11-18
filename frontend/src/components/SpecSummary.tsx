import type { RTLDesignSpec } from '../types'

interface Props {
  spec: RTLDesignSpec
}

export default function SpecSummary({ spec }: Props) {
  // Older saved projects and partial responses can lack fields; a missing list must never blank the results page.
  const ports = spec.ports ?? []
  const constraints = spec.constraints ?? []
  return (
    <details className="spec-summary" data-testid="spec-summary">
      <summary>Specification the design was built from</summary>
      <div>Module <span className="mono">{spec.module_name}</span></div>
      <table aria-label="Ports">
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Direction</th>
            <th scope="col">Width</th>
          </tr>
        </thead>
        <tbody>
          {ports.map((p, i) => (
            <tr key={`${i}-${p.name}`}>
              <td className="mono">{p.name}</td>
              <td>{p.direction}</td>
              <td>{p.width}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>{spec.behavior ?? ''}</p>
      {constraints.length > 0 && (
        <ul>
          {constraints.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </details>
  )
}
