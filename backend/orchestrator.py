"""
The agentic pipeline.

    prompt -> parse_intent -> generate_rtl -> generate_testbench -> explain
           -> simulate -> [FAIL/ERROR? fix_design -> re-simulate] (loop) -> done

`pipeline_events` is a generator that yields one event per stage so the API can
stream progress over SSE (this drives the live AI-agent panel). `run_pipeline`
consumes those events and returns a complete RunResponse for the one-shot route.

A no-progress guard stops the loop if a fix returns code identical to the
previous iteration (prevents burning iterations on a stuck model).
"""

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
    yield {"stage": "intent", "message": f"Identified module '{spec.module_name}' with {len(spec.ports)} ports.",
           "rtl_spec": spec.model_dump()}

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
    while self_correct and result.status in ("FAIL", "ERROR") and iteration < max_iterations:
        iteration += 1
        yield {"stage": "fixing", "iteration": iteration,
               "message": f"Simulation {result.status}. Diagnosing and patching (attempt {iteration})..."}

        fix = llm_service.fix_design(rtl_code, tb_code, result.log_excerpt, model=model)
        new_rtl, new_tb = fix["rtl_code"], fix["testbench_code"]

        if new_rtl == rtl_code and new_tb == tb_code:
            yield {"stage": "fix", "iteration": iteration,
                   "message": "Model returned no change; stopping the loop.", "fix_summary": "no-op"}
            break

        rtl_code, tb_code = new_rtl, new_tb
        yield {"stage": "fix", "iteration": iteration, "message": fix["fix_summary"],
               "fix_summary": fix["fix_summary"], "rtl_code": rtl_code, "testbench_code": tb_code}

        result = simulator.simulate(f"{design_id}", rtl_code, tb_code, timeout=timeout_seconds)
        history.append(IterationRecord(iteration=iteration, status=result.status,
                                       fix_summary=fix["fix_summary"],
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
