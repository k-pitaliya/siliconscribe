import shutil
import pytest

from orchestrator import run_pipeline, pipeline_events
from simulator import IcarusSimulator

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog not installed"
)


@needs_iverilog
def test_clean_design_passes_first_try(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline("Design a 4-bit ALU with add sub and or xor", "d1", sim, max_iterations=3)
    assert resp.status == "PASS"
    assert resp.iterations == 0
    assert resp.waveform is not None and len(resp.waveform.signals) > 0
    assert resp.schematic is not None and resp.schematic.module_name == "alu_4bit"
    assert resp.result.coverage["pass_rate"] == 100.0


@needs_iverilog
def test_self_correction_loop_fixes_buggy_design(tmp_path):
    """The differentiator: a buggy design must be auto-fixed to PASS."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline("Design a buggy 4-bit counter", "d2", sim, max_iterations=3)
    assert resp.status == "PASS"          # loop reached a passing state
    assert resp.iterations >= 1            # at least one fix was applied
    assert len(resp.iteration_history) >= 2
    assert resp.iteration_history[0].status in ("FAIL", "ERROR")
    assert resp.iteration_history[-1].status == "PASS"


@needs_iverilog
def test_stream_emits_expected_stages(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    stages = [e["stage"] for e in pipeline_events("Design a 4:1 mux", "d3", sim, max_iterations=2)]
    for expected in ["start", "intent", "rtl", "testbench", "explanation", "simulate", "done"]:
        assert expected in stages
