"""Pre-layout timing: parsers on recorded tool output, honest 'not available', and real-tool runs."""
import shutil
from pathlib import Path

import pytest

import offline_designs as od
import timing
from timing import find_clock, parse_mapped_stats, parse_sta, run_timing, timing_message

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
    assert t["power_mw"] == pytest.approx(0.0269)


def test_negative_slack_means_the_target_is_missed_and_fmax_is_below_it():
    t = parse_sta("worst slack max -2.19\n", period_ns=0.5)
    assert t["met"] is False and t["fmax_mhz"] == pytest.approx(1000 / 2.69, abs=0.1)
    assert parse_sta("no slack line here", 10.0) == {}


def test_clock_detection():
    assert find_clock("module m(input wire clk, input wire d, output reg q); endmodule") == "clk"
    assert find_clock("module m(input wire [3:0] a, output wire y); endmodule") is None


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
