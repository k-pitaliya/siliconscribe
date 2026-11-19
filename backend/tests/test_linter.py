"""Tests for VerilogLinter (offline, no external tool required)."""
import sys
from pathlib import Path

# Ensure backend is on path (conftest already does, but be defensive)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from linter import VerilogLinter, _parse_tool_output
import offline_designs as od
from cov_metrics import compute_coverage
from models import SimulationResult


def test_linter_importable_without_tool():
    # Must be importable even when verilator/iverilog absent
    linter = VerilogLinter()
    assert hasattr(linter, "lint")


def test_linter_clean_offline_designs_have_no_warnings():
    linter = VerilogLinter()
    for key in ["counter", "alu", "adder", "mux"]:
        d = od.get_design(key)
        res = linter.lint(d["rtl"], d["tb"])
        # Heuristic fallback should be clean for curated offline designs
        assert res["ok"] is True
        assert res["errors"] == []
        # After heuristic tuning, warnings should be 0 for clean designs
        assert res["warnings"] == [], f"{key} unexpectedly had warnings: {res['warnings']}"


def test_linter_missing_semicolon_heuristic():
    linter = VerilogLinter()
    bad = "module foo;\n  assign b = a\nendmodule"
    res = linter.lint(bad)
    # Whether or not an external tool is present, a missing semicolon is a real
    # compile error and must never be reported as clean. The heuristic now
    # classifies it as an error (previously a warning, which let ok=True slip
    # through when no tool was installed).
    assert res["ok"] is False
    assert len(res["errors"]) >= 1
    assert any("missing semicolon" in e.message.lower() for e in res["errors"])


def test_linter_duplicate_module():
    linter = VerilogLinter()
    dup = "module foo; endmodule\nmodule foo; endmodule"
    res = linter.lint(dup)
    # Duplicate module definitions cannot compile: ok must be False whether the
    # finding came from iverilog/verilator or from the heuristic fallback.
    assert res["ok"] is False
    assert any("duplicate" in e.message.lower() for e in res["errors"])


def test_linter_module_endmodule_mismatch():
    linter = VerilogLinter()
    res = linter.lint("module foo; ")
    assert res["ok"] is False
    assert any("mismatch" in e.message.lower() for e in res["errors"])


def test_linter_parse_iverilog_output():
    out = "design.sv:10: error: syntax error\ntest.sv:5: warning: implicit wire"
    errs, warns = _parse_tool_output(out)
    assert len(errs) == 1 and errs[0].line == 10
    assert len(warns) == 1 and warns[0].line == 5


def test_linter_parse_verilator_output():
    out = "%Error: design.sv:8: syntax error\n%Warning-WIDTH: test.sv:12: width mismatch"
    errs, warns = _parse_tool_output(out)
    assert len(errs) == 1
    assert len(warns) == 1


def test_linter_returns_expected_shape():
    linter = VerilogLinter()
    res = linter.lint("module foo; endmodule")
    assert set(res.keys()) == {"ok", "errors", "warnings", "output"}
    assert isinstance(res["ok"], bool)
    assert isinstance(res["errors"], list)
    assert isinstance(res["warnings"], list)
    assert isinstance(res["output"], str)


def test_coverage_toggle_branch_parsing():
    sr = SimulationResult(status="PASS", module_name="x", test_count=10, pass_count=8, fail_count=2,
                          log_excerpt="Toggle coverage: 85%\nBranch coverage: 72.5%")
    cov = compute_coverage(sr)
    assert cov["toggle_coverage"] == 85.0
    assert cov["branch_coverage"] == 72.5
    # backward compat
    assert cov["test_vectors"] == 10
    assert cov["pass_rate"] == 80.0


def test_coverage_backward_compat_no_toggle():
    sr = SimulationResult(status="PASS", module_name="x", test_count=4, pass_count=4, fail_count=0,
                          log_excerpt="Passed: 4\nFailed: 0\nCOV: foo 10")
    cov = compute_coverage(sr)
    assert "toggle_coverage" not in cov
    assert cov["bins"]["foo"] == 10


def test_linter_empty_input():
    linter = VerilogLinter()
    res = linter.lint("")
    # Empty source is not "clean" — a failed generation must be visible.
    assert res["ok"] is False
    assert res["errors"]


def test_numbers_in_comments_are_not_treated_as_assignments():
    rtl = "module m(input wire [3:0] a, output wire [3:0] y);\n    // keep names <= 24 chars, width = 32;\n    assign y = a;\nendmodule\n"
    res = VerilogLinter().lint(rtl)
    assert not any("exceeds" in w.message for w in res["warnings"]), res["warnings"]


def test_lint_refuses_source_the_sandbox_would_refuse_before_any_compiler_runs():
    """`include would make a compiler echo a local file in its diagnostics."""
    rtl = 'module m(output y);\n`include "/etc/passwd"\nassign y = 1\'b0;\nendmodule\n'
    res = VerilogLinter().lint(rtl)
    assert res["ok"] is False
    assert "include" in res["errors"][0].message
    assert res["output"] == "rejected by the sandbox policy before linting"
    assert "root:" not in str(res)
