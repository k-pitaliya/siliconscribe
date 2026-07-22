import shutil
import pytest

from orchestrator import run_pipeline, pipeline_events
from simulator import IcarusSimulator
import llm_service

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


@needs_iverilog
def test_self_correction_uses_offline_scripted_fix(tmp_path):
    """Regression: the offline fix must report fix_type='offline_scripted'."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    resp = run_pipeline("Design a buggy 4-bit counter", "d4", sim, max_iterations=3)
    fix_records = [h for h in resp.iteration_history if h.fix_type]
    assert len(fix_records) >= 1, "Expected at least one fix iteration with fix_type"
    assert fix_records[0].fix_type == "offline_scripted"

    # Verify the fix summary explicitly discloses scripted nature.
    assert "scripted" in fix_records[0].fix_summary.lower() or "known-correct" in fix_records[0].fix_summary.lower()


@needs_iverilog
def test_offline_fallback_disclosure(tmp_path):
    """Regression: an unrecognized prompt must disclose the fallback to the user."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    # This prompt does NOT match any built-in keyword.
    events = list(pipeline_events(
        "Design a UART transmitter with baud rate generator", "d5", sim, max_iterations=1
    ))
    intent_evt = next(e for e in events if e["stage"] == "intent")
    notice = intent_evt.get("fallback_notice")
    assert notice is not None, "fallback_notice must be set for unrecognized prompts"
    assert "counter" in notice.lower() or "representative" in notice.lower()

    # The explanation should also contain the disclosure.
    expl_evt = next(e for e in events if e["stage"] == "explanation")
    assert "offline" in expl_evt["explanation"].lower() or "representative" in expl_evt["explanation"].lower()


@needs_iverilog
def test_exact_match_no_fallback(tmp_path):
    """Regression: a recognized prompt must NOT produce a fallback notice."""
    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(pipeline_events(
        "Design a 4-bit ALU with add sub and or xor", "d6", sim, max_iterations=1
    ))
    intent_evt = next(e for e in events if e["stage"] == "intent")
    assert intent_evt.get("fallback_notice") is None, "Recognized prompt should not have fallback_notice"
