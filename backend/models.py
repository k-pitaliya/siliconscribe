from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class PortSpec(BaseModel):
    name: str = Field(..., description="Port name")
    direction: Literal["input", "output", "inout"] = Field(..., description="Port direction")
    width: int = Field(1, description="Bit width of the port")
    description: str = Field("", description="Brief description of the port")


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
    prompt: str = Field(..., description="Natural language design prompt")
    include_testbench: bool = Field(True, description="Generate testbench along with RTL")
    target_frequency_mhz: Optional[int] = Field(None, description="Target clock frequency hint")
    model: Optional[str] = Field(None, description="Override LLM model for this request")


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
    design_id: str
    rtl_code: str
    testbench_code: str
    timeout_seconds: int = Field(60, description="Simulation timeout")


class IterationRecord(BaseModel):
    """One pass of the self-correction loop."""
    iteration: int
    status: str
    fix_summary: str = ""
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
    prompt: str = Field(..., description="Natural language design prompt")
    target_frequency_mhz: Optional[int] = Field(None, description="Target clock frequency hint")
    self_correct: bool = Field(True, description="Enable auto-fix loop")
    max_iterations: int = Field(5, description="Max self-correction iterations")
    timeout_seconds: int = Field(30, description="Per-simulation timeout")
    model: Optional[str] = Field(None, description="Override LLM model for this run")


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
