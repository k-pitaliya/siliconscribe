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
    ("uninitialised fail_count prints 'Failed: x'", FAILS * 23 + "Passed: 177\nFailed: x\n", "FAIL"),   # FAIL lines seen
    ("an unreadable summary with no failure lines is an ERROR", "Passed: 177\nFailed: x\n", "ERROR"),
    ("a mid-run phase line must not be read as the summary",
     "Phase1 Passed: 5 Failed: 0\n" + FAILS * 20 + "Passed: 5\nFailed: 20\n", "FAIL"),
    ("'FAILED: NOT ALL TESTS PASSED' is not a pass", "FAILED: NOT ALL TESTS PASSED\nPassed: 3\n", "FAIL"),
    # review findings (self-review, 19 Nov)
    ("one failure and no FAIL line is a FAIL", "Passed: 9\nFailed: 1\n", "FAIL"),
    ("a later 'Failed: 0' does not cancel an earlier phase's failures", "Passed: 10\nFailed: 4\nPassed: 30\nFailed: 0\n", "FAIL"),
    ("a CHK|FAIL row contradicts 'Failed: 0'", "CHK|FAIL|directed|t1|5|1|2|\nPassed: 3\nFailed: 0\n", "FAIL"),
    ("FATAL without a summary is a FAIL (so the oracle may not be rewritten)", "FATAL: tb.sv:9: mismatch\n", "FAIL"),
    ("a non-ASCII digit in the summary is an ERROR, not a crash", "Passed: \u00b2\nFailed: 0\n", "ERROR"),
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
    # review findings (self-review, 19 Nov)
    'module dut(input a, output y); assign y = a; initial $display("Failed: 0"); endmodule',
    'module dut(input a, output y); assign y = a; initial #1 $stop; endmodule',
    'module dut(input a, output y); assign y = a; always @(a) testbench/*x*/.fail_count = 0; endmodule',
    'module dut(input a, output y); assign y = a; initial $root.testbench.fail_count = 0; endmodule',
    'module dut(input a, output y); assign y = a; final begin $write("%cassed: 16\\n", 8\'d80); end endmodule',
    'module dut(input a, output y); assign y = a; always @(a) $strobe("%d", a); endmodule',
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


def test_comments_mentioning_final_or_display_are_not_rejected():
    rtl = ("module dut(input a, output y); // the final value; no $display here\n"
           "  /* $write is forbidden in RTL */ assign y = a;\nendmodule")
    assert rtl_integrity_violations(rtl) == []


# ------------------------------------------------------------------ sandbox bypasses found by the self-review (19 Nov)
_TB = ("module testbench; reg [3:0] a; wire [3:0] y; integer fd; add dut(.a(a),.y(y));\n"
       "initial begin {body} a=1; #1; $display(\"Passed: 1\"); $display(\"Failed: 0\"); $finish; end endmodule")
_RTL = "module add(input [3:0] a, output [3:0] y); assign y=a; endmodule"


@pytest.mark.parametrize("body", [
    '$dumpfile/**/("{p}"); $dumpvars(0, testbench);',
    '$dumpfile // a comment\n ("{p}"); $dumpvars(0, testbench);',
    '$dumpfile /* a */ ( /* b */ "{p}" /* c */ ); $dumpvars(0, testbench);',
], ids=["block comment", "line comment", "comments everywhere"])
@needs_iverilog
def test_a_comment_before_the_dumpfile_argument_does_not_bypass_the_path_check(tmp_path, body):
    victim = tmp_path / "outside.txt"
    victim.write_text("ORIGINAL")
    tb = _TB.format(body=body.format(p=victim))
    assert any("$dumpfile" in v for v in sandbox_violations(_RTL, tb))
    res = IcarusSimulator(workspace=str(tmp_path / "ws")).simulate("dump1", _RTL, tb, timeout=20)
    assert res.status == "ERROR"
    assert victim.read_text() == "ORIGINAL", "the waveform was written outside the workspace"


@needs_iverilog
def test_a_macro_cannot_build_a_forbidden_system_task(tmp_path):
    target = tmp_path / "made_by_macro.txt"
    tb = "`define D $\n`define E fopen\n`define F fclose\n" + _TB.format(
        body=f'fd = `D`E("{target}","w"); `D`F(fd);')
    assert any("$fopen" in v for v in sandbox_violations(_RTL, tb))      # found after macro expansion
    res = IcarusSimulator(workspace=str(tmp_path / "ws")).simulate("macro1", _RTL, tb, timeout=20)
    assert res.status == "ERROR"
    assert not target.exists(), "a macro-built $fopen wrote a file outside the workspace"


def test_plain_dumpfile_names_and_harmless_defines_are_still_allowed():
    tb = "`define WIDTH 4\n" + _TB.format(body='$dumpfile("wave.vcd"); $dumpvars(0, testbench);')
    assert sandbox_violations(_RTL, tb) == []
    assert sandbox_violations(_RTL, _TB.format(body="$dumpfile;")) == []


@needs_iverilog
def test_a_valid_summary_followed_by_runaway_output_is_not_a_pass(tmp_path, monkeypatch):
    """The exit-code rule was only unit-tested; this pins the wiring from vvp's exit code to the verdict."""
    import simulator
    monkeypatch.setattr(simulator, "_MAX_OUTPUT_BLOCKS", 64)          # a small output cap, so the test is fast
    tb = ('module testbench; wire [3:0] y; add dut(.a(4\'d1), .y(y));\n'
          'initial begin $display("Passed: 5"); $display("Failed: 0");\n'
          '  forever begin $display("spam spam spam spam spam spam spam spam spam spam"); #1; end end endmodule')
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("flood1", _RTL, tb, timeout=20)
    assert res.status != "PASS"


# ------------------------------------------------------------------ verification-round findings (19 Nov 2026)
@needs_iverilog
@pytest.mark.parametrize("body", [
    'fd = `ID($)fopen("{p}","w"); `ID($)fclose(fd);',
    '`ID($)dumpfile("{p}"); $dumpvars(0, testbench);',
], ids=["macro-argument $fopen", "macro-argument $dumpfile"])
def test_a_dollar_passed_through_a_macro_argument_is_caught_after_expansion(tmp_path, body):
    target = tmp_path / "outside.txt"
    tb = "`define ID(a) a\n" + _TB.format(body=body.format(p=target))
    assert sandbox_violations(_RTL, tb)
    res = IcarusSimulator(workspace=str(tmp_path / "ws")).simulate("macro2", _RTL, tb, timeout=20)
    assert res.status == "ERROR" and not target.exists()


@needs_iverilog
def test_a_macro_defined_in_the_rtl_and_used_in_the_testbench_is_expanded_in_compile_order(tmp_path):
    rtl = "`define ID(a) a\n" + _RTL
    tb = _TB.format(body=f'fd = `ID($)fopen("{tmp_path / "x.txt"}","w");')
    assert any("$fopen" in v for v in sandbox_violations(rtl, tb))


@needs_iverilog
@pytest.mark.parametrize("rtl", [
    "`define T testbench\nmodule dut(input a, output y); assign y = ~a; initial #1 `T.fail_count = 0; endmodule",
    "`define ID(a) a\nmodule dut(input a, output y); assign y = ~a;\n"
    "initial begin `ID($)write(\"%cassed: 16\\n\", 80); `ID($)finish; end endmodule",
], ids=["macro alias for testbench", "macro-built $write and $finish"])
def test_macro_tricks_in_the_rtl_cannot_forge_the_verdict(rtl):
    assert rtl_integrity_violations(rtl) or sandbox_violations(rtl)


@needs_iverilog
def test_legitimate_macros_are_still_allowed(tmp_path):
    tb = ("`define CHECK(c) if (!(c)) begin $display(\"FAIL: c\"); end\n`define AW $clog2(16)\n"
          + _TB.format(body="`CHECK(1);"))
    assert sandbox_violations(_RTL, tb) == []
    assert IcarusSimulator(workspace=str(tmp_path)).simulate("legit1", _RTL, tb, timeout=20).status == "PASS"


@pytest.mark.parametrize("src", [
    "testbench" + "/**/" * 40000 + "x", "$dumpfile(" + "/**/" * 20000 + '"a"' + "/**/" * 20000 + "x",
    "/* " * 60000, "$dumpfile/*" * 20000, "testbench/*" * 20000, "$dumpfile(" * 20000,
], ids=["comments after testbench", "comments in dumpfile", "unterminated comments", "dumpfile + open comment",
        "testbench + open comment", "unclosed dumpfile calls"])
def test_the_scanners_stay_fast_on_adversarial_input(src):
    import time
    t = time.time()
    sandbox_violations(src)
    _rtl_text_rules(src)
    assert time.time() - t < 2.0, "a scanner backtracked (it took over 30 s before the fix)"


def _rtl_text_rules(src):
    from simulator import _rtl_integrity_text
    return _rtl_integrity_text(src)
