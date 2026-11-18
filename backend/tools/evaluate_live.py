#!/usr/bin/env python3
"""Measured live evaluation: run a fixed prompt set through the real pipeline and record the facts.

    cd backend
    PATH="$HOME/.local/bin:$PATH" env -u OFFLINE_MODE LLM_PROVIDER=opencode-app \\
        LLM_MODEL=deepseek-v4.1-flash-free python3 tools/evaluate_live.py            # run what is missing
    python3 tools/evaluate_live.py --only c1,s1                                       # a subset
    python3 tools/evaluate_live.py --summary                                          # just rebuild summary.md

Design rules (so the numbers can be trusted and a free-tier cut-off loses nothing):
  * one JSON line per finished prompt is appended to evaluation/results.jsonl IMMEDIATELY;
  * re-running skips prompts that already have a finished record (resume), unless --redo;
  * an upstream outage or quota error stops the run (it is not recorded as a design failure);
  * a run that silently fell back to the scripted offline demo is recorded as `fallback` and is
    NOT counted as evidence about the model;
  * it calls the pipeline directly, so it never writes to the projects database.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
sys.path.insert(0, str(BACKEND))

OUT_DIR = BACKEND / "evaluation"
RESULTS = OUT_DIR / "results.jsonl"
SUMMARY = OUT_DIR / "summary.md"
ARTIFACTS = OUT_DIR / "artifacts"

# (id, category, prompt). Spread over combinational, sequential and FSM designs, easy to moderate.
PROMPTS = [
    ("c1", "combinational", "Design an 8-to-3 priority encoder with a valid output"),
    ("c2", "combinational", "Design a 4-bit binary to Gray code converter"),
    ("c3", "combinational", "Design a 4-bit ripple-carry adder with carry-in and carry-out"),
    ("c4", "combinational", "Design a 4:1 multiplexer with 8-bit data paths"),
    ("c5", "combinational", "Design a 3-to-8 decoder with an enable input"),
    ("c6", "combinational", "Design a 4-bit magnitude comparator with greater, equal and less outputs"),
    ("c7", "combinational", "Design a 4-bit ALU with add, sub, and, or, xor and overflow detection"),
    ("s1", "sequential", "Design a 4-bit synchronous up-counter with async reset and enable"),
    ("s2", "sequential", "Design an 8-bit loadable up/down counter with synchronous reset"),
    ("s3", "sequential", "Design a 4-bit universal shift register with hold, shift left, shift right and parallel load"),
    ("s4", "sequential", "Design a serial-in parallel-out 8-bit shift register with synchronous reset"),
    ("s5", "sequential", "Design a clock divider that divides the input clock by 4 with an asynchronous reset"),
    ("s6", "sequential", "Design a synchronous FIFO with 8-bit data and depth 4 with full and empty flags"),
    ("f1", "fsm", "Design a Moore FSM that detects the serial bit sequence 1011 with overlapping allowed"),
    ("f2", "fsm", "Design a traffic light controller FSM with red, green and yellow states and a synchronous reset"),
]


def load_done() -> dict:
    done = {}
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                done[rec["id"]] = rec          # the last record for an id wins
    return done


def run_one(pid: str, category: str, prompt: str) -> dict:
    import llm_service
    from orchestrator import run_pipeline
    from simulator import IcarusSimulator

    sim = IcarusSimulator(workspace=tempfile.mkdtemp(prefix="eval_"))
    started = time.time()
    resp = run_pipeline(prompt, f"ev{pid}", sim, self_correct=True, max_iterations=4, timeout_seconds=30)
    d = resp.model_dump()
    res = d["result"] or {}
    strength = d.get("strength") or {}
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / f"{pid}_design.sv").write_text(d["rtl_code"])
    (ARTIFACTS / f"{pid}_testbench.sv").write_text(d["testbench_code"])
    return {
        "id": pid, "category": category, "prompt": prompt,
        "status": d["status"], "repairs": d["iterations"], "seconds": round(time.time() - started, 1),
        "module": d["rtl_spec"]["module_name"],
        "checks_passed": res.get("pass_count"), "checks_total": res.get("test_count"),
        "checks_source": res.get("checks_source"),
        "test_types": [[g["category"], g["passed"], g["total"]] for g in (res.get("check_groups") or [])],
        "strength_killed": strength.get("killed"), "strength_total": strength.get("total"),
        "strength_survivors": [s["description"] for s in strength.get("survivors", [])],
        "toggle_percent": (res.get("measured_toggle") or {}).get("percent"),
        "timing_met": (d.get("timing") or {}).get("met"),
        "timing_fmax_mhz": (d.get("timing") or {}).get("fmax_mhz"),
        "area_um2": (d.get("timing") or {}).get("area_um2"),
        "warning": d.get("verification_warning"),
        "fallback": bool(d.get("fallback_notice")),
        "provider": getattr(llm_service.get_provider(), "name", "?"),
        "model": llm_service.current_model(),
        "testbench_model": (getattr(llm_service.get_provider(), "stage_models", {}) or {}).get("testbench") or None,
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def backfill() -> int:
    """Add toggle coverage, timing and area to records saved before those measurements existed.

    Uses only the saved design and testbench (no model call): re-simulates them and times the design.
    A record is only updated when the re-simulation reproduces its saved verdict.
    """
    from simulator import IcarusSimulator
    from timing import run_timing
    sim = IcarusSimulator(workspace=tempfile.mkdtemp(prefix="evalbf_"))
    done, changed = load_done(), 0
    for pid, rec in done.items():
        design, tb = ARTIFACTS / f"{pid}_design.sv", ARTIFACTS / f"{pid}_testbench.sv"
        if rec.get("toggle_percent") is not None or not (design.exists() and tb.exists()):
            continue
        res = sim.simulate(f"bf{pid}", design.read_text(), tb.read_text(), timeout=60)
        if res.status != rec["status"] or res.test_count != rec["checks_total"]:
            print(f"  {pid}: re-simulation gave {res.status} {res.pass_count}/{res.test_count}, record says "
                  f"{rec['status']} {rec['checks_passed']}/{rec['checks_total']}: left unchanged")
            continue
        rec["toggle_percent"] = res.measured_toggle.percent if res.measured_toggle else None
        if rec["status"] == "PASS":
            tm = run_timing(design.read_text(), rec["module"], Path(tempfile.mkdtemp(prefix="evalti_")), 100,
                            testbench_code=tb.read_text())
            rec.update(timing_met=tm.met, timing_fmax_mhz=tm.fmax_mhz, area_um2=tm.area_um2)
        rec["backfilled"] = True
        changed += 1
        print(f"  {pid}: toggle {rec['toggle_percent']}%, max {rec.get('timing_fmax_mhz')} MHz, {rec.get('area_um2')} um2")
    if changed:
        RESULTS.write_text("".join(json.dumps(r) + "\n" for r in done.values()))
    return changed


def retime() -> int:
    """Recompute timing and area for every saved PASS design with the CURRENT timing code (no model call).

    Needed when the timing estimate itself changes: the saved numbers must come from the code that ships.
    Returns how many records changed; running it again changes none."""
    from timing import run_timing
    done, changed = load_done(), 0
    for pid, rec in done.items():
        design, tb = ARTIFACTS / f"{pid}_design.sv", ARTIFACTS / f"{pid}_testbench.sv"
        if rec.get("status") != "PASS" or not (design.exists() and tb.exists()):
            continue
        tm = run_timing(design.read_text(), rec["module"], Path(tempfile.mkdtemp(prefix="evalrt_")), 100,
                        testbench_code=tb.read_text())
        new = {"timing_met": tm.met, "timing_fmax_mhz": tm.fmax_mhz, "area_um2": tm.area_um2,
               "timing_error": tm.error if tm.slack_ns is None else None}
        if any(rec.get(k) != v for k, v in new.items()):
            rec.update(new)
            changed += 1
            print(f"  {pid}: max {tm.fmax_mhz} MHz, {tm.area_um2} um2" + (f" (not timed: {tm.error})" if tm.slack_ns is None else ""))
    if changed:
        RESULTS.write_text("".join(json.dumps(r) + "\n" for r in done.values()))
    return changed


def _cell(value, suffix: str = "") -> str:
    """A table cell: '-' for results recorded before this measurement existed."""
    return "-" if value is None else f"{value:g}{suffix}"


def summarise() -> str:
    order = {p[0]: i for i, p in enumerate(PROMPTS)}
    recs = sorted(load_done().values(), key=lambda r: order.get(r["id"], 99))
    if not recs:
        return "No results yet.\n"
    missing = [p[0] for p in PROMPTS if p[0] not in {r["id"] for r in recs}]
    evidence = [r for r in recs if not r["fallback"]]
    first = [r for r in evidence if r["status"] == "PASS" and r["repairs"] == 0]
    repaired = [r for r in evidence if r["status"] == "PASS" and r["repairs"] > 0]
    failed = [r for r in evidence if r["status"] != "PASS"]
    times = [r["seconds"] for r in evidence]
    models = sorted({"%s / %s" % (r["provider"], r["model"]) for r in recs})
    tb_models = sorted({str(r["testbench_model"] or "same as design") for r in recs})
    lines = [
        "# Live evaluation", "",
        "Provider/model: " + ", ".join(models),
        "Testbench model: " + ", ".join(tb_models), "",
        f"- Prompts run: **{len(recs)}** ({len(recs) - len(evidence)} fell back to the offline demo and are not counted)",
        *([f"- No result yet for: **{', '.join(missing)}** (not run, or the model did not answer in time on every attempt; "
           "never counted as a pass or as a design failure)"] if missing else []),
        f"- PASS on the first attempt: **{len(first)}** of {len(evidence)}",
        f"- PASS after self-repair: **{len(repaired)}** of {len(evidence)}",
        f"- Not PASS: **{len(failed)}** of {len(evidence)}",
        f"- Median time per run: **{statistics.median(times):.0f} s**" if times else "- Median time: n/a", "",
        "| id | type | verdict | repairs | checks | strength | toggle | max MHz | area um2 | time | notes |", "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        strength = f"{r['strength_killed']}/{r['strength_total']}" if r.get("strength_total") else "-"
        notes = []
        if r["fallback"]:
            notes.append("offline fallback")
        w = r.get("warning") or ""
        if "ORIGINAL testbench" in w:
            notes.append("testbench changed during repair")
        if "Weak testbench" in w:
            notes.append("weak testbench")
        if "Weak evidence" in w:
            notes.append("few executed checks")
        if r.get("strength_survivors"):
            notes.append(f"{len(r['strength_survivors'])} bug(s) missed")
        lines.append(f"| {r['id']} | {r['category']} | {r['status']} | {r['repairs']} | "
                     f"{r['checks_passed']}/{r['checks_total']} | {strength} | {_cell(r.get('toggle_percent'), '%')} | "
                     f"{_cell(r.get('timing_fmax_mhz'))} | {_cell(r.get('area_um2'))} | {r['seconds']:.0f} s | {'; '.join(notes)} |")
    lines += ["", "Strength = injected bugs caught / injected bugs run (mutation testing of the design's own testbench; "
              "survivors may be equivalent mutants). Toggle = measured toggle coverage of design signals. "
              "Max MHz and area = pre-layout estimate on sky130 (typical corner, no wire delay, not sign-off). Raw records: `evaluation/results.jsonl`; designs and testbenches: "
              "`evaluation/artifacts/`.", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated prompt ids")
    ap.add_argument("--redo", action="store_true", help="run again even if a record exists")
    ap.add_argument("--summary", action="store_true", help="only rebuild summary.md")
    ap.add_argument("--backfill", action="store_true", help="add toggle/timing to older records from saved artifacts (no model call)")
    ap.add_argument("--retime", action="store_true", help="recompute timing/area of saved PASS designs with the current timing code (no model call)")
    args = ap.parse_args()
    OUT_DIR.mkdir(exist_ok=True)

    if args.retime:
        print(f"retimed {retime()} record(s)")
    elif args.backfill:
        print(f"backfilled {backfill()} record(s)")
    elif not args.summary:
        import llm_service
        if llm_service.is_offline():
            print("Refusing to run: the provider is offline (scripted demo), which would measure nothing.")
            return 2
        wanted = set(args.only.split(",")) if args.only else None
        done = load_done()
        todo = [p for p in PROMPTS if (wanted is None or p[0] in wanted) and (args.redo or p[0] not in done)]
        print(f"provider={getattr(llm_service.get_provider(), 'name', '?')} model={llm_service.current_model()} "
              f"to run: {[p[0] for p in todo]}", flush=True)
        for pid, category, prompt in todo:
            print(f"[{pid}] {prompt}", flush=True)
            try:
                rec = run_one(pid, category, prompt)
            except Exception as e:  # upstream outage / quota: stop, keep what is finished
                print(f"  STOP: {type(e).__name__}: {str(e)[:200]}", flush=True)
                print("  (not recorded as a design failure; re-run later to resume)", flush=True)
                break
            with RESULTS.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"  -> {rec['status']} repairs={rec['repairs']} checks={rec['checks_passed']}/{rec['checks_total']} "
                  f"strength={rec['strength_killed']}/{rec['strength_total']} {rec['seconds']}s"
                  f"{' FALLBACK' if rec['fallback'] else ''}", flush=True)
    SUMMARY.write_text(summarise())
    print(f"summary written to {SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
