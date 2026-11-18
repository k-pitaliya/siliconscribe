import type { ModelsResponse, RTLDesignSpec, RunResponse, SimulationRerun, StreamEvent, ProjectSummary, UVMExportResponse } from './types'
export type { ProjectSummary, UVMExportResponse } from './types'

// In dev, Vite proxies /api -> :8000. Override with VITE_API_BASE if needed.
const BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

export interface RunParams {
  prompt: string
  target_frequency_mhz?: number
  self_correct?: boolean
  max_iterations?: number
  timeout_seconds?: number
  model?: string
  /** A different model to write the testbench (independent verification). */
  testbench_model?: string
  /** A specification the user reviewed and confirmed; skips the parsing step. */
  spec?: RTLDesignSpec
  reasoning_effort?: string
}

export async function getStatus(): Promise<{ provider: string; offline: boolean; simulator_available: boolean }> {
  // On Vercel, `/` is frontend HTML, not API. Use /api/models as status proxy (has offline + provider).
  // Try /api/models first (proxied to Render), fallback to / for local dev.
  try {
    const r = await fetch(`${BASE}/api/models`)
    if (r.ok) {
      const m = (await r.json()) as ModelsResponse
      return { provider: m.current || (m.offline ? 'offline' : 'zen'), offline: m.offline, simulator_available: true }
    }
  } catch {
    /* fall through */
  }
  const r = await fetch(`${BASE}/`)
  if (!r.ok) throw new Error(`status failed: ${r.status}`)
  return r.json()
}

export async function getModels(opts: { includePaid?: boolean; refresh?: boolean } = {}): Promise<ModelsResponse> {
  // Only non-default options go in the query, so the default request stays a plain /api/models.
  const q = new URLSearchParams()
  if (opts.includePaid) q.set('include_paid', 'true')
  if (opts.refresh) q.set('refresh', 'true')
  const r = await fetch(`${BASE}/api/models${q.size ? `?${q}` : ''}`)
  if (!r.ok) throw new Error(`models failed: ${r.status} ${await r.text().catch(() => '')}`.trim())
  return r.json()
}

/** Parse a prompt into a specification only, so it can be reviewed before anything is generated. */
export async function parseSpec(prompt: string, model?: string, reasoning_effort?: string): Promise<RTLDesignSpec> {
  const r = await fetch(`${BASE}/api/spec/parse`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, model, reasoning_effort }),
  })
  if (!r.ok) {
    let detail = ''
    try { detail = ((await r.json()) as { detail?: unknown }).detail as string } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : `specification failed: ${r.status}`)
  }
  return r.json()
}

export async function runDesign(params: RunParams): Promise<RunResponse> {
  const r = await fetch(`${BASE}/api/design/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!r.ok) throw new Error(`run failed: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function reSimulate(
  design_id: string,
  rtl_code: string,
  testbench_code: string,
): Promise<SimulationRerun> {
  const r = await fetch(`${BASE}/api/simulation/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ design_id, rtl_code, testbench_code, timeout_seconds: 30 }),
  })
  if (!r.ok) throw new Error(`simulate failed: ${r.status} ${await r.text()}`)
  return r.json()
}

/**
 * Stream the agentic pipeline over SSE (fetch + ReadableStream so we can POST a
 * JSON body, which EventSource cannot do). Calls onEvent for each stage.
 */
export async function listProjects(limit = 20, offset = 0): Promise<{ total: number; projects: ProjectSummary[] }> {
  const r = await fetch(`${BASE}/api/projects?limit=${limit}&offset=${offset}`)
  if (!r.ok) throw new Error(`list projects failed: ${r.status}`)
  return r.json()
}

export async function getProject(design_id: string): Promise<RunResponse> {
  const r = await fetch(`${BASE}/api/projects/${encodeURIComponent(design_id)}`)
  if (!r.ok) throw new Error(`get project failed: ${r.status}`)
  return r.json()
}

export async function deleteProject(design_id: string): Promise<void> {
  const r = await fetch(`${BASE}/api/projects/${encodeURIComponent(design_id)}`, { method: 'DELETE' })
  if (!r.ok && r.status !== 204) throw new Error(`delete failed: ${r.status}`)
}

export async function exportUVM(prompt: string, module_name?: string, model?: string, reasoning_effort?: string): Promise<UVMExportResponse> {
  const r = await fetch(`${BASE}/api/uvm/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, module_name: module_name || undefined, model, reasoning_effort }),
  })
  if (!r.ok) throw new Error(`uvm export failed: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function streamDesign(
  params: RunParams,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${BASE}/api/design/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const body = await resp.text().catch(() => '')
    // Render free spin-down: first request after 15m idle takes 30-50s, Vercel Hobby timeout 10s → 504
    // Status only: matching text in the body also matched the field name `timeout_seconds` in a 422.
    if (resp.status === 504 || resp.status === 502) {
      throw new Error(`Render is waking up (free tier sleeps after 15m). Please wait 30s and retry. (504)`)
    }
    // Surface backend detail if the body is JSON. Parse first, then throw
    // OUTSIDE the try — otherwise the throw is caught by our own catch.
    let detail = ''
    try {
      const j = JSON.parse(body)
      if (j && typeof j.detail === 'string') detail = j.detail
    } catch {
      /* body is not JSON */
    }
    if (detail) throw new Error(detail)
    throw new Error(`stream failed: ${resp.status} ${body.slice(0, 200)}`.trim())
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let sawFinal = false

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line.
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      let event: StreamEvent
      try {
        event = JSON.parse(line.slice(5).trim()) as StreamEvent
      } catch {
        continue // malformed frame: ignore it
      }
      if (event.stage === 'done' || event.stage === 'error') sawFinal = true
      // Outside the try, so an exception in the consumer is not swallowed as a "bad frame".
      onEvent(event)
    }
  }
  if (!sawFinal && !signal?.aborted) {
    throw new Error('The connection closed before the run finished. Please try again.')
  }
}
