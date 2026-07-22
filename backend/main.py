import json
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse

import llm_service
from orchestrator import pipeline_events, run_pipeline
from simulator import IcarusSimulator, VCD_FILENAME, LOG_FILENAME
from coverage import compute_coverage
from schematic import build_schematic
from vcd_parser import parse_vcd
from models import (
    GenerateRequest, GenerateResponse,
    SimulationRequest, SimulationResult,
    RunRequest, RunResponse,
)

app = FastAPI(title="SiliconScribe API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://localhost:5173",
        "http://127.0.0.1:5173", "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WORKSPACE = "./workspace"
simulator = IcarusSimulator(workspace=WORKSPACE)

ALLOWED_ARTIFACTS = {VCD_FILENAME, LOG_FILENAME}


def _new_design_id() -> str:
    return str(uuid.uuid4())[:8]


@app.get("/")
async def root():
    return {
        "message": "SiliconScribe API",
        "status": "running",
        "provider": llm_service.get_provider().name,
        "offline": llm_service.is_offline(),
        "simulator_available": simulator.available(),
    }


@app.get("/api/models")
async def get_models():
    """List the models the user can choose for generation (empty when offline)."""
    return llm_service.list_models()


@app.post("/api/design/run", response_model=RunResponse)
async def design_run(request: RunRequest):
    """One-shot: generate -> simulate -> self-correct. Returns everything."""
    try:
        return run_pipeline(
            prompt=request.prompt,
            design_id=_new_design_id(),
            simulator=simulator,
            target_frequency_mhz=request.target_frequency_mhz,
            self_correct=request.self_correct,
            max_iterations=request.max_iterations,
            timeout_seconds=request.timeout_seconds,
            model=request.model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/design/stream")
async def design_stream(request: RunRequest):
    """Server-Sent Events stream of each pipeline stage (drives the agent panel)."""
    design_id = _new_design_id()

    def event_source():
        try:
            for event in pipeline_events(
                prompt=request.prompt,
                design_id=design_id,
                simulator=simulator,
                target_frequency_mhz=request.target_frequency_mhz,
                self_correct=request.self_correct,
                max_iterations=request.max_iterations,
                timeout_seconds=request.timeout_seconds,
                model=request.model,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'stage': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/design/generate", response_model=GenerateResponse)
async def generate_design(request: GenerateRequest):
    """Generate RTL + testbench + explanation only (no simulation)."""
    try:
        design_id = _new_design_id()
        spec = llm_service.parse_intent(request.prompt, model=request.model)
        rtl_code = llm_service.generate_rtl(spec, request.target_frequency_mhz, model=request.model)
        tb_code = llm_service.generate_testbench(rtl_code, spec, model=request.model) if request.include_testbench else None
        explanation = llm_service.explain_design(rtl_code, spec, model=request.model)
        return GenerateResponse(
            design_id=design_id, rtl_spec=spec, rtl_code=rtl_code,
            testbench_code=tb_code, explanation=explanation,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulation/run", response_model=SimulationResult)
async def run_simulation(request: SimulationRequest):
    """Simulate a (possibly hand-edited) RTL/testbench pair once. No auto-fix."""
    try:
        result = simulator.simulate(
            design_id=request.design_id,
            rtl_code=request.rtl_code,
            testbench_code=request.testbench_code,
            timeout=request.timeout_seconds,
        )
        result.coverage = compute_coverage(result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/simulation/{design_id}/waveform")
async def get_waveform(design_id: str):
    """Return parsed VCD JSON for a previously-simulated design."""
    vcd = (simulator.workspace / _safe_id(design_id) / VCD_FILENAME)
    waveform = parse_vcd(vcd)
    if waveform is None:
        raise HTTPException(status_code=404, detail="No waveform for this design")
    return waveform


@app.get("/api/artifacts/{design_id}/{filename}")
async def get_artifact(design_id: str, filename: str):
    """Download a simulation artifact (VCD or transcript). Path-traversal safe."""
    if filename not in ALLOWED_ARTIFACTS:
        raise HTTPException(status_code=400, detail="Artifact not allowed")

    workspace_root = simulator.workspace
    file_path = (workspace_root / _safe_id(design_id) / filename).resolve()

    # Confine strictly within the workspace.
    if not str(file_path).startswith(str(workspace_root)) or not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    return FileResponse(file_path)


def _safe_id(design_id: str) -> str:
    """Reject anything that isn't a plain id segment."""
    if not design_id.isalnum() and "_" not in design_id:
        raise HTTPException(status_code=400, detail="Invalid design id")
    cleaned = "".join(c for c in design_id if c.isalnum() or c == "_")
    if cleaned != design_id:
        raise HTTPException(status_code=400, detail="Invalid design id")
    return cleaned


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
