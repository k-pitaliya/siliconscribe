import json
import logging
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import llm_service
from orchestrator import pipeline_events, run_pipeline, _user_facing_error as orchestrator_user_error
from simulator import IcarusSimulator
from cov_metrics import compute_coverage
from vcd_parser import parse_vcd, ports_from_rtl
from orchestrator import _tb_check_count
from models import (
    SimError,
    SimulationRequest, SimulationRerunResponse,
    RunRequest, RunResponse, RTLDesignSpec, SpecParseRequest,
    SynthesisRequest, TimingRequest, TimingReport,
    UVMExportRequest, UVMExportResponse,
    DESIGN_ID_RE,
)

try:
    import db  # type: ignore
except ImportError:
    db = None  # type: ignore

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
_rate_lock = threading.Lock()  # handlers now run in a thread pool


def _trust_proxy_headers() -> bool:
    return os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes", "on")


def _get_client_ip(req: Request) -> str:
    # Forwarded headers are only believable when a trusted proxy sets them. A client that
    # reaches the app directly can send any X-Forwarded-For / CF-Connecting-IP value, which
    # let one caller dodge the per-IP limit entirely (review finding, reproduced: 25/25
    # requests accepted against a 20/min limit). So by default use the socket peer, and
    # honour the headers only when the deployment says it runs behind a proxy
    # (TRUST_PROXY_HEADERS=1, set in render.yaml).
    if not _trust_proxy_headers():
        return req.client.host if req.client else "unknown"
    # Behind Render/Vercel the direct peer is a proxy, so XFF is needed. Use the
    # LAST entry: client-supplied XFF values are prepended, the proxy appends the
    # address it actually saw.
    xff = req.headers.get("x-forwarded-for")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    ccip = req.headers.get("cf-connecting-ip")
    if ccip:
        return ccip.strip()
    x_real = req.headers.get("x-real-ip")
    if x_real:
        return x_real.strip()
    return req.client.host if req.client else "unknown"


def _check_rate_limit(ip: str):
    with _rate_lock:
        _check_rate_limit_locked(ip)


def _check_rate_limit_locked(ip: str):
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_log[ip] = [t for t in _rate_log[ip] if t > cutoff]
    # Always prune stale empty entries (not only when >500) to prevent unbounded growth
    # Opportunistic sweep every call but cheap when small
    if len(_rate_log) > 100:
        for k in list(_rate_log.keys()):
            if k != ip:
                if not _rate_log[k]:
                    _rate_log.pop(k, None)
                else:
                    # prune stale timestamps
                    trimmed = [t for t in _rate_log[k] if t > cutoff]
                    if not trimmed:
                        _rate_log.pop(k, None)
                    elif len(trimmed) != len(_rate_log[k]):
                        _rate_log[k] = trimmed
    if len(_rate_log[ip]) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MAX_REQUESTS} requests per {RATE_LIMIT_WINDOW}s.",
            headers={"Retry-After": str(int(RATE_LIMIT_WINDOW))},
        )
    _rate_log[ip].append(now)
    if not _rate_log[ip]:
        _rate_log[ip] = [now]

def _cors_origins() -> list:
    """Browser origins allowed to call this API: this machine only, unless CORS_ALLOW_ORIGINS adds exact origins.

    There is deliberately no wildcard such as *.vercel.app: anyone can host a page there, and that page could make
    the visitor's browser call a backend that holds paid-capable model keys and runs any model it is asked to.
    """
    local = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"]
    extra = [o.strip().rstrip("/") for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip().startswith(("http://", "https://"))]
    return local + [o for o in extra if "*" not in o]


app = FastAPI(title="SiliconScribe API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,  # no cookie auth exists; credentials plus a wildcard origin regex was a standing foot-gun
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

WORKSPACE = "./workspace"
simulator = IcarusSimulator(workspace=WORKSPACE)

# Workspace GC on startup (best-effort; do not fail boot if workspace missing). Done once, at import:
# a uvicorn/gunicorn worker imports this module exactly when it boots.
if cleanup_old_workspaces is not None:
    try:
        cleanup_old_workspaces(WORKSPACE, ttl_hours=24)
    except Exception:
        logger.exception("startup cleanup failed")

# Init SQLite persistence (best-effort; do not fail boot)
if db is not None:
    try:
        db.init_db(WORKSPACE)
    except Exception:
        logger.exception("db init failed")



def _new_design_id() -> str:
    # Full UUID: a truncated id (previously 8 hex chars = 32 bits) can collide,
    # and the DB write is an INSERT — silent overwrite of another user's project.
    return uuid.uuid4().hex


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
def get_models(req: Request, include_paid: bool = False, refresh: bool = False):
    """Models the user can choose for generation: the OpenCode app's list and Cloudflare Workers AI.

    `include_paid` also lists the models not marked free (they may use credits). `refresh` re-reads both
    catalogues instead of the cache, and is rate limited because it calls out. A plain `def`: listing can
    wait on a subprocess and on the network, which must not block the event loop.
    """
    if refresh:
        _check_rate_limit(_get_client_ip(req))
    return llm_service.list_models(include_paid=include_paid, refresh=refresh)


@app.post("/api/spec/parse", response_model=RTLDesignSpec)
def parse_spec(request: SpecParseRequest, req: Request):
    """Turn a prompt into a specification and stop, so the user can read and edit it before anything is generated."""
    _check_rate_limit(_get_client_ip(req))
    try:
        return llm_service.parse_intent(request.prompt, model=request.model, reasoning_effort=request.reasoning_effort)
    except llm_service.ModelNotAvailable as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("spec parse failed")
        raise HTTPException(status_code=502, detail=orchestrator_user_error(e))


@app.post("/api/design/run", response_model=RunResponse)
def design_run(request: RunRequest, req: Request):
    """One-shot: generate -> simulate -> self-correct. Returns everything."""
    _check_rate_limit(_get_client_ip(req))
    design_id = _new_design_id()
    logger.info("design_run id=%s prompt=%s model=%s reasoning=%s", design_id, request.prompt[:80], request.model, request.reasoning_effort)
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
            testbench_model=request.testbench_model,
            spec_override=request.spec,
            reasoning_effort=request.reasoning_effort,
        )
        logger.info("design_run id=%s status=%s iterations=%s", design_id, result.status, result.iterations)
        # Persist to SQLite (best-effort, never fail request)
        if db is not None:
            try:
                try:
                    db.save_project(result, prompt=request.prompt)
                except TypeError:
                    db.save_project(result)
            except Exception:
                logger.exception("db save failed for %s", design_id)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("design_run id=%s failed", design_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/design/stream")
async def design_stream(request: RunRequest, req: Request):
    """Server-Sent Events stream of each pipeline stage (drives the agent panel)."""
    _check_rate_limit(_get_client_ip(req))
    design_id = _new_design_id()
    logger.info("design_stream id=%s prompt=%s model=%s reasoning=%s", design_id, request.prompt[:80], request.model, request.reasoning_effort)

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
                testbench_model=request.testbench_model,
                spec_override=request.spec,
                reasoning_effort=request.reasoning_effort,
            ):
                if event.get("stage") == "done" and db is not None:
                    # The browser uses this streaming route, so it must persist the
                    # finished project exactly like /api/design/run does; otherwise
                    # the Projects drawer never lists anything generated in the UI.
                    try:
                        db.save_project(RunResponse(**event["response"]), prompt=request.prompt)
                    except Exception:
                        logger.exception("db save failed for stream %s", design_id)
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            logger.exception("design_stream id=%s error", design_id)
            yield f"data: {json.dumps({'stage': 'error', 'message': 'Internal server error'})}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/simulation/run", response_model=SimulationRerunResponse)
def run_simulation(request: SimulationRequest, req: Request):
    """Simulate a (possibly hand-edited) RTL/testbench pair once. No auto-fix."""
    _check_rate_limit(_get_client_ip(req))
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
        if result.status == "PASS" and _tb_check_count(request.testbench_code) == 0:
            # Same rule as the generation path: a testbench that cannot fail proves nothing.
            result.status = "ERROR"
            result.errors.append(SimError(message="The testbench contains no self-checks; refusing to report PASS."))
        result.coverage = compute_coverage(result)
        logger.info("run_simulation id=%s status=%s", request.design_id, result.status)
        waveform = None
        if result.waveform_file:
            try:
                waveform = parse_vcd(result.waveform_file, ports=ports_from_rtl(request.rtl_code))
            except Exception:
                logger.exception("waveform parse failed for %s", request.design_id)
        return SimulationRerunResponse(**result.model_dump(), waveform=waveform)
    except HTTPException:
        raise
    except Exception:
        logger.exception("run_simulation id=%s failed", request.design_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/synthesis/run")
def run_synthesis(request: SynthesisRequest, req: Request):
    """Synthesize RTL with Yosys (if available) and return gate-level metrics.

    Graceful fallback: when ``yosys`` is not installed the endpoint returns
    ``{"available": False}`` with HTTP 200 so offline mode never breaks.
    """
    _check_rate_limit(_get_client_ip(req))
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


@app.get("/api/projects")
def list_projects_endpoint(request: Request, limit: int = 20, offset: int = 0):
    """List persisted projects, newest first."""
    _check_rate_limit(_get_client_ip(request))
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")
    if db is None:
        return {"total": 0, "projects": []}
    try:
        total = db.count_projects()
        projects = db.list_projects(limit=limit, offset=offset)
        return {"total": total, "projects": projects}
    except HTTPException:
        raise
    except Exception:
        logger.exception("list_projects failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/projects/{design_id}")
def get_project_endpoint(design_id: str, request: Request):
    """Get full RunResponse for a persisted project."""
    _check_rate_limit(_get_client_ip(request))
    if not DESIGN_ID_RE.match(design_id):
        raise HTTPException(status_code=422, detail="Invalid design_id")
    if db is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        proj = db.get_project(design_id)
    except Exception:
        logger.exception("get_project failed for %s", design_id)
        raise HTTPException(status_code=500, detail="Internal server error")
    if proj is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return proj


@app.delete("/api/projects/{design_id}", status_code=204)
def delete_project_endpoint(design_id: str, request: Request):
    """Delete a persisted project."""
    _check_rate_limit(_get_client_ip(request))
    if not DESIGN_ID_RE.match(design_id):
        raise HTTPException(status_code=422, detail="Invalid design_id")
    if db is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        deleted = db.delete_project(design_id)
    except Exception:
        logger.exception("delete_project failed for %s", design_id)
        raise HTTPException(status_code=500, detail="Internal server error")
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    from fastapi.responses import Response

    return Response(status_code=204)


@app.post("/api/timing/run", response_model=TimingReport)
def run_timing_route(request: TimingRequest, req: Request):
    """Map the RTL to sky130 cells and report pre-layout timing at the target clock."""
    _check_rate_limit(_get_client_ip(req))
    from timing import run_timing
    return run_timing(request.rtl_code, request.module_name,
                      Path(WORKSPACE) / ("ti_" + _new_design_id()[:24]), request.target_frequency_mhz,
                      testbench_code=request.testbench_code)


@app.post("/api/uvm/export", response_model=UVMExportResponse)
def uvm_export(request: UVMExportRequest, req: Request):
    """Export a UVM testbench bundle (Questa style) for a spec derived from prompt.

    Export-only, never calls Icarus. Uses llm_service.parse_intent to derive
    RTLDesignSpec, then uvm_templates.generate_uvm_bundle. Gracefully falls back
    to offline spec when Zen not available.
    """
    _check_rate_limit(_get_client_ip(req))
    logger.info("uvm_export prompt=%s module_override=%s", request.prompt[:80], request.module_name)
    try:
        from uvm_templates import generate_uvm_bundle, bundle_to_zip_base64
    except Exception:
        logger.exception("uvm_templates import failed")
        raise HTTPException(status_code=500, detail="UVM templates not available")
    try:
        spec = llm_service.parse_intent(request.prompt, model=request.model, reasoning_effort=request.reasoning_effort)
        if request.module_name:
            spec.module_name = request.module_name
        bundle = generate_uvm_bundle(spec)
        # Detect sequential for response
        is_seq = any("sequential" in (c or "").lower() for c in (spec.constraints or []))
        zip_b64 = None
        try:
            zip_b64 = bundle_to_zip_base64(bundle)
        except Exception:
            logger.exception("uvm zip failed")
        return UVMExportResponse(
            module_name=spec.module_name,
            files=bundle,
            file_count=len(bundle),
            is_sequential=is_seq,
            zip_base64=zip_b64,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("uvm_export failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/api/admin/cleanup")
def admin_cleanup(request: Request, ttl_hours: int = 24):
    """Admin: remove workspace dirs older than TTL (default 24h).

    Requires the ``X-Admin-Token`` header to match the ``ADMIN_TOKEN`` env var.
    If ADMIN_TOKEN is unset the endpoint is disabled: an unauthenticated delete
    endpoint is a denial-of-service waiting to happen.
    """
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Admin cleanup is disabled. Set ADMIN_TOKEN to enable it.",
        )
    supplied = request.headers.get("x-admin-token", "")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Forbidden")
    if cleanup_old_workspaces is None:
        raise HTTPException(status_code=500, detail="Internal server error")
    # Validate TTL to prevent abuse: negative/zero would delete everything
    if not isinstance(ttl_hours, int) or ttl_hours < 1:
        raise HTTPException(status_code=422, detail="ttl_hours must be >= 1")
    if ttl_hours > 720:  # cap at 30 days
        raise HTTPException(status_code=422, detail="ttl_hours must be <= 720")
    # Simple rate-limit even for admin
    if request.client:
        _check_rate_limit(_get_client_ip(request))
    try:
        removed = cleanup_old_workspaces(WORKSPACE, ttl_hours=ttl_hours)
        logger.info("admin cleanup removed %d (ttl=%dh)", removed, ttl_hours)
        return {"removed": removed, "workspace": str(Path(WORKSPACE).resolve()), "ttl_hours": ttl_hours}
    except Exception:
        logger.exception("admin cleanup failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# Serve frontend static when Docker image includes it (docker-compose local single-container).
# In split deploy (Vercel frontend + Render backend) ./static does not exist and this is a no-op.
try:
    from fastapi.staticfiles import StaticFiles

    _static_candidates = [Path(__file__).parent / "static", Path("static"), Path("./static")]
    _static_dir = next((p for p in _static_candidates if p.exists() and (p / "index.html").exists()), None)
    if _static_dir is not None:
        # Mount at "/" after API routes; explicit API routes (/, /health, /api/*) take precedence
        app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="frontend")
        logger.info("mounted static frontend from %s", _static_dir.resolve())
except Exception:
    logger.exception("static mount failed (non-fatal, API-only mode)")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
