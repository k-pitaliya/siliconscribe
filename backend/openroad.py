"""
openroad.py — OpenROAD flow stub (export-only, graceful fallback).

Future: floorplan → place → route via OpenROAD `openroad/flow`.
Current: zero-budget stub that checks for `openroad` binary and returns
`{available: False}` so orchestrator/frontend gracefully fall back.
Docker can add `openroad` later; local without it never breaks.
"""

import shutil
import subprocess
import re
from pathlib import Path
from typing import Dict, Optional

def check_openroad_available() -> bool:
    return shutil.which("openroad") is not None

def run_openroad_flow(rtl_code: str, module_name: str, work_dir: Path, sdc_content: Optional[str] = None) -> Dict:
    """
    Try to run OpenROAD flow. Currently stub: returns available False with note.
    If openroad is installed, attempts `openroad -version` and returns step.
    """
    if shutil.which("openroad") is None:
        return {"available": False, "note": "OpenROAD not installed — install via docker openroad/flow or brew (future). Stub only."}
    # Basic version check
    try:
        r = subprocess.run(["openroad", "-version"], capture_output=True, text=True, timeout=10)
        ver = (r.stdout or r.stderr or "").strip()[:500]
        return {"available": True, "version": ver, "note": "OpenROAD present but full P&R flow not yet wired (stub). Use yosys synthesis metrics for now."}
    except Exception as e:
        return {"available": True, "error": str(e)[:500]}

__all__ = ["check_openroad_available", "run_openroad_flow"]
