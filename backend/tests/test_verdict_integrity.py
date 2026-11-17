"""PASS must be hard to fake: replays the attacks found in the verification/security review.

Every case below was reproduced against the previous code, where it produced a wrong
PASS (verdict forgery) or let a testbench write a file outside its workspace.
"""

import shutil

import pytest

import offline_designs as od
from simulator import (IcarusSimulator, _decide_verdict, rtl_integrity_violations,
                       sandbox_violations)

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")

FAILS = "FAIL: expected=1 got=2\n"

# (name, log, expected status)
VERDICT_CASES = [
    ("honest pass", "Passed: 200\nFailed: 0\nALL TESTS PASSED\n", "PASS"),
    ("honest fail", FAILS * 23 + "Passed: 177\nFailed: 23\n", "FAIL"),
    ("design prints a fake PASS early; the real summary at the end wins",
     "Passed: 200\nFailed: 0\nALL TESTS PASSED\n" + FAILS * 23 + "Passed: 177\nFailed: 23\n", "FAIL"),
    ("uninitialised fail_count prints 'Failed: x'", FAILS * 23 + "Passed: 177\nFailed: x\n", "ERROR"),
    ("a mid-run phase line must not be read as the summary",
     "Phase1 Passed: 5 Failed: 0\n" + FAILS * 20 + "Passed: 5\nFailed: 20\n", "FAIL"),
    ("'FAILED: NOT ALL TESTS PASSED' is not a pass", "FAILED: NOT ALL TESTS PASSED\nPassed: 3\n", "ERROR"),
    ("$error lines contradict 'Failed: 0'", "ERROR: mismatch\nPassed: 10\nFailed: 0\nALL TESTS PASSED\n", "FAIL"),
    ("FAIL lines contradict 'Failed: 0'", FAILS + "Passed: 10\nFailed: 0\nALL TESTS PASSED\n", "FAIL"),
    ("no summary at all", "hello\n", "ERROR"),
    ("zero executed checks is not a pass", "Passed: 0\nFailed: 0\nALL TESTS PASSED\n", "ERROR"),
    ("summary words embedded in other text are ignored", "Tests Passed: 5, Failed: 0\n", "ERROR"),
]


@pytest.mark.parametrize("name,log,expected", VERDICT_CASES, ids=[c[0] for c in VERDICT_CASES])
def test_verdict_is_not_forgeable(name, log, expected):
    assert _decide_verdict(log)[0] == expected


def test_killed_simulator_is_not_a_pass():
    assert _decide_verdict("Passed: 5\nFailed: 0\n", returncode=0)[0] == "PASS"
    status, *_ , notes = _decide_verdict("Passed: 5\nFailed: 0\n", returncode=153)
    assert status == "ERROR" and "exited with code 153" in notes[0]


def test_excerpt_keeps_the_first_failure_not_only_the_tail():
    from simulator import _excerpt
    log = "FAIL: first failing vector a=1 b=2\n" + ("x" * 4000) + "\nPASS tail\n"
    out = _excerpt(log)
    assert "first failing vector" in out and out.rstrip().endswith("PASS tail")
    assert "characters omitted" in out


# ------------------------------------------------------------------ sandbox allowlist
RTL = "module dut(input a, output y); assign y = a; endmodule\n"


def _tb(body):
    return ("module testbench; reg a; wire y; integer fd; dut u(.a(a), .y(y));\n initial begin\n" + body +
            '\n $display("Passed: 1"); $display("Failed: 0"); $finish; end endmodule\n')


@pytest.mark.parametrize("body", [
    'fd = $fopena("/tmp/x");',            # open-mode variant of $fopen (escape found live)
    '$fputc(65, fd);',
    'fd = $ivlh_file_open("/tmp/x", 1);',  # VHDL-textio VPI task (escape found live)
    '$ivlh_readline(fd);',
    '$some_future_vpi_task();',            # an unknown task must be refused, not assumed safe
    '$test$plusargs("x");',
])
def test_unlisted_system_tasks_are_rejected(body):
    assert sandbox_violations(RTL, _tb(body)), body


def test_allowed_tasks_still_work():
    ok = _tb('$display("x %0d", $time); a = $random; $dumpfile("design.vcd"); $dumpvars(0, testbench); '
             'if ($isunknown(y)) $display("x"); $timeformat(-9, 1, " ns", 8);')
    assert sandbox_violations(RTL, ok) == []


@needs_iverilog
def test_file_write_escape_is_really_blocked_end_to_end(tmp_path):
    target = tmp_path / "OUTSIDE.txt"
    sim = IcarusSimulator(workspace=str(tmp_path / "ws"))
    res = sim.simulate("esc1", RTL, _tb(f'fd = $fopena("{target}"); $fputc(65, fd);'), timeout=10)
    assert res.status == "ERROR" and "not an allowed system task" in res.log_excerpt
    assert not target.exists(), "the testbench wrote a file outside its workspace"


# ------------------------------------------------------------------ the design cannot forge the verdict
@pytest.mark.parametrize("rtl", [
    'module dut(input a, output y); assign y = a; initial begin $display("Passed: 200"); end endmodule',
    'module dut(input a, output y); assign y = a; initial begin $display("ALL TESTS PASSED"); $finish; end endmodule',
    'module dut(input a, output y); assign y = a; initial #1 $fatal; endmodule',
    'module dut(input a, output y); assign y = a; initial testbench.fail_count = 0; endmodule',
])
def test_rtl_cannot_print_the_verdict_end_the_run_or_reach_the_testbench(rtl):
    assert rtl_integrity_violations(rtl)


@needs_iverilog
def test_forging_design_is_rejected_end_to_end(tmp_path):
    d = od.get_design("alu")
    forged = d["rtl"].replace("endmodule", 'initial begin $display("Passed: 200"); $display("Failed: 0"); '
                                           '$display("ALL TESTS PASSED"); $finish; end\nendmodule')
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("forge1", forged, d["tb"], timeout=20)
    assert res.status == "ERROR" and "forge the test verdict" in res.log_excerpt


@needs_iverilog
def test_a_genuinely_wrong_design_still_fails_with_the_real_testbench(tmp_path):
    d = od.get_design("alu")
    wrong = d["rtl"].replace("a & b", "a | b", 1)
    assert wrong != d["rtl"]
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("wrong1", wrong, d["tb"], timeout=20)
    assert res.status == "FAIL" and res.fail_count > 0


# ------------------------------------------------------------------ compile-time protections
@needs_iverilog
def test_testbench_wire_narrower_than_the_port_is_an_error(tmp_path):
    rtl = "module dut(input [7:0] a, output [7:0] y); assign y = a; endmodule\n"
    tb = ("module testbench; reg [7:0] a; wire [3:0] y; dut u(.a(a), .y(y));\n"
          ' initial begin a = 8\'hFF; #1; $display("Passed: 1"); $display("Failed: 0"); $finish; end endmodule\n')
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("width1", rtl, tb, timeout=10)
    assert res.status == "ERROR" and "port width mismatch" in res.log_excerpt


@needs_iverilog
def test_rtl_with_hash_delays_is_not_a_false_fail(tmp_path):
    """`count <= #1 ...` compiled before the TB's timescale used to mean a 1 s delay."""
    d = od.get_design("counter")
    delayed = d["rtl"].replace("count <= count + 1'b1;", "count <= #1 count + 1'b1;")
    assert delayed != d["rtl"]
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("delay1", delayed, d["tb"], timeout=20)
    assert res.status == "PASS", res.log_excerpt


@needs_iverilog
def test_timeout_reports_the_hang_and_keeps_flushed_output_for_the_fixer(tmp_path):
    """A testbench with no $finish used to give the fixer nothing at all.

    Only output the simulator has already flushed survives the kill (stdio buffers
    are lost with SIGKILL), so the test prints enough to force a flush before hanging.
    """
    tb = ('module testbench; reg a; wire y; integer i; dut u(.a(a), .y(y));\n'
          ' initial begin for (i = 0; i < 600; i = i + 1) $display("progress line %0d", i);\n'
          "  forever #1 a = ~a; end endmodule\n")
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("hang1", RTL, tb, timeout=2)
    assert res.status == "TIMEOUT"
    assert "no $finish" in res.log_excerpt and "progress line" in res.log_excerpt
