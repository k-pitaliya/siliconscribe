"""
The agentic pipeline.

    prompt -> parse_intent -> generate_rtl -> generate_testbench -> explain
           -> [lint] -> simulate -> [FAIL/ERROR? fix_design -> lint -> re-simulate] (loop) -> done

`pipeline_events` is a generator that yields one event per stage so the API can
stream progress over SSE (this drives the live AI-agent panel). `run_pipeline`
consumes those events and returns a complete RunResponse for the one-shot route.

No-progress guard:
  - Content hashing (not exact string equality) detects identical RTL/TB
    regardless of whitespace changes.
  - Oscillation detection: if an RTL hash we have already seen reappears,
    the loop stops immediately to prevent thrashing.

Linter integration (non-blocking):
  - Before each simulation, VerilogLinter is run on the current RTL+TB.
  - If lint finds errors/warnings, a ``stage="lint"`` event is yielded so the
    agent panel can surface diagnostics.
  - Lint never blocks the pipeline; simulation still runs so the
    self-correction loop can fix issues.
"""

import hashlib
from pathlib import Path
from typing import Iterator, Optional

import llm_service
from coverage import compute_coverage
from schematic import build_schematic
from simulator import IcarusSimulator
from vcd_parser import parse_vcd
from models import (
    RunResponse, IterationRecord, RTLDesignSpec,
)

# Optional synthesis — must not break import when yosys not installed
try:
    from synthesis import YosysSynthesizer  # type: ignore
except Exception:  # pragma: no cover
    YosysSynthesizer = None  # type: ignore

# Optional linter — must not break import when tool chain is absent
try:
    from linter import VerilogLinter  # type: ignore
except Exception:  # pragma: no cover
    VerilogLinter = None  # type: ignore


def _lint_payload(lint_res: dict) -> dict:
    """Convert VerilogLinter result (with SimError objects) to JSON-serialisable payload."""
    def _dump(e):
        # SimError is a pydantic model; be defensive for plain dicts
        if hasattr(e, "model_dump"):
            return e.model_dump()
        if isinstance(e, dict):
            return e
        return {"message": str(e)}
    return {
        "ok": lint_res.get("ok", True),
        "errors": [_dump(e) for e in lint_res.get("errors", [])],
        "warnings": [_dump(w) for w in lint_res.get("warnings", [])],
        "output": lint_res.get("output", ""),
    }


def pipeline_events(
    prompt: str,
    design_id: str,
    simulator: IcarusSimulator,
    target_frequency_mhz: Optional[int] = None,
    self_correct: bool = True,
    max_iterations: int = 3,
    timeout_seconds: int = 30,
    model: Optional[str] = None,
) -> Iterator[dict]:
    """Yield {stage, ...} events as the pipeline runs."""
    model_label = model or "default"
    yield {"stage": "start",
           "message": f"Parsing requirement (provider: {llm_service.get_provider().name}, model: {model_label})..."}

    try:
        # 1. Intent
        spec: RTLDesignSpec = llm_service.parse_intent(prompt, model=model)

        # Check for offline fallback disclosure
        fallback_notice = None
        provider = llm_service.get_provider()
        if hasattr(provider, "_last_exact") and not provider._last_exact:
            fallback_notice = (
                "Your request did not match a built-in offline design. "
                "Showing a representative counter design as a demo."
            )

        yield {"stage": "intent", "message": f"Identified module '{spec.module_name}' with {len(spec.ports)} ports.",
               "rtl_spec": spec.model_dump(), "fallback_notice": fallback_notice}

        # 2. RTL
        rtl_code = llm_service.generate_rtl(spec, target_frequency_mhz, model=model)
        yield {"stage": "rtl", "message": "Generated RTL.", "rtl_code": rtl_code}

        # Lint RTL alone (non-blocking, informational)
        if VerilogLinter is not None:
            try:
                linter = VerilogLinter()
                lint_res = linter.lint(rtl_code)
                if lint_res.get("errors") or lint_res.get("warnings"):
                    payload = _lint_payload(lint_res)
                    yield {
                        "stage": "lint",
                        "target": "rtl",
                        "message": f"Lint RTL: {len(payload['errors'])} error(s), {len(payload['warnings'])} warning(s)",
                        "lint": payload,
                    }
            except Exception:
                pass  # linter must never break the pipeline

        # 3. Testbench
        tb_code = llm_service.generate_testbench(rtl_code, spec, model=model)
        yield {"stage": "testbench", "message": "Generated self-checking testbench.", "testbench_code": tb_code}

        # Lint combined RTL + TB before simulation (non-blocking)
        if VerilogLinter is not None:
            try:
                linter = VerilogLinter()
                lint_res = linter.lint(rtl_code, tb_code)
                if lint_res.get("errors") or lint_res.get("warnings"):
                    payload = _lint_payload(lint_res)
                    yield {
                        "stage": "lint",
                        "target": "tb",
                        "message": f"Lint TB: {len(payload['errors'])} error(s), {len(payload['warnings'])} warning(s)",
                        "lint": payload,
                    }
            except Exception:
                pass

        # 4. Explanation
        explanation = llm_service.explain_design(rtl_code, spec, model=model)
        yield {"stage": "explanation", "message": explanation, "explanation": explanation}

        # 5. Simulate + self-correct
        history: list[IterationRecord] = []
        result = simulator.simulate(design_id, rtl_code, tb_code, timeout=timeout_seconds)
        history.append(IterationRecord(iteration=0, status=result.status, fix_summary="initial",
                                       pass_count=result.pass_count, fail_count=result.fail_count,
                                       log_excerpt=result.log_excerpt[-1200:]))
        yield {"stage": "simulate", "iteration": 0, "status": result.status,
               "message": _sim_message(0, result), "result": result.model_dump()}

        def _norm_hash(code: str) -> str:
            # Whitespace-insensitive hash as promised in the module docstring:
            # strip all whitespace + comments so trivial formatting changes are identical.
            # IMPORTANT: strip comments BEFORE whitespace, otherwise "//.*"
            # after whitespace removal would match from "//" to end-of-file and wipe the hash.
            import re as _re
            norm = _re.sub(r"//.*", "", code)
            norm = _re.sub(r"/\*.*?\*/", "", norm, flags=_re.DOTALL)
            norm = _re.sub(r"\s+", "", norm)
            return hashlib.sha256(norm.encode()).hexdigest()

        iteration = 0
        seen_rtl_hashes: set[str] = set()
        seen_rtl_hashes.add(_norm_hash(rtl_code))

        while self_correct and result.status in ("FAIL", "ERROR") and iteration < max_iterations:
            iteration += 1
            yield {"stage": "fixing", "iteration": iteration,
                   "message": f"Simulation {result.status}. Diagnosing and patching (attempt {iteration})..."}

            fix = llm_service.fix_design(rtl_code, tb_code, result.log_excerpt, model=model)
            new_rtl, new_tb = fix["rtl_code"], fix["testbench_code"]
            new_rtl_hash = _norm_hash(new_rtl)
            cur_hash = _norm_hash(rtl_code)

            # No-progress guard: no change at all (whitespace-insensitive).
            if new_rtl_hash == cur_hash:
                yield {"stage": "fix", "iteration": iteration,
                       "message": "Model returned no change; stopping the loop.", "fix_summary": "no-op"}
                break

            # Oscillation guard: we have seen this RTL before (whitespace-insensitive).
            if new_rtl_hash in seen_rtl_hashes:
                yield {"stage": "fix", "iteration": iteration,
                       "message": "Oscillation detected (repeated RTL); stopping the loop.",
                       "fix_summary": "oscillation"}
                break

            seen_rtl_hashes.add(new_rtl_hash)
            rtl_code, tb_code = new_rtl, new_tb
            yield {"stage": "fix", "iteration": iteration, "message": fix["fix_summary"],
                   "fix_summary": fix["fix_summary"], "fix_type": fix.get("fix_type", ""),
                   "rtl_code": rtl_code, "testbench_code": tb_code}

            # Lint the fixed design before re-simulating (non-blocking)
            if VerilogLinter is not None:
                try:
                    linter = VerilogLinter()
                    lint_res = linter.lint(rtl_code, tb_code)
                    if lint_res.get("errors") or lint_res.get("warnings"):
                        payload = _lint_payload(lint_res)
                        yield {
                            "stage": "lint",
                            "target": "fix",
                            "iteration": iteration,
                            "message": f"Lint fix #{iteration}: {len(payload['errors'])} error(s), {len(payload['warnings'])} warning(s)",
                            "lint": payload,
                        }
                except Exception:
                    pass

            result = simulator.simulate(f"{design_id}", rtl_code, tb_code, timeout=timeout_seconds)
            history.append(IterationRecord(iteration=iteration, status=result.status,
                                           fix_summary=fix["fix_summary"],
                                           fix_type=fix.get("fix_type", ""),
                                           pass_count=result.pass_count, fail_count=result.fail_count,
                                           log_excerpt=result.log_excerpt[-1200:]))
            yield {"stage": "simulate", "iteration": iteration, "status": result.status,
                   "message": _sim_message(iteration, result), "result": result.model_dump()}

        # 6. Post-processing artifacts
        # Pass explicit log to compute_coverage so toggle/branch parsing sees full transcript
        result.coverage = compute_coverage(result, log=result.log_excerpt or "")
        waveform = parse_vcd(result.waveform_file) if result.waveform_file else None
        schematic = build_schematic(spec)

        # 7. Synthesis (yosys) — graceful fallback to port-level schematic
        synthesis: Optional[dict] = None
        if YosysSynthesizer is not None:
            try:
                synth_workdir = Path(simulator.workspace) / design_id / "synth"
                synthesizer = YosysSynthesizer(workspace=str(simulator.workspace))
                synthesis = synthesizer.synthesize(rtl_code, spec.module_name, work_dir=synth_workdir)
                if synthesis.get("available"):
                    if "cell_count" in synthesis:
                        msg = f"Synthesis: {synthesis['cell_count']} cells, ~{synthesis.get('area_estimate', '?')} um² (yosys)"
                    elif synthesis.get("error"):
                        msg = f"Synthesis warning: {str(synthesis['error'])[:120]}"
                    else:
                        msg = "Synthesis completed (yosys available)"
                else:
                    msg = "Synthesis not available (yosys not installed — showing port-level schematic)"
                yield {"stage": "synthesis", "synthesis": synthesis, "message": msg}
            except Exception as e:
                synthesis = {"available": False, "error": str(e)}
                try:
                    yield {"stage": "synthesis", "synthesis": synthesis, "message": "Synthesis fallback (port-level schematic)"}
                except Exception:
                    pass
        else:
            synthesis = {"available": False}
            try:
                yield {"stage": "synthesis", "synthesis": synthesis, "message": "Synthesis not available (yosys not installed — showing port-level schematic)"}
            except Exception:
                pass

        response = RunResponse(
            design_id=design_id,
            rtl_spec=spec,
            rtl_code=rtl_code,
            testbench_code=tb_code,
            explanation=explanation,
            status=result.status,
            result=result,
            iterations=iteration,
            iteration_history=history,
            waveform=waveform,
            schematic=schematic,
            synthesis=synthesis,
        )
        yield {"stage": "done", "status": result.status,
               "message": _final_message(result, iteration),
               "response": response.model_dump()}
    except Exception:
        import logging
        logging.getLogger("siliconscribe.orchestrator").exception("pipeline failed")
        # Never throw to SSE stream; yield a terminal error stage so frontend can handle gracefully
        yield {"stage": "error", "message": "Internal server error"}


def run_pipeline(prompt: str, design_id: str, simulator: IcarusSimulator, **kwargs) -> RunResponse:
    """Consume the event stream and return the final RunResponse."""
    final = None
    for event in pipeline_events(prompt, design_id, simulator, **kwargs):
        if event["stage"] == "done":
            final = event["response"]
        elif event["stage"] == "error":
            # Surface as exception for non-stream callers; preserves 500 generic contract in API layer
            raise RuntimeError(event.get("message", "Internal server error"))
    if final is None:
        raise RuntimeError("Pipeline did not produce a final response")
    return RunResponse(**final)


def _sim_message(iteration: int, result) -> str:
    if result.status == "PASS":
        return f"Simulation passed: {result.pass_count}/{result.test_count} tests."
    if result.status == "FAIL":
        return f"Simulation failed: {result.fail_count} of {result.test_count} tests failed."
    if result.status == "TIMEOUT":
        return "Simulation timed out."
    return "Simulation error (compile or runtime)."


def _final_message(result, iterations: int) -> str:
    if result.status == "PASS":
        if iterations:
            return f"Design passes after {iterations} self-correction iteration(s)."
        return "Design passes on the first attempt."
    return f"Could not reach a passing state after {iterations} iteration(s) ({result.status})."
