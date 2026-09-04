"""Tests for VerilogLinter (offline, no external tool required)."""
import pytest
import sys
from pathlib import Path

# Ensure backend is on path (conftest already does, but be defensive)
import os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from linter import VerilogLinter, _parse_tool_output
from models import SimError
import offline_designs as od
from coverage import compute_coverage
from models import SimulationResult


def test_linter_importable_without_tool():
    # Must be importable even when verilator/iverilog absent
    l = VerilogLinter()
    assert hasattr(l, "lint")


def test_linter_clean_offline_designs_have_no_warnings():
    l = VerilogLinter()
    for key in ["counter", "alu", "adder", "mux"]:
        d = od.get_design(key)
        res = l.lint(d["rtl"], d["tb"])
        # Heuristic fallback should be clean for curated offline designs
        assert res["ok"] is True
        assert res["errors"] == []
        # After heuristic tuning, warnings should be 0 for clean designs
        assert res["warnings"] == [], f"{key} unexpectedly had warnings: {res['warnings']}"


def test_linter_missing_semicolon_heuristic():
    import shutil
    l = VerilogLinter()
    bad = "module foo;\n  assign b = a\nendmodule"
    res = l.lint(bad)
    # When iverilog is present the tool reports a syntax error (ok=False);
    # heuristic still surfaces the missing-semicolon warning.
    if shutil.which("iverilog") or shutil.which("verilator"):
        assert len(res["warnings"]) >= 1
        assert any("missing semicolon" in w.message.lower() for w in res["warnings"])
        # tool will flag a real compile error
        assert res["ok"] is False
        assert len(res["errors"]) >= 1
    else:
        # Fallback mode: ok True with warnings (per spec)
        assert res["ok"] is True
        assert len(res["warnings"]) >= 1
        assert any("missing semicolon" in w.message.lower() for w in res["warnings"])


def test_linter_duplicate_module():
    import shutil
    l = VerilogLinter()
    dup = "module foo; endmodule\nmodule foo; endmodule"
    res = l.lint(dup)
    if shutil.which("iverilog") or shutil.which("verilator"):
        # tool reports duplicate as error, heuristic still surfaces warning
        assert any("duplicate" in w.message.lower() for w in res["warnings"])
        assert res["ok"] is False
    else:
        assert res["ok"] is True
        assert any("duplicate" in w.message.lower() for w in res["warnings"])


def test_linter_module_endmodule_mismatch():
    l = VerilogLinter()
    res = l.lint("module foo; ")
    assert any("mismatch" in w.message.lower() for w in res["warnings"])


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
    l = VerilogLinter()
    res = l.lint("module foo; endmodule")
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
    l = VerilogLinter()
    res = l.lint("")
    assert res["ok"] is True
    assert res["errors"] == []
    assert res["warnings"] == []
