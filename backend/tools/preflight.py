#!/usr/bin/env python3
"""Demo-day readiness check: is everything the live demo needs actually working?

    cd backend
    PATH="$HOME/.local/bin:$PATH" python3 tools/preflight.py            # free checks only
    PATH="$HOME/.local/bin:$PATH" python3 tools/preflight.py --live     # also ONE tiny model call

Each line is OK / WARN / FAIL. The last lines say which rung of the fallback ladder is usable:
live model -> offline demo -> saved results. Nothing here writes to the projects database.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

RESULTS: list[tuple[str, str, str]] = []


def record(level: str, name: str, detail: str) -> None:
    RESULTS.append((level, name, detail))
    print(f"[{level:4s}] {name}: {detail}", flush=True)


def parse_version(text: str) -> tuple[int, ...] | None:
    """'Icarus Verilog version 12.0 (stable)' -> (12, 0)."""
    m = re.search(r"version\s+(\d+)(?:\.(\d+))?", text or "")
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def http_ok(url: str, timeout: float = 4.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 - fixed local URLs
            return 200 <= r.status < 300
    except Exception:
        return False


def check_simulator() -> None:
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        record("FAIL", "Icarus Verilog", "iverilog/vvp not on PATH (add ~/.local/bin)")
        return
    _, out = run(["iverilog", "-V"])
    v = parse_version(out.splitlines()[0] if out else "")
    if v is None:
        record("WARN", "Icarus Verilog", "installed, version not recognised")
    elif v[0] != 12:
        record("WARN", "Icarus Verilog", f"version {v[0]}.{v[1]}; the code was tested against 12.0")
    else:
        record("OK", "Icarus Verilog", f"version {v[0]}.{v[1]}")


def check_yosys() -> None:
    if not shutil.which("yosys"):
        record("WARN", "Yosys", "not installed: synthesis metrics will show 'not available'")
        return
    rc, out = run(["yosys", "-V"], timeout=60)
    record("OK" if rc == 0 else "WARN", "Yosys", out.strip().splitlines()[0][:60] if out.strip() else f"exit {rc}")


def check_offline_pipeline() -> bool:
    # llm_service is imported by main() BEFORE this runs, with the environment the user intends for
    # the live demo; get_provider() re-reads OFFLINE_MODE on every call, so setting it only for this
    # check does not turn the live provider into the offline one.
    previous = os.environ.get("OFFLINE_MODE")
    os.environ["OFFLINE_MODE"] = "1"
    try:
        from orchestrator import run_pipeline
        from simulator import IcarusSimulator
        t = time.time()
        r = run_pipeline("Design a 4-bit synchronous up-counter with async reset and enable", "preflight",
                         IcarusSimulator(workspace=tempfile.mkdtemp()), self_correct=True, max_iterations=2)
        ok = r.status == "PASS" and r.result is not None and r.result.test_count >= 20
        extras = []
        if r.strength and r.strength.total:
            extras.append(f"strength {r.strength.killed}/{r.strength.total}")
        if r.synthesis and r.synthesis.get("available"):
            extras.append(f"{r.synthesis.get('cell_count', '?')} cells")
        record("OK" if ok else "FAIL", "Offline demo pipeline",
               f"{r.status} {r.result.pass_count}/{r.result.test_count} in {time.time() - t:.1f}s" + (f" ({', '.join(extras)})" if extras else ""))
        return ok
    except Exception as e:
        record("FAIL", "Offline demo pipeline", f"{type(e).__name__}: {str(e)[:120]}")
        return False
    finally:
        if previous is None:
            os.environ.pop("OFFLINE_MODE", None)
        else:
            os.environ["OFFLINE_MODE"] = previous


def check_live_config() -> bool:
    provider = os.getenv("LLM_PROVIDER", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if provider != "opencode-app":
        record("WARN", "Live provider", f"LLM_PROVIDER={provider or '(unset)'}; the planned demo path is opencode-app")
    if not shutil.which("opencode"):
        record("FAIL" if provider == "opencode-app" else "WARN", "OpenCode app", "`opencode` not on PATH")
        return False
    rc, out = run(["opencode", "models"], timeout=60)
    listed = {ln.strip() for ln in out.splitlines()}
    wanted = model if "/" in model else f"opencode/{model}"
    if rc != 0:
        record("WARN", "OpenCode app", "`opencode models` failed: is the app signed in?")
        return False
    if model and wanted not in listed:
        record("FAIL", "OpenCode model", f"{wanted} is not offered to this account")
        return False
    record("OK", "OpenCode app", f"signed in; model {wanted or '(default)'} is available")
    try:
        timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "0"))
    except ValueError:
        timeout = 0
    if timeout < 300:
        record("WARN", "LLM timeout", f"LLM_TIMEOUT_SECONDS={timeout or 'default'}: testbench generation can take 120-200 s and runs "
                                     "have taken 11 minutes; use 360")
    else:
        record("OK", "LLM timeout", f"{timeout} s")
    return True


def check_live_call() -> bool:
    try:
        import llm_service
        if llm_service.is_offline():
            record("FAIL", "Live model call", "provider resolved to offline (set LLM_PROVIDER and unset OFFLINE_MODE)")
            return False
        t = time.time()
        reply = llm_service.get_provider()._chat(None, "Reply with exactly the single word OK.", 0.0, stage="intent")
        ok = "ok" in (reply or "").lower()
        record("OK" if ok else "WARN", "Live model call", f"replied in {time.time() - t:.0f}s: {(reply or '').strip()[:40]!r}")
        return ok
    except Exception as e:
        record("FAIL", "Live model call", f"{type(e).__name__}: {str(e)[:140]}")
        return False


def check_servers() -> None:
    record("OK" if http_ok("http://127.0.0.1:8000/health") else "WARN", "Backend :8000",
           "responding" if http_ok("http://127.0.0.1:8000/health") else "not running (start it before the demo)")
    record("OK" if http_ok("http://127.0.0.1:5173/") else "WARN", "Frontend :5173",
           "responding" if http_ok("http://127.0.0.1:5173/") else "not running (cd frontend && npm run dev)")


def check_storage() -> None:
    db = BACKEND / "workspace" / "projects.db"
    if db.exists():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
                n = c.execute("select count(*) from projects").fetchone()[0]
            record("OK", "Projects database", f"{n} saved projects (read-only check)")
        except Exception as e:
            record("WARN", "Projects database", f"unreadable: {str(e)[:80]}")
    else:
        record("OK", "Projects database", "none yet (created on first run)")
    free_gb = shutil.disk_usage(BACKEND).free / 1e9
    record("OK" if free_gb > 2 else "WARN", "Disk space", f"{free_gb:.0f} GB free")


def check_evidence() -> bool:
    res = BACKEND / "evaluation" / "results.jsonl"
    n = len(res.read_text().splitlines()) if res.exists() else 0
    record("OK" if n else "WARN", "Saved live results", f"{n} evaluated prompts in evaluation/results.jsonl" if n else
           "none: run tools/evaluate_live.py so there is evidence to show if the live model is down")
    return bool(n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="also make ONE tiny live model call (uses a little quota)")
    args = ap.parse_args()

    import llm_service  # noqa: F401  (import first so the provider is built from the real environment)

    check_simulator()
    check_yosys()
    offline_ok = check_offline_pipeline()
    live_cfg = check_live_config()
    live_ok = check_live_call() if (args.live and live_cfg) else None
    check_servers()
    check_storage()
    saved_ok = check_evidence()

    print("\nFallback ladder:")
    print(f"  1. live model        : {'READY' if live_ok else ('configured, not tested (use --live)' if live_cfg and live_ok is None else 'NOT READY')}")
    print(f"  2. offline demo      : {'READY' if offline_ok else 'NOT READY'}")
    print(f"  3. saved live results: {'READY' if saved_ok else 'NOT READY'}")
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print(f"\n{len(fails)} failure(s), {len([r for r in RESULTS if r[0] == 'WARN'])} warning(s).")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
