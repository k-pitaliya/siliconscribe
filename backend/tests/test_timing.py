"""Pre-layout timing: parsers on recorded tool output, honest 'not available', and real-tool runs."""
import shutil
from pathlib import Path

import pytest

import offline_designs as od
import timing
from timing import analyze_netlist, parameter_overrides, parse_mapped_stats, parse_sta, run_timing, sta_errors, timing_message

needs_tools = pytest.mark.skipif(bool(timing.missing_requirements()) or shutil.which("iverilog") is None,
                                 reason="yosys, OpenSTA or the sky130 library is not installed")

STAT = """6. Printing statistics.
=== counter ===
       11  150.144 cells
        4  100.096   sky130_fd_sc_hd__dfrtp_1
        1    3.754   sky130_fd_sc_hd__nand2_1
        3   26.275   sky130_fd_sc_hd__xnor2_1
        3   20.019   sky130_fd_sc_hd__xor2_1
   Chip area for module '\\counter': 150.144000
     of which used for sequential elements: 100.096000 (66.67%)
"""

STA = """Startpoint: rst_n (input port clocked by clk)
Endpoint: _14_ (recovery check against rising-edge clock clk)
           0.00   data arrival time
          10.23   slack (MET)

Startpoint: _14_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _17_ (rising edge-triggered flip-flop clocked by clk)
   0.00    0.60 v _17_/D (sky130_fd_sc_hd__dfrtp_1)
           0.60   data arrival time
           9.27   slack (MET)

worst slack max 9.27
Group                  Internal  Switching    Leakage      Total
Total                  2.32e-05   3.70e-06   6.25e-11   2.69e-05 100.0%
"""


def test_mapped_statistics_are_read_from_the_stat_file():
    s = parse_mapped_stats(STAT)
    assert s["area_um2"] == 150.144 and s["sequential_area_um2"] == 100.096
    assert s["cell_count"] == 11 and s["flip_flops"] == 4
    assert s["cells"][0] == ["dfrtp_1", 4]                       # most common first, library prefix dropped
    assert parse_mapped_stats("nothing useful") == {}


def test_sta_report_gives_worst_slack_fmax_and_the_critical_path():
    t = parse_sta(STA, period_ns=10.0)
    assert t["slack_ns"] == 9.27 and t["met"] is True
    assert t["fmax_mhz"] == pytest.approx(1000 / 0.73, abs=0.1)
    assert (t["critical_start"], t["critical_end"], t["critical_delay_ns"]) == ("_14_", "_17_", 0.6)   # smallest slack, not the first block


def test_negative_slack_means_the_target_is_missed_and_fmax_is_below_it():
    t = parse_sta("worst slack max -2.19\n", period_ns=0.5)
    assert t["met"] is False and t["fmax_mhz"] == pytest.approx(1000 / 2.69, abs=0.1)
    assert parse_sta("no slack line here", 10.0) == {}




def test_missing_tools_are_reported_never_estimated(monkeypatch, tmp_path):
    monkeypatch.setattr(timing, "missing_requirements", lambda: ["OpenSTA"])
    r = run_timing("module m(input a, output y); assign y = a; endmodule", "m", tmp_path, 100)
    assert r.available is False and "OpenSTA" in r.error
    assert r.slack_ns is None and r.area_um2 is None and r.fmax_mhz is None
    assert timing_message(r).startswith("Timing: Timing needs")


def test_bad_module_name_and_sandbox_violations_never_reach_a_tool(monkeypatch, tmp_path):
    monkeypatch.setattr(timing, "missing_requirements", lambda: [])
    monkeypatch.setattr(timing, "_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tool must not run")))
    assert "Invalid module name" in run_timing("module m; endmodule", "m; rm -rf", tmp_path).error
    r = run_timing('module m(output y);\n`include "/etc/passwd"\nendmodule', "m", tmp_path)
    assert r.available is False and "include" in r.error


def test_default_target_is_100_mhz():
    assert run_timing("x", "bad name", Path("/nonexistent")).period_ns == 10.0


@needs_tools
def test_real_counter_meets_100_mhz_with_four_flip_flops(tmp_path):
    d = od.get_design("counter")
    r = run_timing(d["rtl"], "counter", tmp_path, 100)
    assert r.available and r.error is None and r.met is True
    assert r.clock == "clk" and r.flip_flops == 4
    assert 0 < r.slack_ns < 10 and r.fmax_mhz > 100
    assert 50 < r.area_um2 < 1000 and r.cell_count >= 5
    assert not any("lpflow" in c[0] for c in r.cells)            # isolation cells are excluded from mapping
    assert "Not sign-off" in r.note


@needs_tools
def test_real_combinational_design_is_timed_with_a_virtual_clock_and_can_miss(tmp_path):
    d = od.get_design("alu8")
    fast = run_timing(d["rtl"], "alu_8bit", tmp_path / "a", 2000)
    assert fast.met is False and fast.slack_ns < 0 and fast.fmax_mhz < 2000 and fast.clock.startswith("virtual")
    slow = run_timing(d["rtl"], "alu_8bit", tmp_path / "b", 50)
    assert slow.met is True
    assert slow.fmax_mhz == pytest.approx(fast.fmax_mhz, rel=0.05)      # fmax does not depend on the target asked for


@needs_tools
def test_unsynthesizable_code_is_reported_plainly(tmp_path):
    r = run_timing("module m(input a, output y); assign y = nonexistent_thing; endmodule", "m", tmp_path)
    assert r.slack_ns is None and r.error


@needs_tools
def test_pipeline_emits_timing_after_a_pass_and_none_for_a_fail_or_when_disabled(tmp_path, monkeypatch):
    import orchestrator
    from simulator import IcarusSimulator
    def run(prompt, **kw):
        ev = list(orchestrator.pipeline_events(prompt, "timingrun", IcarusSimulator(workspace=str(tmp_path)), **kw))
        return ev, [e for e in ev if e["stage"] == "done"][0]["response"]
    ev, done = run("Design a 4-bit synchronous up-counter with async reset and enable", target_frequency_mhz=200)
    assert done["timing"]["met"] is True and done["timing"]["target_mhz"] == 200 and done["timing"]["period_ns"] == 5.0
    stages = [e["stage"] for e in ev]
    assert stages.index("timing") < stages.index("done")
    _, bad = run("Design a buggy 4-bit counter", self_correct=False)
    assert bad["timing"] is None
    monkeypatch.setattr(orchestrator, "TIMING_ENABLED", False)
    _, off = run("Design a 4-bit synchronous up-counter with async reset and enable")
    assert off["timing"] is None


# ---------------------------------------------------------------------------------------------
# Audit round: every case below was found by deliberately breaking the first version.
# ---------------------------------------------------------------------------------------------

NETLIST = """module cnt(clk, rst_n, en, q);
  input clk;
  input rst_n;
  input [1:0] bus;
  output [3:0] q;
  sky130_fd_sc_hd__dfrtp_1 _07_ (
    .CLK(clk),
    .D(_01_),
    .Q(q[0]),
    .RESET_B(rst_n)
  );
  sky130_fd_sc_hd__nand2_1 _08_ (
    .A(en),
    .B(q[0]),
    .Y(_01_)
  );
endmodule
"""


def _tools_netlist_totals(netlist: Path) -> tuple[float, int]:
    """Area and cell count recomputed from the written netlist and the liberty file (not from Yosys' own stat)."""
    import re
    lib = timing.LIBERTY.read_text()
    heads = list(re.finditer(r'cell\s*\(\s*"?(sky130_fd_sc_hd__\w+)"?\s*\)\s*\{', lib))
    area = {}
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(lib)
        a = re.search(r"\barea\s*:\s*([0-9.]+)", lib[m.end():end])
        if a:
            area[m.group(1)] = float(a.group(1))
    text = netlist.read_text()
    assert text.count("\nmodule ") == 1, "the design must be flattened to one module"
    cells = re.findall(r"^\s*(sky130_fd_sc_hd__\w+)\s+\S+\s*\($", text, re.M)
    return round(sum(area[c] for c in cells), 3), len(cells)


COUNTER_RTL = """module cnt(input {clk}, input rst_n, input en, output reg [7:0] q);
  always @(posedge {clk} or negedge rst_n) if (!rst_n) q <= 0; else if (en) q <= q + 1;
endmodule"""


def test_netlist_analysis_reads_clock_flops_and_ports():
    n = analyze_netlist(NETLIST)
    assert n["clock_nets"] == {"clk"} and n["flip_flops"] == 1 and n["latches"] == 0
    assert n["scalar_inputs"] == {"clk", "rst_n"}            # a bus is not a clock port
    assert n["unmapped"] == []
    bad = analyze_netlist(NETLIST.replace("sky130_fd_sc_hd__nand2_1 _08_", "\\$_TBUF_  _08_"))
    assert bad["unmapped"] == ["$_TBUF_"]
    latch = analyze_netlist(NETLIST.replace("sky130_fd_sc_hd__dfrtp_1", "sky130_fd_sc_hd__dlxtp_1"))
    assert latch["latches"] == 1 and latch["flip_flops"] == 0


def test_testbench_parameter_overrides_are_read_conservatively():
    tb = "mux4to1 #(.WIDTH(16), .DEPTH( 4 )) dut (.a(a));"
    assert parameter_overrides(tb, "mux4to1") == ({"WIDTH": 16, "DEPTH": 4}, False)
    assert parameter_overrides("m #(.W(2*8), .D(3)) u (.a(a));", "m") == ({"D": 3}, True)   # expressions are not guessed
    assert parameter_overrides("m #(.W(f(1,2))) u (.a(a));", "m") == ({}, True)               # nested parentheses
    assert parameter_overrides("other #(.W(8)) u ();", "m") == ({}, False)
    assert parameter_overrides("", "m") == ({}, False) and parameter_overrides(None, "m") == ({}, False)


def test_only_error_lines_are_quoted_not_warnings():
    out = "Warning 2402: power activity did not converge\nError: cell not found\nWarning: other"
    assert sta_errors(out) == ["Error: cell not found"]


def test_slack_keeps_four_decimals():
    assert parse_sta("worst slack max 8.8123\n", 10.0)["slack_ns"] == 8.8123


def test_power_is_not_reported():
    assert "power_mw" not in timing.TimingReport.model_fields      # never displayed, never claimed


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf"), 1e12, 20000])
def test_out_of_range_targets_fall_back_to_the_default(bad):
    assert run_timing("x", "bad name", Path("/nonexistent"), bad).period_ns == 10.0


@needs_tools
def test_hierarchical_design_reports_the_whole_design_not_one_module(tmp_path):
    rtl = """module add4(input [3:0] a, input [3:0] b, output [4:0] s); assign s = a + b; endmodule
module top(input clk, input rst_n, input [3:0] a, b, c, output reg [5:0] q);
  wire [4:0] s1, s2;
  add4 u1(.a(a), .b(b), .s(s1));
  add4 u2(.a(s1[3:0]), .b(c), .s(s2));
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 0; else q <= s1 + s2;
endmodule"""
    r = run_timing(rtl, "top", tmp_path, 100)
    assert r.error is None and r.slack_ns is not None and r.clock == "clk"      # the clock is the TOP module's port
    area, cells = _tools_netlist_totals(tmp_path / "netlist.v")
    assert r.area_um2 == pytest.approx(area, abs=0.01) and r.cell_count == cells
    assert r.flip_flops == 6


@needs_tools
@pytest.mark.parametrize("clk", ["clk", "sys_clk", "i_clk", "ck", "tick", "CK_50M"])
def test_clock_is_found_from_the_netlist_whatever_it_is_called(tmp_path, clk):
    r = run_timing(COUNTER_RTL.format(clk=clk), "cnt", tmp_path / clk, 100)
    assert r.error is None and r.clock == clk and r.flip_flops == 8
    ref = run_timing(COUNTER_RTL.format(clk="clk"), "cnt", tmp_path / "ref", 100)
    assert r.slack_ns == pytest.approx(ref.slack_ns, abs=1e-6)         # same circuit, same answer


@needs_tools
def test_two_clock_design_times_both_clocks_and_says_crossings_are_not_timed(tmp_path):
    rtl = """module two(input clk_a, input clk_b, input rst_n, input d, output reg qa, output reg qb);
  always @(posedge clk_a or negedge rst_n) if(!rst_n) qa<=0; else qa<=d;
  always @(posedge clk_b or negedge rst_n) if(!rst_n) qb<=0; else qb<=qa;
endmodule"""
    r = run_timing(rtl, "two", tmp_path, 100)
    assert r.error is None and r.clock == "clk_a, clk_b" and r.slack_ns is not None
    assert "between clocks" in r.note


@needs_tools
def test_derived_clock_is_refused_not_half_timed(tmp_path):
    rtl = """module dv(input clk, input rst_n, output reg a, output reg b);
  always @(posedge clk or negedge rst_n) if(!rst_n) a<=0; else a<=~a;
  always @(posedge a or negedge rst_n) if(!rst_n) b<=0; else b<=~b;
endmodule"""
    r = run_timing(rtl, "dv", tmp_path, 100)
    assert r.slack_ns is None and r.met is None and "derived or gated" in r.error
    assert r.area_um2 is not None                                       # the mapped area is still real


@needs_tools
def test_latch_is_refused(tmp_path):
    r = run_timing("module lt(input en, input d, output reg q); always @* if (en) q = d; endmodule", "lt", tmp_path)
    assert r.slack_ns is None and "latch" in r.error.lower()


@needs_tools
def test_tristate_is_refused_instead_of_being_silently_turned_into_a_wire(tmp_path):
    r = run_timing("module ts(input en, input a, output y); assign y = en ? a : 1'bz; endmodule", "ts", tmp_path)
    assert r.slack_ns is None and r.met is None and "not mapped" in r.error


@needs_tools
def test_combinational_loop_is_refused(tmp_path):
    r = run_timing("module lp(input a, output y); wire w; assign w = ~(a & y); assign y = ~w; endmodule", "lp", tmp_path)
    assert r.slack_ns is None and "loop" in r.error.lower()


@needs_tools
@pytest.mark.parametrize("rtl", ["module k(output [3:0] y); assign y = 4'b1010; endmodule",
                                 "module w(input a, output y); assign y = a; endmodule"])
def test_design_with_no_logic_cells_has_nothing_to_time(tmp_path, rtl):
    r = run_timing(rtl, "k" if "module k" in rtl else "w", tmp_path)
    assert r.slack_ns is None and "no logic cells" in r.error


@needs_tools
def test_fmax_does_not_depend_on_the_target_asked_for(tmp_path):
    rtl = COUNTER_RTL.format(clk="clk")
    slow = run_timing(rtl, "cnt", tmp_path / "s", 100)
    fast = run_timing(rtl, "cnt", tmp_path / "f", 800)                 # close to the limit: 2-decimal rounding used to show here
    assert fast.fmax_mhz == pytest.approx(slow.fmax_mhz, rel=0.005)
    assert (slow.period_ns - slow.slack_ns) == pytest.approx(fast.period_ns - fast.slack_ns, abs=2e-4)


@needs_tools
def test_testbench_parameters_decide_which_circuit_is_timed(tmp_path):
    d = od.get_design("mux")
    default = run_timing(d["rtl"], "mux4to1", tmp_path / "d", 100)
    wide = run_timing(d["rtl"], "mux4to1", tmp_path / "w", 100, testbench_code="mux4to1 #(.WIDTH(16)) dut (.sel(s));")
    assert (default.cell_count, wide.cell_count) == (8, 16)             # the width follows the testbench
    assert "WIDTH=16" in wide.note and "WIDTH" not in default.note.replace("Not sign-off", "")
    odd = run_timing(d["rtl"], "mux4to1", tmp_path / "o", 100, testbench_code="mux4to1 #(.NOPE(3)) dut (.sel(s));")
    assert odd.error is None and odd.cell_count == 8                    # unknown name: falls back to the defaults
    expr = run_timing(d["rtl"], "mux4to1", tmp_path / "e", 100, testbench_code="mux4to1 #(.WIDTH(2*8)) dut (.sel(s));")
    assert expr.cell_count == 8 and "not plain numbers" in expr.note    # expressions are not guessed, and it says so


@needs_tools
def test_pipeline_gives_the_testbench_to_timing(tmp_path, monkeypatch):
    import orchestrator
    from simulator import IcarusSimulator
    seen = {}
    real = orchestrator.run_timing
    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)
    monkeypatch.setattr(orchestrator, "run_timing", spy)
    list(orchestrator.pipeline_events("Design a 4-bit synchronous up-counter with async reset and enable", "tbpass",
                                      IcarusSimulator(workspace=str(tmp_path))))
    assert "module testbench" in (seen.get("testbench_code") or "")


def test_positional_parameter_overrides_follow_the_declaration_order():
    rtl = "module m #(parameter integer W = 4, parameter [3:0] D = 2, E = 1)(input a, output y); endmodule"
    assert parameter_overrides("m #(8) u (.a(a));", "m", rtl) == ({"W": 8}, False)
    assert parameter_overrides("m #(8, 3, 5) u ();", "m", rtl) == ({"W": 8, "D": 3, "E": 5}, False)
    assert parameter_overrides("m #(2*8) u ();", "m", rtl) == ({}, True)
    assert parameter_overrides("m #(8, 3, 5, 7) u ();", "m", rtl) == ({"W": 8, "D": 3, "E": 5}, True)   # 4th has no name
    assert parameter_overrides("m #(8) u ();", "m") == ({}, True)                                       # no RTL given
    assert parameter_overrides("m #(.D(9)) u ();", "m", rtl) == ({"D": 9}, False)


@needs_tools
def test_positional_testbench_parameters_reach_the_timed_circuit(tmp_path):
    d = od.get_design("alu8")
    r = run_timing(d["rtl"], "alu_8bit", tmp_path, 100, testbench_code=d["tb"])
    assert r.error is None and "WIDTH=8" in r.note and "were not applied" not in r.note
