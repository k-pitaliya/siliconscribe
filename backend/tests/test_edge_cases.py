"""Edge-case tests for the orchestrator and offline pipeline."""
import shutil
import pytest

from orchestrator import run_pipeline, pipeline_events
from simulator import IcarusSimulator
import llm_service

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog not installed"
)


@needs_iverilog
def test_empty_prompt_uses_offline_default(tmp_path):
    """An empty prompt should fall back to the counter design (offline default)."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline("", "ec1", sim, max_iterations=1)
    assert resp.status == "PASS"
    assert resp.rtl_spec.module_name == "counter"


@needs_iverilog
def test_max_iterations_zero_skips_self_correct(tmp_path):
    """max_iterations=0 should run simulation but never enter the fix loop."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline(
        "Design a buggy 4-bit counter", "ec2", sim,
        max_iterations=0, self_correct=True,
    )
    assert resp.iterations == 0
    assert len(resp.iteration_history) == 1  # only the initial entry


@needs_iverilog
def test_self_correct_false_skips_loop(tmp_path):
    """self_correct=False should never enter the fix loop."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline(
        "Design a buggy 4-bit counter", "ec3", sim,
        max_iterations=5, self_correct=False,
    )
    assert resp.iterations == 0


@needs_iverilog
def test_prompt_with_extra_whitespace_matches(tmp_path):
    """Leading/trailing whitespace should still match a known design."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline("   Design a 4-bit ALU   ", "ec4", sim, max_iterations=1)
    assert resp.status == "PASS"
    assert resp.rtl_spec.module_name == "alu_4bit"


@needs_iverilog
def test_pipeline_events_yields_all_stages(tmp_path):
    """Every pipeline run must yield start, intent, rtl, testbench, explanation, simulate, done."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    stages = [e["stage"] for e in pipeline_events("Design a counter", "ec5", sim, max_iterations=1)]
    for required in ["start", "intent", "rtl", "testbench", "explanation", "simulate", "done"]:
        assert required in stages, f"Missing stage: {required}"


@needs_iverilog
def test_buggy_counter_passes_after_fix(tmp_path):
    """The self-correction loop must fix the buggy counter to PASS."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline("Design a buggy 4-bit counter", "ec6", sim, max_iterations=3)
    assert resp.status == "PASS"
    assert resp.iterations >= 1
