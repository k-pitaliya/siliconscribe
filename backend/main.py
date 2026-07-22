import json
import logging
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse

import llm_service
from orchestrator import pipeline_events, run_pipeline
from simulator import IcarusSimulator, VCD_FILENAME, LOG_FILENAME
from coverage import compute_coverage
from vcd_parser import parse_vcd
from models import (
    SimulationRequest, SimulationResult,
    RunRequest, RunResponse,
)

# --- Structured logging ---
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("siliconscribe")

# --- Simple in-memory rate limiter (per-IP, sliding window) ---
RATE_LIMIT_WINDOW = 60        # seconds
RATE_LIMIT_MAX_REQUESTS = 20  # per window

_rate_log: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(ip: str):
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_log[ip] = [t for t in _rate_log[ip] if t > cutoff]
    if len(_rate_log[ip]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW}s.",
        )
    _rate_log[ip].append(now)

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


@app.get("/health")
async def health():
    """Health check endpoint for Docker/CI probes."""
    return {"status": "ok", "simulator": simulator.available()}


@app.get("/api/models")
async def get_models():
    """List the models the user can choose for generation (empty when offline)."""
    return llm_service.list_models()


@app.post("/api/design/run", response_model=RunResponse)
async def design_run(request: RunRequest, req: Request):
    """One-shot: generate -> simulate -> self-correct. Returns everything."""
    _check_rate_limit(req.client.host if req.client else "unknown")
    design_id = _new_design_id()
    logger.info("design_run id=%s prompt=%s", design_id, request.prompt[:80])
    try:
        result = run_pipeline(
            prompt=request.prompt,
            design_id=design_id,
            simulator=simulator,
            target_frequency_mhz=request.target_frequency_mhz,
            self_correct=request.self_correct,
            max_iterations=request.max_iterations,
            timeout_seconds=request.timeout_seconds,
            model=request.model,
        )
        logger.info("design_run id=%s status=%s iterations=%s", design_id, result.status, result.iterations)
        return result
    except Exception as e:
        logger.exception("design_run id=%s failed", design_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/design/stream")
async def design_stream(request: RunRequest, req: Request):
    """Server-Sent Events stream of each pipeline stage (drives the agent panel)."""
    _check_rate_limit(req.client.host if req.client else "unknown")
    design_id = _new_design_id()
    logger.info("design_stream id=%s prompt=%s", design_id, request.prompt[:80])

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
            logger.exception("design_stream id=%s error", design_id)
            yield f"data: {json.dumps({'stage': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/simulation/run", response_model=SimulationResult)
async def run_simulation(request: SimulationRequest):
    """Simulate a (possibly hand-edited) RTL/testbench pair once. No auto-fix."""
    logger.info("run_simulation id=%s", request.design_id)
    try:
        result = simulator.simulate(
            design_id=request.design_id,
            rtl_code=request.rtl_code,
            testbench_code=request.testbench_code,
            timeout=request.timeout_seconds,
        )
        result.coverage = compute_coverage(result)
        logger.info("run_simulation id=%s status=%s", request.design_id, result.status)
        return result
    except Exception as e:
        logger.exception("run_simulation id=%s failed", request.design_id)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
