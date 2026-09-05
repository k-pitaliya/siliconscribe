import type { ModelsResponse, RunResponse, SimulationResult, StreamEvent, ProjectSummary, UVMExportResponse } from './types'
export type { ProjectSummary, UVMExportResponse } from './types'

// In dev, Vite proxies /api -> :8000. Override with VITE_API_BASE if needed.
const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface RunParams {
  prompt: string
  target_frequency_mhz?: number
  self_correct?: boolean
  max_iterations?: number
  timeout_seconds?: number
  model?: string
}

export async function getStatus(): Promise<{ provider: string; offline: boolean; simulator_available: boolean }> {
  const r = await fetch(`${BASE}/`)
  return r.json()
}

export async function getModels(): Promise<ModelsResponse> {
  const r = await fetch(`${BASE}/api/models`)
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
): Promise<SimulationResult> {
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
  const r = await fetch(`${BASE}/api/projects/${design_id}`)
  if (!r.ok) throw new Error(`get project failed: ${r.status}`)
  return r.json()
}

export async function deleteProject(design_id: string): Promise<void> {
  const r = await fetch(`${BASE}/api/projects/${design_id}`, { method: 'DELETE' })
  if (!r.ok && r.status !== 204) throw new Error(`delete failed: ${r.status}`)
}

export async function exportUVM(prompt: string, module_name?: string, model?: string): Promise<UVMExportResponse> {
  const r = await fetch(`${BASE}/api/uvm/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, module_name: module_name || undefined, model }),
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
  if (!resp.ok || !resp.body) throw new Error(`stream failed: ${resp.status}`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

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
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as StreamEvent)
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}
