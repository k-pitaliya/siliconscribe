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
