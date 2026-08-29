import re

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict

# Shared design_id pattern for path-traversal hardening
DESIGN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


class PortSpec(BaseModel):
    name: str = Field(..., description="Port name")
    direction: Literal["input", "output", "inout"] = Field(..., description="Port direction")
    width: int = Field(1, description="Bit width of the port")
    description: str = Field("", description="Brief description of the port")

    @field_validator("width", mode="before")
    @classmethod
    def coerce_width(cls, v):
        """Accept numeric strings, parameter names (WIDTH), or plain ints."""
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.isdigit():
                return int(v)
            # Parameterized width like "WIDTH" — default to 1 (the TB will
            # instantiate with the module's default parameter).
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
    pass_count: int = 0
    fail_count: int = 0
    log_excerpt: str = ""


class WaveformSignal(BaseModel):
    name: str
    width: int = 1
    wave: List[dict] = Field(default_factory=list, description="List of {t, v} value changes")


class Waveform(BaseModel):
    timescale: str = "1ns"
    end_time: int = 0
    signals: List[WaveformSignal] = Field(default_factory=list)
    truncated: bool = False
    dropped_signals: int = 0
    changes_truncated: bool = False


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
