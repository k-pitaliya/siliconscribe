import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { ModelInfo, ProviderInfo } from '../types'

type Family = 'opencode' | 'cloudflare'

const CLOUDFLARE_DEFAULT_HINT =
  'Cloudflare is not set up. Start the backend with CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN set.'

function familyOf(m: ModelInfo): Family {
  if (m.provider === 'cloudflare' || m.id.startsWith('@cf/') || m.id.startsWith('@hf/')) return 'cloudflare'
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

  const cloudflareProvider = providers.find((p) => p.id === 'cloudflare')
  const cloudflareOffline = view === 'cloudflare' && (!cloudflareProvider || !cloudflareProvider.available)
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
        <button
          type="button"
          role="radio"
          aria-checked={view === 'opencode'}
          className={view === 'opencode' ? 'seg-btn on' : 'seg-btn'}
          disabled={disabled}
          onClick={() => switchView('opencode')}
        >
          OpenCode
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={view === 'cloudflare'}
          className={view === 'cloudflare' ? 'seg-btn on' : 'seg-btn'}
          disabled={disabled}
          onClick={() => switchView('cloudflare')}
        >
          Cloudflare
        </button>
      </div>

      <label className="field-label" htmlFor="model-select" id="model-select-label">Model</label>

      {cloudflareOffline ? (
        <div className="model-offline" role="status">
          {cloudflareProvider?.hint || CLOUDFLARE_DEFAULT_HINT}
        </div>
      ) : visible.length === 0 ? (
        <div className="model-offline" role="status">No models available.</div>
      ) : (
        <>
          <select
            id="model-select"
            value={selected && selectedFamily === view ? selectedModel : ''}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={disabled}
          >
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
          {view === 'cloudflare' && cloudflareProvider?.hint && <div className="model-note" role="status">{cloudflareProvider.hint}</div>}
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
    </div>
  )
}
