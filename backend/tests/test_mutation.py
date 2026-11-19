"""Testbench strength: mutants are generated safely, scored honestly, and wired into the pipeline."""
import shutil
import time
from pathlib import Path

import pytest

import offline_designs as od
from models import SimulationResult, StrengthReport
from mutation import (
    apply_mutant, candidate_mutants, mask_code, run_strength, select_mutants, weak_strength_note,
)
from simulator import IcarusSimulator

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")

SRC = """`timescale 1ns/1ps
module m #(parameter WIDTH = 4 + 1)(input clk, input [WIDTH-1:0] a, b, output reg [WIDTH-1:0] y);
    // a + b - c would be a comment, "a + b" a string
    integer i;
    always @(posedge clk) begin
        for (i = 0; i < 4; i = i + 1) y <= y;
        if (a == b) y <= a + b;
        else y <= a & ~b;
    end
endmodule
"""


def _descs(code):
    return [(m.kind, code[m.start:m.end]) for m in candidate_mutants(code)]


def test_mask_keeps_length_and_newlines_and_blanks_what_must_not_be_mutated():
    masked = mask_code(SRC)
    assert len(masked) == len(SRC) and masked.count("\n") == SRC.count("\n")
    assert "a + b - c" not in masked and '"a + b"' not in masked      # comment and string gone
    assert "timescale" not in masked and "4 + 1" not in masked         # directive and parameter gone


def test_only_real_behaviour_is_mutated():
    found = _descs(SRC)
    kinds = {k for k, _ in found}
    assert {"add", "eq", "and", "bnot", "ifneg", "edge_p"} <= kinds
    # nothing inside the for header, the bit-range brackets, the parameter, comments or strings
    assert ("add", "+") in found                                       # the `a + b` in the body only
    assert sum(1 for k, _ in found if k == "add") == 1
    assert not any(k in ("lt", "const") for k, _ in found)             # `i < 4` is in the for header


def test_unary_minus_and_nonblocking_arrows_are_not_treated_as_binary_ops():
    code = "module t(input [3:0] a, output reg [3:0] y); always @(*) begin y = -a; y <= a - 1; end endmodule\n"
    subs = [m for m in candidate_mutants(code) if m.kind == "sub"]
    assert len(subs) == 1 and code[subs[0].start - 3:subs[0].start] == " a "   # only `a - 1`
    assert not [m for m in candidate_mutants(code) if m.kind == "lt"]          # `<=` is an assignment


def test_apply_mutant_changes_exactly_one_spot_and_negates_an_if():
    mutants = {m.kind: m for m in candidate_mutants(SRC)}
    out = apply_mutant(SRC, mutants["ifneg"])
    assert "if (!(a == b))" in out and out.count("\n") == SRC.count("\n")
    assert apply_mutant(SRC, mutants["add"]).count("a - b") == 1


def test_selection_is_deterministic_diverse_and_bounded():
    code = "module t(input [7:0] a, b, c, d, output [7:0] y); assign y = " + " + ".join("abcd"[i % 4] for i in range(40)) + \
           "; always @(*) if (a == b) ; endmodule\n"
    cands = candidate_mutants(code)
    assert len([c for c in cands if c.kind == "add"]) >= 30
    a, b = select_mutants(cands, 6), select_mutants(cands, 6)
    assert a == b and len(a) == 6
    assert {"ifneg", "eq"} <= {m.kind for m in a}                       # 40 `+` must not crowd the rest out
    assert [m.start for m in a] == sorted(m.start for m in a)


def test_a_design_with_nothing_to_mutate_is_skipped_not_scored():
    class Never:
        workspace = Path("/nonexistent")
        def simulate(self, *a, **k):
            raise AssertionError("no mutant should be simulated")
    r = run_strength(Never(), "x", "module t; endmodule\n", "module testbench; endmodule\n")
    assert r.status == "skipped" and r.total == 0


class _FakeSim:
    """Returns scripted results so the accounting rules can be pinned without Icarus."""
    def __init__(self, results, delay=0.0):
        self.results, self.delay, self.calls = list(results), delay, 0
        self.workspace = Path("/nonexistent")
    def simulate(self, design_id, rtl, tb, timeout=60):
        time.sleep(self.delay)
        self.calls += 1
        return self.results.pop(0)


def _res(status, log=""):
    return SimulationResult(status=status, module_name="m", log_excerpt=log)


def test_scoring_rules_pass_survives_fail_and_hang_are_caught_crash_is_inconclusive():
    code = ("module t(input a, b, c, d, output y, z); assign y = (a & b) | (c ^ d);\n"
            " assign z = (a == b) && (c != d); endmodule\n")
    n = len(select_mutants(candidate_mutants(code)))
    assert n >= 6
    script = [_res("PASS"), _res("FAIL"), _res("TIMEOUT"), _res("ERROR", "Compilation failed:\nboom"),
              _res("ERROR", "No valid summary"), _res("ERROR", "Rejected by sandbox policy: x")][:n]
    sim = _FakeSim([_res("PASS")] + script + [_res("FAIL")] * (n - len(script)))     # first call: the unmutated baseline
    r = run_strength(sim, "design1234", code, "tb")
    assert r.invalid == 2                                               # compile failure + sandbox refusal
    assert r.inconclusive == 1                                          # a crash without a reported failure
    assert r.total == n - 3
    assert len(r.survivors) == 1                                        # only the PASS survived
    assert r.killed == r.total - 1                                      # FAIL, and a hang of a fast testbench, count as caught


def test_a_timeout_is_not_a_catch_when_the_testbench_is_slow_anyway(monkeypatch):
    """Review finding: a one-check testbench with a long busy loop scored 3/3 because every mutant timed out."""
    import mutation
    monkeypatch.setattr(mutation, "PER_MUTANT_TIMEOUT", 0.3)
    code = "module t(input a, b, output y); assign y = a & b; endmodule\n"
    n = len(select_mutants(candidate_mutants(code)))
    sim = _FakeSim([_res("PASS")] + [_res("TIMEOUT")] * n, delay=0.15)      # the baseline itself takes half the limit
    r = run_strength(sim, "design1234", code, "tb")
    assert r.killed == 0 and r.inconclusive == n
    assert r.status == "skipped"                                            # nothing was really scored


def test_time_budget_returns_a_partial_report_instead_of_hanging():
    code = ("module t(input a, b, c, d, output y, z); assign y = (a & b) | (c ^ d);\n"
            " assign z = (a == b) && (c != d); endmodule\n")
    sim = _FakeSim([_res("FAIL")] * 20, delay=0.1)
    r = run_strength(sim, "design1234", code, "tb", budget_seconds=0.25)
    assert r.status == "partial" and 0 < r.total < len(select_mutants(candidate_mutants(code)))


def test_warning_only_for_a_clearly_weak_testbench():
    weak = StrengthReport(status="ok", total=10, killed=3)
    assert "caught only 3 of 10" in weak_strength_note(weak)
    assert weak_strength_note(StrengthReport(status="ok", total=10, killed=9)) is None
    assert "caught none of the 3" in weak_strength_note(StrengthReport(status="ok", total=3, killed=0))   # small, but zero
    assert weak_strength_note(StrengthReport(status="ok", total=3, killed=1)) is None      # too few to judge a ratio
    assert weak_strength_note(StrengthReport(status="skipped")) is None
    assert weak_strength_note(None) is None


@needs_iverilog
@pytest.mark.parametrize("key,min_killed", [("alu", 12), ("alu8", 12), ("mux", 3), ("counter", 7), ("adder", 5)])
def test_curated_testbenches_catch_almost_every_injected_bug(key, min_killed, tmp_path):
    d = od.get_design(key)
    r = run_strength(IcarusSimulator(workspace=str(tmp_path)), "cur" + key, d["rtl"], d["tb"])
    assert r.status == "ok" and r.killed >= min_killed, (key, r.killed, r.total, r.survivors)
    assert r.killed + len(r.survivors) == r.total


@needs_iverilog
def test_a_testbench_that_barely_checks_anything_scores_low_and_is_flagged(tmp_path):
    d = od.get_design("counter")
    weak_tb = (
        "`timescale 1ns/1ps\nmodule testbench;\n    reg clk = 0, rst_n = 0, enable = 0;\n    wire [3:0] count;\n"
        "    integer pass_count = 0, fail_count = 0;\n" + od.CHK_TASK +
        "    counter #(4) dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));\n"
        "    always #5 clk = ~clk;\n"
        "    initial begin\n        #12; chk(\"reset\", \"only_check\", 0, count);\n"
        "        $display(\"Passed: %0d\", pass_count);\n        $display(\"Failed: %0d\", fail_count);\n        $finish;\n    end\n"
        "endmodule\n"
    )
    sim = IcarusSimulator(workspace=str(tmp_path))
    assert sim.simulate("weakbase", d["rtl"], weak_tb).status == "PASS"                 # it passes...
    r = run_strength(sim, "weakrun", d["rtl"], weak_tb)
    assert r.total >= 5 and r.killed / r.total < 0.5, (r.killed, r.total)               # ...but would catch few bugs
    assert "Weak testbench" in weak_strength_note(r)


@needs_iverilog
def test_scratch_folder_is_removed_after_scoring(tmp_path):
    d = od.get_design("adder")
    sim = IcarusSimulator(workspace=str(tmp_path))
    run_strength(sim, "tidyrun", d["rtl"], d["tb"])
    assert not [p for p in Path(tmp_path).iterdir() if p.name.endswith("_mu")]


@needs_iverilog
def test_pipeline_reports_strength_for_a_pass_and_none_for_a_fail(tmp_path):
    from orchestrator import pipeline_events
    def final(prompt, **kw):
        sim = IcarusSimulator(workspace=str(tmp_path))
        events = list(pipeline_events(prompt, "strengthrun", sim, **kw))
        return events, [e for e in events if e["stage"] == "done"][0]["response"]
    events, done = final("Design a 4-bit synchronous up-counter with async reset and enable")
    assert done["status"] == "PASS" and done["strength"]["total"] >= 5
    assert any(e["stage"] == "strength" for e in events)
    assert events.index(next(e for e in events if e["stage"] == "strength")) < len(events) - 1   # before 'done'
    _, bad = final("Design a buggy 4-bit counter", self_correct=False)
    assert bad["status"] == "FAIL" and bad["strength"] is None


@needs_iverilog
def test_pipeline_skips_strength_when_disabled(tmp_path, monkeypatch):
    import orchestrator
    monkeypatch.setattr(orchestrator, "STRENGTH_ENABLED", False)
    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(orchestrator.pipeline_events("Design a 4-bit synchronous up-counter with async reset and enable", "nostrength", sim))
    assert not any(e["stage"] == "strength" for e in events)
    assert [e for e in events if e["stage"] == "done"][0]["response"]["strength"] is None
