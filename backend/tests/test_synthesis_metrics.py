"""Cell counts come from the JSON netlist, not from Yosys' changing text format."""
import shutil
import tempfile
from pathlib import Path

import pytest

from schematic import _yosys_warnings, summarize_netlist, synthesize_with_yosys

needs_yosys = pytest.mark.skipif(shutil.which("yosys") is None, reason="yosys not installed")

NETLIST = {"modules": {"top": {"cells": {
    "a": {"type": "$_AND_"}, "b": {"type": "$_AND_"}, "c": {"type": "$_XOR_"},
    "d": {"type": "$_DFF_PN0_"}, "e": {"type": "$_DLATCH_P_"},
}}}}


def test_summary_counts_types_flops_and_latches():
    s = summarize_netlist(NETLIST, "top")
    assert s["cell_count"] == 5
    assert s["cell_types"][0] == ["AND", 2]                       # most common first, $_ and _ stripped
    assert s["flip_flops"] == 1 and s["latches"] == 1


def test_summary_falls_back_to_the_only_module_and_handles_garbage():
    assert summarize_netlist(NETLIST, "other_name")["cell_count"] == 5
    assert summarize_netlist({}, "top") is None
    assert summarize_netlist({"modules": {"m": {"cells": {}}}}, "m")["cell_count"] == 0


def test_yosys_warnings_are_deduplicated_and_capped():
    out = "x\nWarning: Found 1 problems\nWarning: Found 1 problems\n" + "".join(f"Warning: w{i}\n" for i in range(9))
    w = _yosys_warnings(out)
    assert w[0] == "Found 1 problems" and len(w) == 5 and len(set(w)) == 5


@needs_yosys
def test_real_synthesis_of_a_counter_reports_cells_and_four_flops():
    import offline_designs as od
    r = synthesize_with_yosys(od.get_design("counter")["rtl"], "counter", Path(tempfile.mkdtemp()))
    assert r["available"] and "error" not in r, r.get("error")
    assert r["cell_count"] > 4 and r["flip_flops"] == 4 and r["latches"] == 0
    assert r["liberty_mapped"] is False                           # still no pretend-real area


@needs_yosys
def test_an_incomplete_combinational_if_is_reported_as_a_latch():
    rtl = "module lat(input en, input d, output reg q);\n always @(*) if (en) q = d;\nendmodule\n"
    r = synthesize_with_yosys(rtl, "lat", Path(tempfile.mkdtemp()))
    assert r["latches"] >= 1 and "latch" in r["latch_warning"]


@pytest.mark.skipif(shutil.which("yosys") is None, reason="yosys not installed")
def test_sub_modules_are_counted_as_their_gates_not_as_one_cell_each(tmp_path):
    """Self-review finding: without -flatten, a ripple adder of 4 full_adder instances reported 4 cells of type
    full_adder, and a latch inside a sub-module was not reported."""
    rtl = ("module full_adder(input a, b, ci, output s, co); assign s = a ^ b ^ ci; assign co = (a & b) | (ci & (a ^ b));\n"
           "endmodule\n"
           "module rca(input [3:0] a, b, output [3:0] s, output co); wire [4:0] c; assign c[0] = 1'b0; assign co = c[4];\n"
           "genvar i; generate for (i = 0; i < 4; i = i + 1) begin : g\n"
           "  full_adder fa(.a(a[i]), .b(b[i]), .ci(c[i]), .s(s[i]), .co(c[i+1])); end endgenerate\nendmodule\n"
           "module lat(input en, d, output reg q); always @* if (en) q = d; endmodule\n"
           "module top(input [3:0] a, b, input en, output [3:0] s, output co, output q);\n"
           "rca r(.a(a), .b(b), .s(s), .co(co)); lat l(.en(en), .d(a[0]), .q(q)); endmodule\n")
    info = synthesize_with_yosys(rtl, "top", tmp_path)
    types = dict((t, n) for t, n in info.get("cell_types") or [])
    assert "full_adder" not in types and "rca" not in types
    assert info["cell_count"] > 4
    assert info["latches"] >= 1
