export interface ModelInfo {
  id: string
  label: string
  note: string
  tag: 'accurate' | 'balanced' | 'fast' | string
}

export interface ModelsResponse {
  offline: boolean
  current: string | null
  models: ModelInfo[]
}

export interface PortSpec {
  name: string
  direction: 'input' | 'output' | 'inout'
  width: number
  description: string
}

export interface RTLDesignSpec {
  module_name: string
  parameters: { name: string; type: string; default: number | string }[]
  ports: PortSpec[]
  behavior: string
  constraints: string[]
}

export interface SimError {
  file: string
  line: number | null
  message: string
}

export interface SimulationResult {
  status: 'PASS' | 'FAIL' | 'TIMEOUT' | 'ERROR'
  module_name: string
  simulation_time_ns: number
  test_count: number
  pass_count: number
  fail_count: number
  coverage: Record<string, any>
  errors: SimError[]
  waveform_file: string | null
  transcript_file: string | null
  log_excerpt: string
}

export interface IterationRecord {
  iteration: number
  status: string
  fix_summary: string
  pass_count: number
  fail_count: number
  log_excerpt: string
}

export interface WaveformSignal {
  name: string
  width: number
  wave: { t: number; v: string }[]
}

export interface Waveform {
  timescale: string
  end_time: number
  signals: WaveformSignal[]
}

export interface SchematicPort {
  name: string
  direction: string
  width: number
}

export interface Schematic {
  module_name: string
  inputs: SchematicPort[]
  outputs: SchematicPort[]
  inouts: SchematicPort[]
}

export interface RunResponse {
  design_id: string
  rtl_spec: RTLDesignSpec
  rtl_code: string
  testbench_code: string
  explanation: string
  status: string
  result: SimulationResult | null
  iterations: number
  iteration_history: IterationRecord[]
  waveform: Waveform | null
  schematic: Schematic | null
}

/** A single SSE event emitted by /api/design/stream. */
export interface StreamEvent {
  stage:
    | 'start'
    | 'intent'
    | 'rtl'
    | 'testbench'
    | 'explanation'
    | 'simulate'
    | 'fixing'
    | 'fix'
    | 'done'
    | 'error'
  message?: string
  iteration?: number
  status?: string
  rtl_spec?: RTLDesignSpec
  rtl_code?: string
  testbench_code?: string
  explanation?: string
  fix_summary?: string
  result?: SimulationResult
  response?: RunResponse
}
