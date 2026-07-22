"""
The agentic pipeline.

    prompt -> parse_intent -> generate_rtl -> generate_testbench -> explain
           -> simulate -> [FAIL/ERROR? fix_design -> re-simulate] (loop) -> done

`pipeline_events` is a generator that yields one event per stage so the API can
stream progress over SSE (this drives the live AI-agent panel). `run_pipeline`
consumes those events and returns a complete RunResponse for the one-shot route.

No-progress guard:
  - Content hashing (not exact string equality) detects identical RTL/TB
    regardless of whitespace changes.
  - Oscillation detection: if an RTL hash we have already seen reappears,
    the loop stops immediately to prevent thrashing.
"""

import hashlib
from typing import Iterator, Optional

import llm_service
from coverage import compute_coverage
from schematic import build_schematic
from simulator import IcarusSimulator
from vcd_parser import parse_vcd
from models import (
    RunResponse, IterationRecord, RTLDesignSpec,
)


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

    # 3. Testbench
    tb_code = llm_service.generate_testbench(rtl_code, spec, model=model)
    yield {"stage": "testbench", "message": "Generated self-checking testbench.", "testbench_code": tb_code}

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

    iteration = 0
    seen_rtl_hashes: set[str] = set()
    seen_rtl_hashes.add(hashlib.sha256(rtl_code.encode()).hexdigest())

    while self_correct and result.status in ("FAIL", "ERROR") and iteration < max_iterations:
        iteration += 1
        yield {"stage": "fixing", "iteration": iteration,
               "message": f"Simulation {result.status}. Diagnosing and patching (attempt {iteration})..."}

        fix = llm_service.fix_design(rtl_code, tb_code, result.log_excerpt, model=model)
        new_rtl, new_tb = fix["rtl_code"], fix["testbench_code"]
        new_rtl_hash = hashlib.sha256(new_rtl.encode()).hexdigest()

        # No-progress guard: no change at all.
        if new_rtl_hash == hashlib.sha256(rtl_code.encode()).hexdigest():
            yield {"stage": "fix", "iteration": iteration,
                   "message": "Model returned no change; stopping the loop.", "fix_summary": "no-op"}
            break

        # Oscillation guard: we have seen this RTL before.
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

        result = simulator.simulate(f"{design_id}", rtl_code, tb_code, timeout=timeout_seconds)
        history.append(IterationRecord(iteration=iteration, status=result.status,
                                        fix_summary=fix["fix_summary"],
                                        fix_type=fix.get("fix_type", ""),
                                        pass_count=result.pass_count, fail_count=result.fail_count,
                                        log_excerpt=result.log_excerpt[-1200:]))
        yield {"stage": "simulate", "iteration": iteration, "status": result.status,
               "message": _sim_message(iteration, result), "result": result.model_dump()}

    # 6. Post-processing artifacts
    result.coverage = compute_coverage(result)
    waveform = parse_vcd(result.waveform_file) if result.waveform_file else None
    schematic = build_schematic(spec)

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
    )
    yield {"stage": "done", "status": result.status,
           "message": _final_message(result, iteration),
           "response": response.model_dump()}


def run_pipeline(prompt: str, design_id: str, simulator: IcarusSimulator, **kwargs) -> RunResponse:
    """Consume the event stream and return the final RunResponse."""
    final = None
    for event in pipeline_events(prompt, design_id, simulator, **kwargs):
        if event["stage"] == "done":
            final = event["response"]
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
