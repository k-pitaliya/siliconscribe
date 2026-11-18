import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { RefreshCw } from 'lucide-react'
import type { ModelInfo, ProviderInfo } from '../types'

type Family = 'opencode' | 'cloudflare' | 'nim'

const SOURCES: [Family, string][] = [
  ['opencode', 'OpenCode'],
  ['cloudflare', 'Cloudflare'],
  ['nim', 'NVIDIA NIM'],
]

const DEFAULT_HINT: Record<'cloudflare' | 'nim', string> = {
  cloudflare: 'Cloudflare is not set up. Start the backend with CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN set.',
  nim: 'NVIDIA NIM is not set up. Start the backend with NVIDIA_NIM_API_KEY set.',
}

function familyOf(m: ModelInfo): Family {
  if (m.provider === 'cloudflare' || m.id.startsWith('@cf/') || m.id.startsWith('@hf/')) return 'cloudflare'
  if (m.provider === 'nim' || m.id.startsWith('nim/')) return 'nim'
  return 'opencode'
}

interface Props {
  models: ModelInfo[]
  providers: ProviderInfo[]
  selectedModel: string
  onModelChange: (id: string) => void
  includePaid: boolean
  onIncludePaidChange: (v: boolean) => void
  paidHidden: number
  onRefresh: () => void
  refreshing?: boolean
  disabled?: boolean
}

export default function ModelPicker({
  models, providers, selectedModel, onModelChange, includePaid, onIncludePaidChange,
  paidHidden, onRefresh, refreshing = false, disabled = false,
}: Props) {
  const selected = models.find((m) => m.id === selectedModel)
  const selectedFamily: Family | null = selected ? familyOf(selected) : null

  const [view, setView] = useState<Family>(() => selectedFamily ?? 'opencode')

  // When the selected model changes from outside to another family, follow it.
  useEffect(() => {
    if (selectedFamily) setView(selectedFamily)
  }, [selectedFamily])

  const buttons = useRef<Partial<Record<Family, HTMLButtonElement | null>>>({})

  /** The WAI-ARIA radio pattern: one tab stop (the checked one); arrow keys, Home and End move between the sources. */
  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, family: Family) {
    const moves = ['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End']
    if (disabled || !moves.includes(e.key)) return
    e.preventDefault()
    const i = SOURCES.findIndex(([f]) => f === family)
    const n = e.key === 'Home' ? 0 : e.key === 'End' ? SOURCES.length - 1
      : e.key === 'ArrowRight' || e.key === 'ArrowDown' ? (i + 1) % SOURCES.length : (i - 1 + SOURCES.length) % SOURCES.length
    const next = SOURCES[n][0]
    switchView(next)
    buttons.current[next]?.focus()
  }

  function switchView(next: Family) {
    setView(next)
    if (selectedFamily === next) return
    const candidates = models.filter((m) => familyOf(m) === next)
    if (candidates.length === 0) return
    const pick = next === 'opencode'
      ? (candidates.find((m) => m.free === true) ?? candidates[0])
      : candidates[0]
    onModelChange(pick.id)
  }

  const viewProvider = providers.find((p) => p.id === view)
  const nonOpenCodeOffline =
    view !== 'opencode' && (!viewProvider || !viewProvider.available)
  const visible = models.filter((m) => familyOf(m) === view)

  // Distinct groups in order of first appearance.
  const groups: string[] = []
  for (const m of visible) {
    const g = m.group ?? 'Models'
    if (!groups.includes(g)) groups.push(g)
  }

  return (
    <div className="model-picker">
      <div role="radiogroup" aria-label="Model source" className="seg">
        {SOURCES.map(([family, label]) => (
          <button
            key={family}
            type="button"
            role="radio"
            aria-checked={view === family}
            tabIndex={view === family ? 0 : -1}
            ref={(el) => { buttons.current[family] = el }}
            className={view === family ? 'seg-btn on' : 'seg-btn'}
            disabled={disabled}
            onClick={() => switchView(family)}
            onKeyDown={(e) => onKeyDown(e, family)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Right after the switch in the DOM, because that is where it is on screen: Tab order follows what the eye sees. */}
      <button
        type="button"
        className="icon-btn"
        aria-label="Refresh model list"
        title="Refresh model list"
        onClick={onRefresh}
        disabled={disabled || refreshing}
      >
        <RefreshCw size={14} aria-hidden="true" className={refreshing ? 'spin' : undefined} />
      </button>

      {/* A <label> only where there is a control to label. */}
      {nonOpenCodeOffline || visible.length === 0
        ? <div className="field-label">Model</div>
        : <label className="field-label" htmlFor="model-select" id="model-select-label">Model</label>}

      {nonOpenCodeOffline ? (
        <div className="model-offline" role="status">
          {viewProvider?.hint || DEFAULT_HINT[view as 'cloudflare' | 'nim']}
        </div>
      ) : visible.length === 0 ? (
        <div className="model-offline" role="status">{viewProvider?.hint || 'No models available.'}</div>
      ) : (
        <>
          <select
            id="model-select"
            value={selected && selectedFamily === view ? selectedModel : ''}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={disabled}
          >
            {/* Without a valid selection the menu must say so, not silently show its first option while another model is in use. */}
            {!(selected && selectedFamily === view) && <option value="" disabled hidden>Choose a model</option>}
            {groups.map((g) => (
              <optgroup key={g} label={g}>
                {visible
                  .filter((m) => (m.group ?? 'Models') === g)
                  .map((m) => (
                    <option key={m.id} value={m.id} title={m.id}>
                      {`${m.label}${m.free ? ' (free)' : ''}`}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
          {selected?.note && <div className="model-note" aria-live="polite">{selected.note}</div>}
          {view !== 'opencode' && viewProvider?.hint && <div className="model-note" role="status">{viewProvider.hint}</div>}
        </>
      )}

      {view === 'opencode' && (
        <>
          <label className="check">
            <input
              type="checkbox"
              checked={includePaid}
              onChange={(e) => onIncludePaidChange(e.target.checked)}
              disabled={disabled}
            />{' '}
            Show other models{!includePaid && paidHidden > 0 ? ` (${paidHidden} hidden)` : ''}
          </label>
          {includePaid && (
            <div className="model-note">Models not marked free may use credits on your OpenCode account.</div>
          )}
        </>
      )}
    </div>
  )
}
