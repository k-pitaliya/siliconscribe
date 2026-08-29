"""
SQLite persistence for ai-eda-playground (zero-budget, stdlib only).

- File: Path(WORKSPACE)/"projects.db"  (defaults to backend/workspace/projects.db)
- Table `projects` with columns:
    id TEXT PRIMARY KEY,
    prompt TEXT,
    module_name TEXT,
    rtl_spec TEXT (JSON),
    rtl_code TEXT,
    testbench_code TEXT,
    explanation TEXT,
    status TEXT,
    pass_count INTEGER,
    fail_count INTEGER,
    iterations INTEGER,
    created_at REAL,
    waveform_truncated INTEGER,
    data TEXT (full RunResponse JSON for faithful retrieval)

Thread-safe: every function opens a new sqlite3 connection, ensures table exists,
executes, commits, closes. No shared connection / no lock needed.

Workspace handling: ensures workspace directory exists; _db_path resolves
relative WORKSPACE values relative to this file's parent (backend/workspace)
for stable location regardless of cwd, while still accepting absolute tmp paths.
"""

import json
import sqlite3
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("siliconscribe.db")

# Default workspace fallback when no explicit workspace given
# Mirrors main.WORKSPACE = "./workspace" but resolved to backend/workspace for stability
_DEFAULT_WORKSPACE = Path(__file__).parent / "workspace"
_DB_FILENAME = "projects.db"


def _resolve_workspace(workspace=None) -> Path:
    """
    Resolve workspace Path.
    - If workspace is None: try lazy import of main.WORKSPACE, else fallback to backend/workspace
    - If workspace is relative with leading '.' (./workspace), resolve relative to this file's parent
      so the DB is always at backend/workspace/projects.db regardless of cwd.
    - If workspace is absolute (e.g. /tmp/...), use it verbatim.
    - Otherwise resolve against cwd or file parent (handles 'workspace' bare string).
    """
    ws = workspace
    if ws is None:
        try:
            import main as _main  # lazy to avoid circular import at top-level
            candidate = getattr(_main, "WORKSPACE", None)
            if candidate:
                ws = candidate
        except Exception:
            pass
    if ws is None:
        ws = _DEFAULT_WORKSPACE

    p = Path(ws)
    if p.is_absolute():
        workspace_path = p
    else:
        # Relative path handling
        s = str(p)
        # For "./workspace" or "../something" treat as relative to this file's parent
        # This makes Path("./workspace") -> backend/workspace irrespective of cwd
        if s.startswith("."):
            # e.g. "./workspace" -> backend/workspace
            workspace_path = (Path(__file__).parent / p).resolve()
        else:
            # bare "workspace" -> also backend/workspace
            # If it already looks like a path with separators, prefer file-parent resolution for stability
            # But if caller explicitly passed a relative tmp path like "tmp_xxx", we still want file-parent?
            # For safety, if workspace came from lazy main.WORKSPACE ("./workspace"), we handled above.
            # For any other bare relative, treat as file-parent as well to keep consistent.
            # However absolute tmp paths are already handled.
            try:
                # Try to resolve against cwd first, but fallback to file parent if that dir doesn't exist
                # Simpler: always resolve against file parent for non-absolute to guarantee backend/workspace
                workspace_path = (Path(__file__).parent / p).resolve() if s == "workspace" or "/" in s or "\\" in s else Path(p).resolve()
                # If the cwd-resolved path doesn't exist and file-parent version does, prefer file-parent
                # To keep deterministic, just use file-parent for simple names
                if s in ("workspace", "workspace/") or s.startswith("workspace/"):
                    workspace_path = (Path(__file__).parent / p).resolve()
            except Exception:
                workspace_path = Path(p).resolve()
            # Final fallback: if workspace_path still relative, make absolute via file parent
            if not workspace_path.is_absolute():
                workspace_path = (Path(__file__).parent / workspace_path).resolve()
    # Ensure workspace dir exists
    try:
        workspace_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        logger.exception("Failed to create workspace dir %s", workspace_path)
    return workspace_path


def _db_path(workspace=None) -> Path:
    ws_path = _resolve_workspace(workspace)
    # If ws_path points to a file (unlikely), use its parent
    # Otherwise assume it's a directory
    if ws_path.is_file():
        ws_path = ws_path.parent
    return ws_path / _DB_FILENAME


def _ensure_table(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            prompt TEXT,
            module_name TEXT,
            rtl_spec TEXT,
            rtl_code TEXT,
            testbench_code TEXT,
            explanation TEXT,
            status TEXT,
            pass_count INTEGER,
            fail_count INTEGER,
            iterations INTEGER,
            created_at REAL,
            waveform_truncated INTEGER,
            data TEXT
        )
        """
    )
    # Migration: ensure 'data' column exists for DBs created before it was added
    try:
        cur = conn.execute("PRAGMA table_info(projects)")
        cols = {row[1] for row in cur.fetchall()}
        if "data" not in cols:
            conn.execute("ALTER TABLE projects ADD COLUMN data TEXT")
        # Also ensure prompt column etc if older DB missing? Check all expected columns
        for col, coldef in [
            ("prompt", "TEXT"),
            ("module_name", "TEXT"),
            ("rtl_spec", "TEXT"),
            ("rtl_code", "TEXT"),
            ("testbench_code", "TEXT"),
            ("explanation", "TEXT"),
            ("status", "TEXT"),
            ("pass_count", "INTEGER"),
            ("fail_count", "INTEGER"),
            ("iterations", "INTEGER"),
            ("created_at", "REAL"),
            ("waveform_truncated", "INTEGER"),
        ]:
            if col not in cols:
                try:
                    conn.execute(f"ALTER TABLE projects ADD COLUMN {col} {coldef}")
                except Exception:
                    pass
    except Exception:
        # If pragma fails, ignore – table creation will have covered most
        pass
    # Optional: create index on created_at for sorted listing
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at DESC)")
    except Exception:
        pass


def init_db(workspace=None):
    """Ensure workspace exists and projects table is created."""
    path = _db_path(workspace)
    # Ensure parent dir exists (already done in _db_path)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        _ensure_table(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _extract_fields(run_response, prompt_override: Optional[str] = None) -> Dict[str, Any]:
    """
    Normalize RunResponse (pydantic model or dict) into DB row dict.
    prompt_override takes precedence over any prompt in the payload.
    """
    # Normalize to dict
    if hasattr(run_response, "model_dump"):
        try:
            d = run_response.model_dump()
        except Exception:
            d = dict(run_response)  # fallback
    elif isinstance(run_response, dict):
        d = run_response
    else:
        # Try dict conversion
        try:
            d = dict(run_response)
        except Exception:
            raise ValueError("run_response must be dict or pydantic model")

    design_id = d.get("design_id") or d.get("id")
    if not design_id:
        raise ValueError("run_response missing design_id/id")

    rtl_spec = d.get("rtl_spec")
    rtl_spec_json = "{}"
    module_name = ""
    if rtl_spec is not None:
        if hasattr(rtl_spec, "model_dump"):
            try:
                rtl_spec_dict = rtl_spec.model_dump()
                rtl_spec_json = json.dumps(rtl_spec_dict)
                module_name = rtl_spec_dict.get("module_name", "") or ""
            except Exception:
                rtl_spec_json = json.dumps({})
        elif isinstance(rtl_spec, dict):
            try:
                rtl_spec_json = json.dumps(rtl_spec)
                module_name = rtl_spec.get("module_name", "") or ""
            except Exception:
                rtl_spec_json = "{}"
        elif isinstance(rtl_spec, str):
            # assume already JSON or raw
            try:
                parsed = json.loads(rtl_spec)
                if isinstance(parsed, dict):
                    module_name = parsed.get("module_name", "") or ""
                rtl_spec_json = rtl_spec
            except Exception:
                rtl_spec_json = json.dumps({"raw": rtl_spec})
        else:
            try:
                rtl_spec_json = json.dumps(str(rtl_spec))
            except Exception:
                rtl_spec_json = "{}"

    # Fallback module_name from schematic if rtl_spec didn't have it
    if not module_name:
        schematic = d.get("schematic")
        if schematic is not None:
            if hasattr(schematic, "model_dump"):
                try:
                    s = schematic.model_dump()
                    module_name = s.get("module_name", "") or ""
                except Exception:
                    pass
            elif isinstance(schematic, dict):
                module_name = schematic.get("module_name", "") or ""
            elif isinstance(schematic, str):
                try:
                    s = json.loads(schematic)
                    module_name = s.get("module_name", "") or ""
                except Exception:
                    pass

    rtl_code = d.get("rtl_code", "") or ""
    testbench_code = d.get("testbench_code", "") or d.get("testbench", "") or ""
    explanation = d.get("explanation", "") or ""
    status = d.get("status", "") or ""

    result = d.get("result")
    if result is not None and hasattr(result, "model_dump"):
        try:
            result = result.model_dump()
        except Exception:
            result = {}
    if not isinstance(result, dict):
        result = {} if result is None else {}

    pass_count = 0
    fail_count = 0
    try:
        pass_count = int(result.get("pass_count", 0) or 0)
    except Exception:
        pass_count = 0
    try:
        fail_count = int(result.get("fail_count", 0) or 0)
    except Exception:
        fail_count = 0

    iterations = 0
    try:
        iterations = int(d.get("iterations", 0) or 0)
    except Exception:
        iterations = 0

    waveform = d.get("waveform")
    if waveform is not None and hasattr(waveform, "model_dump"):
        try:
            waveform = waveform.model_dump()
        except Exception:
            waveform = {}
    waveform_truncated = 0
    if isinstance(waveform, dict):
        # check truncated or changes_truncated
        truncated = waveform.get("truncated")
        if truncated:
            waveform_truncated = 1
        elif waveform.get("changes_truncated"):
            waveform_truncated = 1
    elif isinstance(waveform, str):
        try:
            wj = json.loads(waveform)
            if wj.get("truncated"):
                waveform_truncated = 1
        except Exception:
            pass

    # prompt handling
    prompt_val = prompt_override
    if prompt_val is None:
        # try from dict
        prompt_val = d.get("prompt")
        if prompt_val is None:
            # check if run_response had attribute prompt (model_extra)
            try:
                prompt_val = getattr(run_response, "prompt", None)
            except Exception:
                prompt_val = None
        if prompt_val is None:
            prompt_val = ""
    # Ensure string
    prompt_val = str(prompt_val) if prompt_val is not None else ""

    created_at = time.time()

    # Full data JSON – use original d (ensure serializable)
    # If d already came from model_dump, it's serializable. Otherwise try json dump.
    try:
        data_json = json.dumps(d, default=str)
    except Exception:
        # minimal fallback
        data_json = json.dumps({
            "design_id": str(design_id),
            "prompt": prompt_val,
            "rtl_spec": json.loads(rtl_spec_json) if rtl_spec_json else {},
            "rtl_code": str(rtl_code),
            "testbench_code": str(testbench_code),
            "explanation": str(explanation),
            "status": str(status),
            "result": result,
            "iterations": iterations,
            "waveform": waveform if isinstance(waveform, dict) else None,
        }, default=str)

    return {
        "id": str(design_id),
        "prompt": prompt_val,
        "module_name": str(module_name or ""),
        "rtl_spec": rtl_spec_json,
        "rtl_code": str(rtl_code),
        "testbench_code": str(testbench_code),
        "explanation": str(explanation),
        "status": str(status),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "iterations": iterations,
        "created_at": float(created_at),
        "waveform_truncated": int(waveform_truncated),
        "data": data_json,
    }


def save_project(run_response, prompt: Optional[str] = None, workspace=None):
    """
    Persist a RunResponse (or dict) to SQLite.
    - run_response: RunResponse pydantic model or dict with at least design_id
    - prompt: optional prompt string; if None, extracted from run_response if present else ""
    - workspace: optional workspace override (defaults to main.WORKSPACE or backend/workspace)
    """
    # Handle case where caller passed prompt as second positional but it's actually a workspace path
    # If prompt looks like a path and workspace is None and prompt contains "/" and not typical prompt, ambiguous.
    # We treat second arg always as prompt; workspace must be passed as keyword.
    # To support legacy spec where only one arg, this is fine.
    fields = _extract_fields(run_response, prompt_override=prompt)
    path = _db_path(workspace)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        _ensure_table(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO projects
            (id, prompt, module_name, rtl_spec, rtl_code, testbench_code, explanation, status, pass_count, fail_count, iterations, created_at, waveform_truncated, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["id"],
                fields["prompt"],
                fields["module_name"],
                fields["rtl_spec"],
                fields["rtl_code"],
                fields["testbench_code"],
                fields["explanation"],
                fields["status"],
                fields["pass_count"],
                fields["fail_count"],
                fields["iterations"],
                fields["created_at"],
                fields["waveform_truncated"],
                fields["data"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return fields["id"]


def get_project(design_id: str, workspace=None):
    """
    Retrieve a project by id. Returns full RunResponse dict (as stored) or None if not found.
    If stored data JSON exists, that is returned (with prompt merged). Otherwise reconstructs minimal dict.
    """
    if not isinstance(design_id, str) or not design_id:
        return None
    path = _db_path(workspace)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT data, id, prompt, module_name, rtl_spec, rtl_code, testbench_code, explanation, status, pass_count, fail_count, iterations, created_at, waveform_truncated FROM projects WHERE id = ?",
            (design_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        data_json, rid, prompt, module_name, rtl_spec_json, rtl_code, testbench_code, explanation, status, pass_count, fail_count, iterations, created_at, waveform_truncated = row
        if data_json:
            try:
                data = json.loads(data_json)
                # Ensure prompt is present (fallback to column if missing)
                if not data.get("prompt") and prompt:
                    data["prompt"] = prompt
                # Ensure design_id key present
                if not data.get("design_id") and rid:
                    data["design_id"] = rid
                return data
            except Exception:
                pass
        # Fallback reconstruction
        try:
            rtl_spec_dict = json.loads(rtl_spec_json) if rtl_spec_json else {}
        except Exception:
            rtl_spec_dict = {}
        # Build minimal RunResponse-like dict
        reconstructed = {
            "design_id": rid,
            "prompt": prompt or "",
            "rtl_spec": rtl_spec_dict,
            "rtl_code": rtl_code or "",
            "testbench_code": testbench_code or "",
            "explanation": explanation or "",
            "status": status or "",
            "result": {
                "status": status or "UNKNOWN",
                "module_name": module_name or "",
                "simulation_time_ns": 0,
                "test_count": (pass_count or 0) + (fail_count or 0),
                "pass_count": pass_count or 0,
                "fail_count": fail_count or 0,
                "coverage": {},
                "errors": [],
                "waveform_file": None,
                "transcript_file": None,
                "log_excerpt": "",
            },
            "iterations": iterations or 0,
            "iteration_history": [],
            "waveform": {
                "timescale": "1ns",
                "end_time": 0,
                "signals": [],
                "truncated": bool(waveform_truncated),
                "dropped_signals": 0,
                "changes_truncated": bool(waveform_truncated),
            } if waveform_truncated else None,
            "schematic": {
                "module_name": module_name or (rtl_spec_dict.get("module_name") if isinstance(rtl_spec_dict, dict) else ""),
                "inputs": [],
                "outputs": [],
                "inouts": [],
            },
            "synthesis": None,
            "created_at": created_at,
        }
        return reconstructed
    finally:
        conn.close()


def list_projects(limit: int = 50, offset: int = 0, workspace=None):
    """
    List projects ordered by newest first.
    Returns list of dicts with keys: design_id, prompt, module_name, status, created_at, iterations
    """
    # Clamp limit/offset to sane values
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    try:
        offset = int(offset)
    except Exception:
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0

    path = _db_path(workspace)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        _ensure_table(conn)
        cur = conn.execute(
            "SELECT id, prompt, module_name, status, created_at, iterations FROM projects ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cur.fetchall()
        result: List[Dict[str, Any]] = []
        for r in rows:
            rid, prompt, module_name, status, created_at, iterations = r
            result.append(
                {
                    "design_id": rid,
                    "prompt": prompt or "",
                    "module_name": module_name or "",
                    "status": status or "",
                    "created_at": created_at or 0,
                    "iterations": iterations or 0,
                }
            )
        return result
    finally:
        conn.close()


def count_projects(workspace=None) -> int:
    path = _db_path(workspace)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        _ensure_table(conn)
        cur = conn.execute("SELECT COUNT(*) FROM projects")
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def delete_project(design_id: str, workspace=None) -> bool:
    if not isinstance(design_id, str) or not design_id:
        return False
    path = _db_path(workspace)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    try:
        _ensure_table(conn)
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (design_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

