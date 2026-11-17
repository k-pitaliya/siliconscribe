export interface ModelInfo {
  id: string
  label: string
  note: string
  tag: 'accurate' | 'balanced' | 'fast' | string
  thinking_levels?: string[]
  reasoning?: boolean
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

/** One comparison made by the testbench (parsed from a `CHK|...` transcript line). */
export interface CheckResult {
  idx: number
  status: 'PASS' | 'FAIL'
  category: string
  name: string
  t: number | null
  expected: string | null
  actual: string | null
  detail: string
  source: 'chk' | 'legacy_fail'
}

/** Exact per-category counters (never truncated, unlike the row list). */
export interface CheckGroup {
  category: string
  total: number
  passed: number
  failed: number
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
  /** Per-check detail; display data only, the verdict never comes from these rows. */
  checks?: CheckResult[]
  check_groups?: CheckGroup[]
  checks_source?: 'structured' | 'legacy' | 'none'
  checks_total_logged?: number
  checks_truncated?: boolean
  checks_consistent?: boolean
  /** Measured from the VCD; absent when no waveform was produced. */
  measured_toggle?: ToggleCoverage | null
}

/** Result of re-simulating edited code: the verdict plus the matching waveform. */
export interface SimulationRerun extends SimulationResult {
  waveform?: Waveform | null
}

export interface Diagnosis {
  symptom?: string
  root_cause?: string
  fix_location?: string
  confidence?: 'high' | 'medium' | 'low' | string
}

export interface IterationRecord {
  iteration: number
  status: string
  fix_summary: string
  fix_type?: string
  diagnosis?: Diagnosis | null
  pass_count: number
  fail_count: number
  log_excerpt: string
}

export type SignalRole =
  | 'clock' | 'reset' | 'in' | 'out' | 'io' | 'dut_internal' | 'internal' | 'tb' | 'aux' | 'param'

export interface WaveformSignal {
  name: string
  width: number
  wave: { t: number; v: string }[]
  path?: string
  scope?: string
  var_type?: string
  role?: SignalRole
  msb?: number | null
  lsb?: number | null
  /** Time of the last stored change when this signal's changes were capped. */
  truncated_at?: number | null
}

export interface Waveform {
  timescale: string
  timescale_ps?: number | null
  timescale_defaulted?: boolean
  end_time: number
  signals: WaveformSignal[]
  truncated: boolean
  dropped_signals: number
  changes_truncated: boolean
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

export interface SynthesisInfo {
  available: boolean
  cell_count?: number
  /** Most common generic cell types first, e.g. ["AND", 5]. */
  cell_types?: [string, number][]
  flip_flops?: number
  latches?: number
  latch_warning?: string
  /** Yosys' own `Warning:` lines (multiple drivers, loops, ...). */
  warnings?: string[]
  area_estimate?: number | string
  error?: string
}

/** A design signal with bits that never switched in one or both directions. */
export interface UntoggledSignal {
  signal: string
  width: number
  never_rose: number[]
  never_fell: number[]
}

/** Toggle coverage measured from the simulator's VCD (design signals only). */
export interface ToggleCoverage {
  percent: number
  bits_total: number
  bits_toggled: number
  signals: number
  untoggled: UntoggledSignal[]
  untoggled_more: number
  partial: boolean
}

/** One injected bug the testbench did not notice. */
export interface MutantInfo {
  description: string
  line: number
}

/** Mutation testing of the design's own testbench: how many injected bugs it caught. */
export interface StrengthReport {
  status: 'ok' | 'partial' | 'skipped'
  total: number
  killed: number
  invalid: number
  survivors: MutantInfo[]
  note: string
  seconds: number
}

export interface LintInfo {
  ok: boolean
  errors: SimError[]
  warnings: SimError[]
  output?: string
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
  synthesis?: SynthesisInfo | null
  fallback_notice?: string | null
  verification_warning?: string | null
  strength?: StrengthReport | null
}

export interface ProjectSummary {
  design_id: string
  prompt: string
  module_name: string
  status: string
  created_at: number
  iterations: number
}

export interface UVMExportResponse {
  module_name: string
  files: Record<string, string>
  file_count: number
  is_sequential: boolean
  zip_base64: string | null
  note: string
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
    | 'lint'
    | 'synthesis'
    | 'strength'
    | 'done'
    | 'error'
  message?: string
  iteration?: number
  status?: string
  target?: string
  rtl_spec?: RTLDesignSpec
  rtl_code?: string
  testbench_code?: string
  explanation?: string
  fix_summary?: string
  fix_type?: string
  diagnosis?: Diagnosis | null
  fallback_notice?: string
  result?: SimulationResult
  response?: RunResponse
  synthesis?: SynthesisInfo
  lint?: LintInfo
  strength?: StrengthReport
}
