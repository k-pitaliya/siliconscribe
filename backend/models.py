import re

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict

# Shared design_id pattern for path-traversal hardening
DESIGN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


class PortSpec(BaseModel):
    name: str = Field(..., description="Port name")
    direction: Literal["input", "output", "inout"] = Field(..., description="Port direction")
    width: int = Field(1, ge=1, le=1024, description="Bit width of the port")
    description: str = Field("", description="Brief description of the port")

    @field_validator("width", mode="before")
    @classmethod
    def coerce_width(cls, v):
        """Accept ints, numeric strings and the width spellings models actually use.

        Review finding: "[7:0]", "7:0", "8 bits" and 8.0 were all silently turned into 1,
        which then fed RTL generation, testbench generation and the weak-evidence floor.
        A genuine parameter name such as "WIDTH" still defaults to 1 (the testbench
        instantiates the module with its default parameter).
        """
        import re
        if isinstance(v, bool):
            return 1
        if isinstance(v, int):
            return v
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return int(s)
            m = re.fullmatch(r"\[?\s*(\d+)\s*:\s*(\d+)\s*\]?", s)        # [7:0] / 7:0
            if m:
                return abs(int(m.group(1)) - int(m.group(2))) + 1
            m = re.fullmatch(r"(\d+)\s*-?\s*bits?", s, re.IGNORECASE)         # "8 bits" / "8-bit"
            if m:
                return int(m.group(1))
            m = re.fullmatch(r"(\d+)\.0+", s)                                 # "8.0"
            if m:
                return int(m.group(1))
            return 1
        return 1


class ParameterSpec(BaseModel):
    name: str
    type: str = Field("integer", description="Parameter type")
    default: int | str = Field(..., description="Default value")


class RTLDesignSpec(BaseModel):
    module_name: str = Field(..., description="Name of the Verilog module")
    parameters: List[ParameterSpec] = Field(default_factory=list)
    ports: List[PortSpec] = Field(..., description="List of ports")
    behavior: str = Field(..., description="Behavioral description of the module")
    constraints: List[str] = Field(default_factory=list, description="Design constraints")


class GenerateRequest(BaseModel):
    prompt: str = Field(..., max_length=2000, description="Natural language design prompt")
    include_testbench: bool = Field(True, description="Generate testbench along with RTL")
    target_frequency_mhz: Optional[int] = Field(None, ge=1, le=10000, description="Target clock frequency hint")
    model: Optional[str] = Field(None, max_length=100, description="Override LLM model for this request")
    reasoning_effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = Field(
        None, description="Thinking level / reasoning effort for the model (actual, not display). Only for models that support it."
    )


class GenerateResponse(BaseModel):
    design_id: str
    rtl_spec: RTLDesignSpec
    rtl_code: str
    testbench_code: Optional[str] = None
    explanation: str


class SimError(BaseModel):
    """A single compile or runtime error parsed from tool output."""
    file: str = ""
    line: Optional[int] = None
    message: str = ""


class CheckResult(BaseModel):
    """One comparison made by the testbench (one `CHK|...` transcript line)."""
    idx: int
    status: Literal["PASS", "FAIL"]
    category: str = "other"
    name: str = ""
    t: Optional[int] = None            # simulation time in the VCD tick unit
    expected: Optional[str] = None     # hex text as printed by %0h (may contain x / z)
    actual: Optional[str] = None
    detail: str = ""
    source: Literal["chk", "legacy_fail"] = "chk"


class CheckGroup(BaseModel):
    """Exact counters for one category (never truncated, unlike the row list)."""
    category: str
    total: int
    passed: int
    failed: int


class UntoggledSignal(BaseModel):
    """A design signal with bits that never switched in one or both directions."""
    signal: str
    width: int
    never_rose: List[int] = Field(default_factory=list)   # bit positions that never went 0 -> 1
    never_fell: List[int] = Field(default_factory=list)   # bit positions that never went 1 -> 0


class ToggleCoverage(BaseModel):
    """Toggle coverage MEASURED from the simulator's VCD (not reported by the testbench).

    A bit is covered when it was seen going 0 -> 1 and 1 -> 0. Only signals inside the design
    under test count; testbench variables, parameters and loop integers do not.
    """
    percent: float = 0.0
    bits_total: int = 0
    bits_toggled: int = 0
    signals: int = 0
    untoggled: List[UntoggledSignal] = Field(default_factory=list)   # capped list, worst first
    untoggled_more: int = 0                                          # signals not listed
    partial: bool = False                                            # the VCD was cut at the size cap


class SimulationResult(BaseModel):
    status: Literal["PASS", "FAIL", "TIMEOUT", "ERROR"]
    module_name: str
    simulation_time_ns: float = 0
    test_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    coverage: dict = Field(default_factory=dict)
    errors: List[SimError] = Field(default_factory=list)
    waveform_file: Optional[str] = None
    transcript_file: Optional[str] = None
    log_excerpt: str = ""
    # Per-check detail parsed from the transcript (see checks.py). The verdict above is
    # never taken from these rows; they exist so the UI can show WHAT was tested.
    checks: List[CheckResult] = Field(default_factory=list)
    check_groups: List[CheckGroup] = Field(default_factory=list)
    checks_source: Literal["structured", "legacy", "none"] = "none"
    checks_total_logged: int = 0
    checks_truncated: bool = False
    checks_consistent: bool = True
    # Measured from the VCD the simulator wrote (see vcd_parser.toggle_coverage); None when unavailable.
    measured_toggle: Optional[ToggleCoverage] = None


class SimulationRequest(BaseModel):
    design_id: str = Field(..., max_length=32, pattern=r"^[a-zA-Z0-9_-]{1,32}$", description="Design identifier")
    rtl_code: str = Field(..., max_length=50000, description="RTL code")
    testbench_code: str = Field(..., max_length=50000, description="Testbench code")
    timeout_seconds: int = Field(60, ge=1, le=120, description="Simulation timeout")

    @field_validator("design_id")
    @classmethod
    def validate_design_id(cls, v: str) -> str:
        if not DESIGN_ID_RE.match(v):
            raise ValueError("design_id must match ^[a-zA-Z0-9_-]{1,32}$")
        # Redundant extra guard: disallow path separators even if regex changes
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("design_id contains illegal path characters")
        return v


class IterationRecord(BaseModel):
    """One pass of the self-correction loop."""
    iteration: int
    status: str
    fix_summary: str = ""
    fix_type: str = ""
    diagnosis: Optional[dict] = Field(
        None,
        description="Structured root-cause diagnosis from the debugger "
                    "(symptom, root_cause, fix_location, confidence). "
                    "None for scripted offline fixes."
    )
    pass_count: int = 0
    fail_count: int = 0
    log_excerpt: str = ""


class WaveformSignal(BaseModel):
    name: str
    width: int = 1
    wave: List[dict] = Field(default_factory=list, description="List of {t, v} value changes")
    # Context the viewer needs to group and order signals sensibly (see vcd_parser.py).
    path: str = ""                      # hierarchical path, e.g. "testbench.count"
    scope: str = ""                     # enclosing scope name
    var_type: str = "wire"              # wire / reg / integer / parameter / real ...
    role: str = "internal"              # clock | reset | in | out | io | dut_internal | internal | tb | aux | param
    msb: Optional[int] = None
    lsb: Optional[int] = None
    truncated_at: Optional[int] = None  # time of the last stored change if this signal's changes were capped


class Waveform(BaseModel):
    timescale: str = "1ns"
    timescale_ps: Optional[float] = None      # one time unit in picoseconds
    timescale_defaulted: bool = False         # True when the simulator fell back to its 1 s default
    end_time: int = 0
    signals: List[WaveformSignal] = Field(default_factory=list)
    truncated: bool = False
    dropped_signals: int = 0
    changes_truncated: bool = False


class SimulationRerunResponse(SimulationResult):
    """Result of re-simulating edited code: the verdict AND the matching waveform.

    Without the waveform the Waveform tab kept showing the PRE-edit run next to the new
    PASS/FAIL (review finding).
    """
    waveform: Optional[Waveform] = None


class SchematicPort(BaseModel):
    name: str
    direction: str
    width: int = 1


class Schematic(BaseModel):
    module_name: str
    inputs: List[SchematicPort] = Field(default_factory=list)
    outputs: List[SchematicPort] = Field(default_factory=list)
    inouts: List[SchematicPort] = Field(default_factory=list)


class RunRequest(BaseModel):
    """One-shot: natural language -> generate -> simulate -> self-correct."""
    prompt: str = Field(..., max_length=2000, description="Natural language design prompt")
    target_frequency_mhz: Optional[int] = Field(None, ge=1, le=10000, description="Target clock frequency hint")
    self_correct: bool = Field(True, description="Enable auto-fix loop")
    max_iterations: int = Field(5, ge=0, le=10, description="Max self-correction iterations")
    timeout_seconds: int = Field(30, ge=1, le=120, description="Per-simulation timeout")
    model: Optional[str] = Field(None, max_length=100, description="Override LLM model for this run")
    reasoning_effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = Field(
        None, description="Thinking level / reasoning effort (actual, model-specific). Only for models with variants."
    )


class MutantInfo(BaseModel):
    """One injected bug the testbench did NOT notice."""
    description: str
    line: int


class StrengthReport(BaseModel):
    """How many injected bugs the design's own testbench caught (mutation testing)."""
    status: str = "skipped"            # "ok" | "partial" (time budget hit) | "skipped"
    total: int = 0                      # mutants that compiled and were run
    killed: int = 0                     # of those, how many the testbench caught
    invalid: int = 0                    # injected changes that did not compile (not counted)
    survivors: List[MutantInfo] = Field(default_factory=list)
    note: str = ""
    seconds: float = 0.0


class TimingReport(BaseModel):
    """Pre-layout timing and mapped area (Yosys + OpenSTA on the sky130 library). See timing.py."""
    available: bool = False
    library: str = ""
    clock: Optional[str] = None
    target_mhz: float = 100.0
    period_ns: float = 10.0
    slack_ns: Optional[float] = None          # worst setup slack; negative = too slow for the target
    met: Optional[bool] = None
    fmax_mhz: Optional[float] = None
    critical_start: Optional[str] = None
    critical_end: Optional[str] = None
    critical_delay_ns: Optional[float] = None
    area_um2: Optional[float] = None
    sequential_area_um2: Optional[float] = None
    cell_count: Optional[int] = None
    flip_flops: Optional[int] = None
    cells: List[list] = Field(default_factory=list)      # [[cell name, count], ...] most common first
    note: str = ""
    error: Optional[str] = None
    seconds: float = 0.0


class TimingRequest(BaseModel):
    """Request body for POST /api/timing/run."""
    rtl_code: str = Field(..., max_length=100000)
    module_name: str = Field(..., max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    target_frequency_mhz: Optional[int] = Field(None, ge=1, le=10000)
    testbench_code: Optional[str] = Field(None, max_length=100000)   # only read for #(.PARAM(n)) overrides


class RunResponse(BaseModel):
    design_id: str
    rtl_spec: RTLDesignSpec
    rtl_code: str
    testbench_code: str
    explanation: str
    status: str
    result: Optional[SimulationResult] = None
    iterations: int = 0
    iteration_history: List[IterationRecord] = Field(default_factory=list)
    waveform: Optional[Waveform] = None
    schematic: Optional[Schematic] = None
    synthesis: Optional[dict] = None
    fallback_notice: Optional[str] = None
    verification_warning: Optional[str] = None
    strength: Optional[StrengthReport] = None
    timing: Optional[TimingReport] = None


class SynthesisRequest(BaseModel):
    """Request body for POST /api/synthesis/run."""
    rtl_code: str = Field(..., max_length=100000, description="RTL Verilog/SystemVerilog code")
    module_name: str = Field(..., max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", description="Top module name")

    @field_validator("module_name")
    @classmethod
    def validate_module_name(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", v):
            raise ValueError("module_name must be a valid Verilog identifier")
        return v


class UVMExportRequest(BaseModel):
    """Request body for POST /api/uvm/export (export-only, commercial sim style).

    The endpoint is export-only and never touches the Icarus path.
    `prompt` is the natural-language design intent (max 2000 chars, same limit
    as GenerateRequest/RunRequest). `module_name` optionally overrides the
    inferred/spec module name (e.g., UI provides a sanitize slot).
    """
    prompt: str = Field(..., max_length=2000, description="Natural language design prompt for UVM export")
    module_name: Optional[str] = Field(
        None,
        max_length=64,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Optional override for DUT module name (valid Verilog identifier)",
    )
    target_frequency_mhz: Optional[int] = Field(None, ge=1, le=10000, description="Optional clock hint, unused for UVM but kept for parity")
    model: Optional[str] = Field(None, max_length=100, description="Optional LLM model override")
    reasoning_effort: Optional[Literal["low", "medium", "high", "xhigh", "max"]] = Field(
        None, description="Thinking level / reasoning effort (actual, model-specific)."
    )

    @field_validator("module_name")
    @classmethod
    def validate_module_override(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", v):
            raise ValueError("module_name must be a valid Verilog identifier")
        return v


class UVMExportResponse(BaseModel):
    """Response for POST /api/uvm/export.

    `files` maps filename -> content (SystemVerilog / Makefile / filelist.f / README).
    `zip_base64` is an optional in-memory zip (base64) for one-click download;
    callers that only need the file map may ignore it.
    """
    module_name: str = Field(..., description="DUT module name used for generation")
    files: Dict[str, str] = Field(..., description="Filename -> file content mapping")
    file_count: int = Field(..., description="Number of files in bundle")
    is_sequential: bool = Field(..., description="True if spec constraints indicate sequential logic")
    zip_base64: Optional[str] = Field(None, description="Base64-encoded zip of the bundle (optional)")
    note: str = Field(
        "Questa/ModelSim style (logic/always_ff, UVM 1.2). Export-only, not simulated via Icarus iVerilog.",
        description="Human-readable note about simulator compatibility",
    )
