"""UVM bundle structure (self-review ASIC findings, 19 Nov 2026). The bundle is export-only (no UVM simulator here), so
these tests check the structural rules that made every bundle uncompilable, and the crash on mux-like specifications."""
import re
import shutil
import subprocess

import pytest

import offline_designs as od
import uvm_templates as u
from models import PortSpec, RTLDesignSpec

SPECS = {k: RTLDesignSpec(**od.get_design(k)["spec"]) for k in od.DESIGNS}
SPECS["sel_only"] = RTLDesignSpec(module_name="m2", behavior="x", ports=[
    PortSpec(name="sel", direction="input", width=2), PortSpec(name="y", direction="output", width=1)])
SPECS["d_sel_y"] = RTLDesignSpec(module_name="m3", behavior="x", ports=[
    PortSpec(name="d", direction="input", width=4), PortSpec(name="sel", direction="input", width=2),
    PortSpec(name="y", direction="output", width=1)])


@pytest.mark.parametrize("key", list(SPECS))
def test_a_bundle_is_generated_and_no_task_is_declared_inside_a_task(key):
    files = u.generate_uvm_bundle(SPECS[key])
    seq = next(v for n, v in files.items() if n.endswith("_sequence.sv"))
    for body in re.findall(r"virtual task body\(\);(.*?)\n    endtask", seq, re.S):
        assert not re.search(r"^\s*task\b", body, re.M), "a task declared inside body() is illegal SystemVerilog"


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
def test_the_helper_task_layout_parses(tmp_path):
    """The exact construct the bundle uses (helper tasks as class members before body) must parse; the old nesting did not."""
    src = tmp_path / "t.sv"
    src.write_text("class c; task send(input logic [1:0] v); endtask\n  virtual task body(); send(2'd1); endtask\nendclass\n"
                   "module top; endmodule\n")
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _shreg(rst="rst", clk="clk", constraints=("Synchronous design",)):
    return RTLDesignSpec(module_name="shreg", behavior="shift", constraints=list(constraints), ports=[
        PortSpec(name=clk, direction="input", width=1), PortSpec(name=rst, direction="input", width=1),
        PortSpec(name="d", direction="input", width=1), PortSpec(name="q", direction="output", width=4)])


def test_an_active_high_reset_is_wired_by_its_own_name_and_released_low():
    files = u.generate_uvm_bundle(_shreg("rst"))
    top = next(v for n, v in files.items() if n.endswith("tb_top.sv"))
    assert ".rst(rst)" in top and ".rst_n(" not in top
    assert "logic rst = 1'b1;" in top and "rst = 1'b0;" in top
    mon = next(v for n, v in files.items() if n.endswith("_monitor.sv"))
    assert "wait (vif.rst == 1'b0)" in mon


def test_an_active_low_reset_and_a_clock_named_clock_are_handled():
    files = u.generate_uvm_bundle(_shreg("areset_n", "clock"))
    top = next(v for n, v in files.items() if n.endswith("tb_top.sv"))
    assert ".clock(clock)" in top and ".areset_n(areset_n)" in top
    assert "forever #5 clock = ~clock;" in top and "logic areset_n = 1'b0;" in top


def test_a_clock_input_makes_the_design_sequential_even_without_the_word():
    assert u._is_sequential(_shreg(constraints=("Synchronous design",)))
    assert not u._RST_NAME_RE.search("burst") and not u._RST_NAME_RE.search("first")


def test_a_mux_with_a_b_and_a_select_is_not_treated_as_an_alu():
    mux = RTLDesignSpec(module_name="mux2", behavior="y = sel ? b : a", ports=[
        PortSpec(name="a", direction="input", width=4), PortSpec(name="b", direction="input", width=4),
        PortSpec(name="sel", direction="input", width=1), PortSpec(name="y", direction="output", width=4)])
    files = u.generate_uvm_bundle(mux)
    item = next(v for n, v in files.items() if n.endswith("_seq_item.sv"))
    assert "ADD" not in item and "XOR" not in item
    assert u._is_alu_like(SPECS["alu"], next(p for p in SPECS["alu"].ports if p.name in ("op", "opcode", "sel", "alu_op")))
