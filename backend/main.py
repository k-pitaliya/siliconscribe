import json
import logging
import time
import uuid
from collections import defaultdict
from pathlib import Path

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
    SynthesisRequest,
)

try:
    from cleanup import cleanup_old_workspaces
except ImportError:
    cleanup_old_workspaces = None  # type: ignore

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

# Workspace GC on startup (best-effort; do not fail boot if workspace missing)
if cleanup_old_workspaces is not None:
    try:
        # Run eagerly at import so early tests also benefit, but also wire as startup event
        cleanup_old_workspaces(WORKSPACE, ttl_hours=24)
    except Exception:
        logger.exception("startup cleanup failed")


@app.on_event("startup")
async def _startup_gc():
    if cleanup_old_workspaces is not None:
        try:
            removed = cleanup_old_workspaces(WORKSPACE, ttl_hours=24)
            logger.info("startup GC removed %d stale workspaces", removed)
        except Exception:
            logger.exception("startup GC failed")


# Alternative lifespan handler for newer FastAPI (if on_event is deprecated)
try:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore
        if cleanup_old_workspaces is not None:
            try:
                cleanup_old_workspaces(WORKSPACE, ttl_hours=24)
            except Exception:
                logger.exception("lifespan cleanup failed")
        yield

    # Only assign if not already set; app.router.lifespan_context is newer API
    if not getattr(app, "router", None) or not getattr(app.router, "lifespan_context", None):
        pass  # keep existing on_event; lifespan wiring is optional
except Exception:
    pass


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
    except HTTPException:
        raise
    except Exception:
        logger.exception("design_run id=%s failed", design_id)
        raise HTTPException(status_code=500, detail="Internal server error")


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
        except Exception:
            logger.exception("design_stream id=%s error", design_id)
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/simulation/run", response_model=SimulationResult)
async def run_simulation(request: SimulationRequest, req: Request):
    """Simulate a (possibly hand-edited) RTL/testbench pair once. No auto-fix."""
    _check_rate_limit(req.client.host if req.client else "unknown")
    logger.info("run_simulation id=%s", request.design_id)
    try:
        result = simulator.simulate(
            design_id=request.design_id,
            rtl_code=request.rtl_code,
            testbench_code=request.testbench_code,
            timeout=request.timeout_seconds,
        )
        # Sanitize artifact paths: ensure they are inside workspace before exposing
        for attr in ("waveform_file", "transcript_file"):
            val = getattr(result, attr, None)
            if val:
                try:
                    p = Path(val).resolve()
                    ws = Path(WORKSPACE).resolve()
                    try:
                        is_inside = p.is_relative_to(ws)
                    except AttributeError:
                        try:
                            p.relative_to(ws)
                            is_inside = True
                        except ValueError:
                            is_inside = False
                    if not is_inside:
                        logger.warning("sanitized artifact path outside workspace: %s", val)
                        setattr(result, attr, None)
                except Exception:
                    setattr(result, attr, None)
        result.coverage = compute_coverage(result)
        logger.info("run_simulation id=%s status=%s", request.design_id, result.status)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("run_simulation id=%s failed", request.design_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/synthesis/run")
async def run_synthesis(request: SynthesisRequest, req: Request):
    """Synthesize RTL with Yosys (if available) and return gate-level metrics.

    Graceful fallback: when ``yosys`` is not installed the endpoint returns
    ``{"available": False}`` with HTTP 200 so offline mode never breaks.
    """
    _check_rate_limit(req.client.host if req.client else "unknown")
    logger.info("run_synthesis module=%s len=%d", request.module_name, len(request.rtl_code))
    try:
        try:
            from synthesis import YosysSynthesizer  # type: ignore
        except Exception as e:
            logger.warning("synthesis import failed: %s", e)
            return {"available": False, "error": "synthesis module not available"}
        # Use an isolated work dir per request to avoid collisions
        work_dir = Path(WORKSPACE) / f"synth_{request.module_name}_{uuid.uuid4().hex[:6]}"
        synthesizer = YosysSynthesizer(workspace=WORKSPACE)
        result = synthesizer.synthesize(request.rtl_code, request.module_name, work_dir=work_dir)
        logger.info("run_synthesis module=%s available=%s cell_count=%s", request.module_name, result.get("available"), result.get("cell_count"))
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("run_synthesis failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/admin/cleanup")
async def admin_cleanup(request: Request, ttl_hours: int = 24):
    """Admin: remove workspace dirs older than TTL (default 24h)."""
    if cleanup_old_workspaces is None:
        raise HTTPException(status_code=500, detail="Internal server error")
    # Validate TTL to prevent abuse: negative/zero would delete everything
    if not isinstance(ttl_hours, int) or ttl_hours < 1:
        raise HTTPException(status_code=422, detail="ttl_hours must be >= 1")
    if ttl_hours > 720:  # cap at 30 days
        raise HTTPException(status_code=422, detail="ttl_hours must be <= 720")
    # Simple rate-limit even for admin
    if request.client:
        _check_rate_limit(request.client.host)
    try:
        removed = cleanup_old_workspaces(WORKSPACE, ttl_hours=ttl_hours)
        logger.info("admin cleanup removed %d (ttl=%dh)", removed, ttl_hours)
        return {"removed": removed, "workspace": str(Path(WORKSPACE).resolve()), "ttl_hours": ttl_hours}
    except Exception:
        logger.exception("admin cleanup failed")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
