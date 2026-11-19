"""Formal equivalence of RTL vs mapped netlist, and the critical path report (timing stage)."""
import re
import shutil
from pathlib import Path

import pytest

import equivalence
import offline_designs
import timing

needs_tools = pytest.mark.skipif(bool(timing.missing_requirements()) or shutil.which("yosys") is None,
                                 reason="needs yosys, OpenSTA and the sky130 liberty")
ARTIFACTS = Path(__file__).resolve().parent.parent / "evaluation" / "artifacts"


def _module(rtl):
    return re.search(r"module\s+(\w+)", rtl).group(1)


# ------------------------------------------------------------------ pure parsing (no tools)
COUNTER_BLOCK = """_14_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _17_ (rising edge-triggered flip-flop clocked by clk)
    Delay      Time   Description
-------------------------------------------------------------
   0.0000    0.0000   clock clk (rise edge)
   0.0000    0.0000   clock network delay (ideal)
   0.0000    0.0000 ^ _14_/CLK (sky130_fd_sc_hd__dfrtp_1)
   0.3584    0.3584 ^ _14_/Q (sky130_fd_sc_hd__dfrtp_1)
   0.1163    0.4747 v _09_/Y (sky130_fd_sc_hd__nand4_1)
   0.1303    0.6049 v _10_/Y (sky130_fd_sc_hd__xnor2_1)
   0.0000    0.6049 v _17_/D (sky130_fd_sc_hd__dfrtp_1)
             0.6049   data arrival time

  10.0000   10.0000   clock clk (rise edge)
            10.0000 ^ _17_/CLK (sky130_fd_sc_hd__dfrtp_1)
"""


def test_critical_path_rows_are_the_data_path_cell_by_cell():
    rows = timing.critical_path_rows(COUNTER_BLOCK)
    assert [r["point"] for r in rows] == ["_14_/CLK", "_14_/Q", "_09_/Y", "_10_/Y", "_17_/D"]   # stops at arrival
    assert rows[2] == {"point": "_09_/Y", "cell": "nand4_1", "edge": "fall", "incr_ns": 0.1163, "arrival_ns": 0.4747}
    assert rows[1]["edge"] == "rise" and rows[-1]["arrival_ns"] == 0.6049


def test_parse_sta_attaches_the_worst_path():
    text = "Startpoint: " + COUNTER_BLOCK + "  10.2283   data required time\n            9.6234   slack (MET)\n" \
           "Startpoint: rst_n (input port)\nEndpoint: _14_ (recovery check)\n   0.0000    0.0000 ^ rst_n (in)\n" \
           "             0.0000   data arrival time\n            10.2283   slack (MET)\n"
    out = timing.parse_sta(text, 10.0)
    assert out["critical_start"] == "_14_" and len(out["critical_path"]) == 5          # 9.62 < 10.23: data path


@pytest.mark.parametrize("output, sequential, status", [
    ("...\nSUCCESS!\n", False, "proven"),
    ("...\nFAIL!\n", False, "different"),
    ("ERROR: something\n", False, None),
    ("Of those cells 52 are proven and 0 are unproven.\nEquivalence successfully proven!\n", True, "proven"),
    ("Of those cells 0 are proven and 2 are unproven.\n", True, "not_proven"),
    ("ERROR: no such module\n", True, None),
])
def test_interpret_never_turns_an_undecided_or_broken_run_into_a_pass(output, sequential, status):
    assert equivalence.interpret(output, sequential)["status"] == status


# ------------------------------------------------------------------ real tools
@needs_tools
def test_combinational_netlist_is_proven_by_sat(tmp_path):
    r = timing.run_timing(offline_designs.ALU_RTL_4, _module(offline_designs.ALU_RTL_4), tmp_path, 100)
    assert r.equivalence == "proven" and "SAT" in r.equivalence_method
    assert r.critical_path and r.critical_path[0]["cell"] == "in" and r.critical_path[-1]["cell"] == "out"


@needs_tools
def test_sequential_netlist_is_proven_by_induction(tmp_path):
    r = timing.run_timing(offline_designs.COUNTER_RTL, "counter", tmp_path, 100)
    assert r.equivalence == "proven" and "induction" in r.equivalence_method
    assert r.critical_path[0]["point"].endswith("/CLK")                   # register-to-register path


@needs_tools
def test_a_sabotaged_netlist_is_reported_as_different(tmp_path):
    rtl = offline_designs.ALU_RTL_4
    timing.run_timing(rtl, _module(rtl), tmp_path, 100)
    net = (tmp_path / "netlist.v").read_text()
    sabotaged = net.replace("sky130_fd_sc_hd__nand2_1 ", "sky130_fd_sc_hd__nor2_1 ", 1)   # same pins (A, B, Y)
    assert sabotaged != net, "sabotage did not apply"
    (tmp_path / "netlist.v").write_text(sabotaged)
    eq = equivalence.prove_equivalence(tmp_path, _module(rtl), str(timing.LIBERTY))
    assert eq["status"] == "different"


@needs_tools
def test_re_encoded_fsm_state_is_not_proven_rather_than_passed(tmp_path):
    rtl = (ARTIFACTS / "f1_design.sv").read_text()
    r = timing.run_timing(rtl, _module(rtl), tmp_path, 100,
                          testbench_code=(ARTIFACTS / "f1_testbench.sv").read_text())
    assert r.equivalence == "not_proven" and "could not be decided" in r.equivalence_method


@needs_tools
def test_the_proof_uses_the_parameters_the_netlist_was_mapped_with(tmp_path):
    rtl = "module w #(parameter W = 2) (input [W-1:0] a, b, output [W-1:0] y); assign y = a & b; endmodule"
    tb = "module tb; w #(.W(6)) dut(); endmodule"
    r = timing.run_timing(rtl, "w", tmp_path, 100, testbench_code=tb)
    assert "W=6" in r.note and r.equivalence == "proven"     # a W=2 gold against a W=6 netlist could not pass


def test_clock_path_pins_after_the_arrival_time_are_not_part_of_the_data_path():
    # With propagated clocks OpenSTA lists clock-tree pins in the required-time half, in the same row format.
    block = COUNTER_BLOCK.replace("            10.0000 ^ _17_/CLK", "   0.0500   10.0500 ^ ckbuf/X (sky130_fd_sc_hd__clkbuf_1)\n            10.0500 ^ _17_/CLK")
    assert "ckbuf/X" in block
    assert "ckbuf/X" not in [r["point"] for r in timing.critical_path_rows(block)]


@needs_tools
def test_x_inputs_cannot_fake_a_mismatch(tmp_path):
    # Regression: with X allowed on inputs, SAT "disproved" this correct ALU (evaluation c7) using b = 100x.
    rtl = (ARTIFACTS / "c7_design.sv").read_text()
    r = timing.run_timing(rtl, _module(rtl), tmp_path, 100, testbench_code=(ARTIFACTS / "c7_testbench.sv").read_text())
    assert r.equivalence == "proven", r.equivalence_method


@needs_tools
def test_a_lookup_table_design_is_proven_not_skipped(tmp_path):
    # Regression: evaluation c5 builds its decoder from an initialised array; SAT cannot model memory init, so the
    # gold design must go through `memory` first (as synthesis does) or the check silently cannot run.
    rtl = (ARTIFACTS / "c5_design.sv").read_text()
    r = timing.run_timing(rtl, _module(rtl), tmp_path, 100, testbench_code=(ARTIFACTS / "c5_testbench.sv").read_text())
    assert r.equivalence == "proven", r.equivalence_method
