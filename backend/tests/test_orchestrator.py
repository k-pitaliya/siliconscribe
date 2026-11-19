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


@needs_iverilog
def test_oscillation_detection_stops_loop(tmp_path):
    """Regression: if the provider alternates between two RTLs the loop must stop."""
    from simulator import IcarusSimulator

    _orig_fix = llm_service.OfflineProvider.fix_design

    _oscillation_state = {"call": 0, "variants": []}

    def _alternating_fix(self, rtl_code, tb_code, log_excerpt, model=None):
        _oscillation_state["call"] += 1
        # Produce two *functionally different* RTLs so whitespace-insensitive hash
        # treats them as distinct. On call 3 we return to the first variant to
        # trigger the oscillation guard (seen hash).
        # Variant A: original buggy RTL + comment A, Variant B: + comment B
        if not _oscillation_state["variants"]:
            # Create two distinct variants from the initial rtl_code
            # Use functional differences (different comments are stripped for hash?
            # No — comments are stripped before hashing, so we need code change)
            # We use different constant increments to ensure distinct hashes.
            v_a = rtl_code.replace("count + 2'd2", "count + 3'd3") if "count + 2'd2" in rtl_code else rtl_code + "\n// variant A\nwire _a = 1'b0;"
            v_b = rtl_code.replace("count + 2'd2", "count + 4'd4") if "count + 2'd2" in rtl_code else rtl_code + "\n// variant B\nwire _b = 1'b0;"
            # Ensure they are functionally distinct even after comment stripping:
            # fallback to adding distinct logic if replace didn't fire
            if v_a == rtl_code:
                v_a = rtl_code.replace("endmodule", "wire _osc_a = 1'b0;\nendmodule")
            if v_b == rtl_code or v_b == v_a:
                v_b = rtl_code.replace("endmodule", "wire _osc_b = 1'b1;\nendmodule")
            _oscillation_state["variants"] = [v_a, v_b]
        # Alternate between variants; on third call return to first (oscillation)
        if _oscillation_state["call"] == 1:
            fixed = _oscillation_state["variants"][0]
        elif _oscillation_state["call"] == 2:
            fixed = _oscillation_state["variants"][1]
        else:
            fixed = _oscillation_state["variants"][0]  # repeat -> oscillation
        return {
            "rtl_code": fixed,
            "testbench_code": tb_code,
            "fix_summary": "oscillation test fix",
            "fix_type": "test",
        }

    llm_service.OfflineProvider.fix_design = _alternating_fix
    try:
        sim = IcarusSimulator(workspace=str(tmp_path))
        events = list(pipeline_events("Design a buggy 4-bit counter", "d7", sim, max_iterations=5))
        # Find the final RunResponse from done stage
        done = next(e for e in events if e["stage"] == "done")
        resp = done["response"]
        # Must NOT have burned all 5 iterations — should have stopped early.
        iterations = resp["iterations"] if isinstance(resp, dict) else resp.iterations
        assert iterations < 5, f"Loop ran {iterations} times; oscillation guard failed"
        # Check that an oscillation or no-op guard fired in the event stream
        fix_events = [e for e in events if e["stage"] == "fix"]
        assert fix_events, "Expected at least one fix event"
        assert any("oscillation" in e.get("fix_summary","").lower() or "oscillation" in e.get("message","").lower() or "no change" in e.get("message","").lower() or "no-op" in e.get("fix_summary","").lower() for e in fix_events), f"Guard message missing in {fix_events}"
    finally:
        llm_service.OfflineProvider.fix_design = _orig_fix


def test_tb_check_count_detects_self_checks():
    from orchestrator import _tb_check_count

    tb = (
        "if (a !== b) fail_count++; else pass_count++;\n"
        "if (c !== d) begin fail_count += 1; $error(\"bad\"); end\n"
        "if (e) $fatal(1, \"fatal\");\n"
        "if (fail_count == 0) $display(\"ALL TESTS PASSED\");\n"
    )
    # fail_count++ / fail_count += / $error / $fatal = 4
    assert _tb_check_count(tb) == 4
    assert _tb_check_count("initial begin $finish; end") == 0


@needs_iverilog
def test_fix_cannot_delete_testbench_checks(tmp_path, monkeypatch):
    """A fix that replaces a failing TB with a check-free one must be rejected."""
    import offline_designs as od

    def _cheating_fix(self, rtl_code, tb_code, log_excerpt, model=None,
                      reasoning_effort=None, spec=None):
        return {
            "rtl_code": od.get_design("counter")["rtl"],  # correct RTL
            "testbench_code": (
                "module testbench;\n"
                "  initial begin\n"
                "    $display(\"Passed: 1\");\n"
                "    $display(\"Failed: 0\");\n"
                "    $display(\"ALL TESTS PASSED\");\n"
                "    $finish;\n"
                "  end\n"
                "endmodule\n"
            ),
            "fix_summary": "cheating fix that removes all checks",
            "fix_type": "test",
        }

    monkeypatch.setattr(llm_service.OfflineProvider, "fix_design", _cheating_fix)
    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(pipeline_events("Design a buggy 4-bit counter", "d8", sim, max_iterations=2))
    fix_events = [e for e in events if e["stage"] == "fix"]
    assert any("Testbench change rejected" in e.get("message", "") for e in fix_events), fix_events
    done = next(e for e in events if e["stage"] == "done")
    resp = done["response"]
    tb_final = resp["testbench_code"] if isinstance(resp, dict) else resp.testbench_code
    assert "fail_count" in tb_final, "Original self-checking TB must be retained"


def test_repair_compile_errors_scopes_wire_to_reg_to_testbench():
    from orchestrator import _repair_compile_errors

    rtl = "module top; endmodule\n"
    tb = ("module testbench;\n"
          "  wire test_valid_w;\n"
          "  initial begin\n"
          "    test_valid_w = 1'b1;\n"
          "  end\n"
          "endmodule\n")
    log = ("Compilation failed:\n"
           "testbench.sv:3: error: test_valid_w is not a valid l-value here\n"
           "  wire test_valid_w;\n"
           "       ^~~~~~~~~~~~\n")
    new_rtl, new_tb, repaired = _repair_compile_errors(rtl, tb, log)
    assert repaired == ["testbench.sv:test_valid_w"]
    assert new_rtl == rtl
    assert "reg test_valid_w;" in new_tb
    assert "wire test_valid_w;" not in new_tb


def test_repair_compile_errors_scopes_wire_to_reg_to_rtl():
    from orchestrator import _repair_compile_errors

    rtl = ("module top(output reg y);\n"
           "  wire state;\n"
           "  always @* state = 1'b1;\n"
           "  assign y = state;\n"
           "endmodule\n")
    tb = "module testbench; top u(); endmodule\n"
    log = ("design.sv:3: error: state is not a valid l-value here\n"
           "  always @* state = 1'b1;\n")
    new_rtl, new_tb, repaired = _repair_compile_errors(rtl, tb, log)
    assert repaired == ["design.sv:state"]
    assert "reg state;" in new_rtl
    assert new_tb == tb


def test_repair_compile_errors_ignores_unrelated_failures():
    from orchestrator import _repair_compile_errors

    rtl = "module top; endmodule\n"
    tb = "module testbench; endmodule\n"
    log = "testbench.sv:3: error: syntax error\n"
    assert _repair_compile_errors(rtl, tb, log) == (rtl, tb, [])


@needs_iverilog
def test_compiler_repair_runs_without_calling_llm(monkeypatch, tmp_path):
    """A wire→reg compile failure is repaired deterministically with a diagnosis."""
    import models

    class _FakeLive:
        name = "fake-live"
        model = "fake-model"

    spec = models.RTLDesignSpec(
        module_name="host",
        ports=[models.PortSpec(name="a", direction="input", width=1),
               models.PortSpec(name="y", direction="output", width=1)],
        behavior="assign y = a",
        constraints=["combinational"],
    )
    rtl = ("module host(input a, output y);\n"
           "  assign y = a;\n"
           "endmodule\n")
    bad_tb = ("module testbench;\n"
              "  reg a; wire y;\n"
              "  wire test_valid_w;\n"
              "  integer pass_count = 0, fail_count = 0;\n"
              "  host dut(.a(a), .y(y));\n"
              "  initial begin\n"
              "    a = 1'b1; test_valid_w = 1'b1;\n"
              "    if (test_valid_w !== 1'b1) fail_count = fail_count + 1;\n"
              "    else pass_count = pass_count + 1;\n"
              "    $display(\"Passed: %0d\", pass_count);\n"
              "    $display(\"Failed: %0d\", fail_count);\n"
              "    $display(\"ALL TESTS PASSED\");\n"
              "    $finish;\n"
              "  end\n"
              "endmodule\n")

    monkeypatch.setattr(llm_service, "get_provider", lambda: _FakeLive())
    monkeypatch.setattr(llm_service, "parse_intent", lambda *a, **k: spec)
    monkeypatch.setattr(llm_service, "generate_rtl", lambda *a, **k: rtl)
    monkeypatch.setattr(llm_service, "generate_testbench", lambda *a, **k: bad_tb)
    monkeypatch.setattr(llm_service, "explain_design", lambda *a, **k: "x")

    def _must_not_call(*a, **k):
        raise AssertionError("fix_design must not be called for a mechanical repair")

    monkeypatch.setattr(llm_service, "fix_design", _must_not_call)

    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(pipeline_events("Design a passthrough", "d10", sim, max_iterations=2))
    repairs = [e for e in events if e.get("fix_type") == "compiler_repair"]
    assert repairs, events
    diag = repairs[0]["diagnosis"]
    assert diag["fix_location"] == "testbench.sv"
    assert "wire" in diag["root_cause"].lower()
    assert "l-value" in diag["symptom"]
    done = next(e for e in events if e["stage"] == "done")
    resp = done["response"]
    status = resp["status"] if isinstance(resp, dict) else resp.status
    assert status == "PASS"


@needs_iverilog
def test_testbench_only_fix_is_applied(monkeypatch, tmp_path):
    """A corrected TB oracle with unchanged RTL must not be discarded as a no-op."""
    import models

    class _FakeLive:
        name = "fake-live"
        model = "fake-model"

    spec = models.RTLDesignSpec(
        module_name="host",
        ports=[models.PortSpec(name="a", direction="input", width=1),
               models.PortSpec(name="y", direction="output", width=1)],
        behavior="assign y = a",
        constraints=["combinational"],
    )
    rtl = ("module host(input a, output y);\n"
           "  assign y = a;\n"
           "endmodule\n")
    bad_tb = ("module testbench;\n"
              "  reg a; wire y;\n"
              "  integer pass_count = 0, fail_count = 0;\n"
              "  host dut(.a(a), .y(y));\n"
              "  initial begin\n"
              "    a = 1'b1; #1;\n"
              "    if (y === 1'b0) pass_count = pass_count + 1;\n"
              "    else fail_count = fail_count + 1;\n"
              "    $display(\"Passed: %0d\", pass_count);\n"
              "    $display(\"Failed: %0d\", fail_count);\n"
              "    if (fail_count == 0) $display(\"ALL TESTS PASSED\");\n"
              "    $finish;\n"
              "  end\n"
              "endmodule\n")
    good_tb = bad_tb.replace("if (y === 1'b0)", "if (y === 1'b1)")

    def _tb_only_fix(rtl_code, tb_code, log_excerpt, model=None,
                     reasoning_effort=None, spec=None):
        assert rtl_code == rtl
        return {
            "rtl_code": rtl,
            "testbench_code": good_tb,
            "fix_summary": "Corrected the testbench oracle.",
            "diagnosis": {"symptom": "1 failed", "root_cause": "oracle inverted",
                          "fix_location": "testbench.sv", "confidence": "high"},
            "fix_type": "test",
        }

    monkeypatch.setattr(llm_service, "get_provider", lambda: _FakeLive())
    monkeypatch.setattr(llm_service, "parse_intent", lambda *a, **k: spec)
    monkeypatch.setattr(llm_service, "generate_rtl", lambda *a, **k: rtl)
    monkeypatch.setattr(llm_service, "generate_testbench", lambda *a, **k: bad_tb)
    monkeypatch.setattr(llm_service, "explain_design", lambda *a, **k: "x")
    monkeypatch.setattr(llm_service, "fix_design", _tb_only_fix)

    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(pipeline_events("Design a passthrough", "d11", sim, max_iterations=2))
    fixes = [e for e in events if e["stage"] == "fix" and e.get("fix_type") == "test"]
    assert fixes, events
    assert fixes[0]["rtl_code"] == rtl
    assert "y === 1'b1" in fixes[0]["testbench_code"]
    done = next(e for e in events if e["stage"] == "done")
    resp = done["response"]
    status = resp["status"] if isinstance(resp, dict) else resp.status
    assert status == "PASS"


def test_midrun_upstream_failure_does_not_swap_design(monkeypatch, tmp_path):
    """Once a live call succeeds, a later outage must fail, not silently offline."""
    import models

    class _FakeLive:
        name = "fake-live"
        model = "fake-model"

    spec = models.RTLDesignSpec(
        module_name="my_design",
        ports=[models.PortSpec(name="a", direction="input", width=1)],
        behavior="pass through",
        constraints=["combinational"],
    )

    monkeypatch.setattr(llm_service, "get_provider", lambda: _FakeLive())
    monkeypatch.setattr(llm_service, "parse_intent", lambda *a, **k: spec)

    def _boom(*a, **k):
        raise RuntimeError("LLM_UPSTREAM:Connection error")

    monkeypatch.setattr(llm_service, "generate_rtl", _boom)
    monkeypatch.setattr(llm_service, "generate_testbench", _boom)
    monkeypatch.setattr(llm_service, "explain_design", lambda *a, **k: "x")

    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(pipeline_events("Design a custom widget", "d9", sim, max_iterations=1))
    error_events = [e for e in events if e["stage"] == "error"]
    assert error_events, events
    assert "became unavailable mid-run" in error_events[0]["message"]
    assert not any(e["stage"] == "done" for e in events)
    # And no silent switch to the curated offline designs.
    assert not any(e.get("fallback_notice") for e in events)


# ------------------------------------------------------------------ self-review QA findings (19 Nov 2026)
@needs_iverilog
def test_a_fix_that_keeps_one_real_check_is_still_rejected_for_dropping_checks(tmp_path, monkeypatch):
    """The older test above is caught by the 'no checks / no DUT' guard first, so the check-COUNT guard had no test."""
    import offline_designs as od
    from tests.test_independent_testbench import TRIVIAL_TB

    def _trimming_fix(self, rtl_code, tb_code, log_excerpt, model=None, reasoning_effort=None, spec=None):
        return {"rtl_code": rtl_code, "testbench_code": TRIVIAL_TB, "fix_summary": "trimmed", "fix_type": "test"}

    monkeypatch.setattr(llm_service.OfflineProvider, "fix_design", _trimming_fix)
    events = list(pipeline_events("Design a buggy 4-bit counter", "d9", IcarusSimulator(workspace=str(tmp_path)), max_iterations=2))
    assert any("removed self-checks" in e.get("message", "") for e in events if e["stage"] == "fix")
    done = next(e for e in events if e["stage"] == "done")["response"]
    assert done["status"] != "PASS" and done["testbench_code"] == od.get_design("counter")["tb"]


@needs_iverilog
def test_a_strict_a_b_a_b_fixer_is_stopped_as_an_oscillation(tmp_path, monkeypatch):
    calls = {"n": 0}

    def _ab(self, rtl_code, tb_code, log_excerpt, model=None, reasoning_effort=None, spec=None):
        calls["n"] += 1
        tag = "a" if calls["n"] % 2 else "b"
        base = rtl_code.split("\nwire _osc_")[0].replace("\nendmodule", "")
        return {"rtl_code": base + f"\nwire _osc_{tag} = 1'b0;\nendmodule\n", "testbench_code": tb_code, "fix_summary": tag,
                "fix_type": "rtl"}

    monkeypatch.setattr(llm_service.OfflineProvider, "fix_design", _ab)
    events = list(pipeline_events("Design a buggy 4-bit counter", "d10", IcarusSimulator(workspace=str(tmp_path)), max_iterations=6))
    assert any(e.get("fix_summary") == "oscillation" for e in events if e["stage"] == "fix")
    assert calls["n"] < 6
