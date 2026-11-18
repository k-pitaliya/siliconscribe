"""The mapping verification tool: its helpers, and that it really detects a wrong netlist."""
import importlib.util
import shutil
from pathlib import Path

import pytest

import offline_designs as od
import timing

SPEC = importlib.util.spec_from_file_location("verify_mapping", Path(__file__).resolve().parents[1] / "tools" / "verify_mapping.py")
vm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vm)

needs_tools = pytest.mark.skipif(bool(timing.missing_requirements()) or shutil.which("iverilog") is None,
                                 reason="yosys, OpenSTA or the sky130 library is not installed")


def test_top_module_is_the_one_the_testbench_instantiates():
    rtl = "module leaf(input a, output y); assign y = a; endmodule\nmodule top #(parameter W = 4)(input a, output y); leaf u(.a(a), .y(y)); endmodule"
    assert vm.top_module(rtl, "module testbench; top #(.W(4)) dut (.a(a), .y(y)); endmodule") == "top"
    assert vm.top_module(rtl, "module testbench; top dut (.a(a)); endmodule") == "top"
    assert vm.top_module(rtl, "module testbench; endmodule") is None


def test_parameter_overrides_are_stripped_for_the_gate_level_testbench_only():
    tb = "module testbench; mux #(.WIDTH(f(1,2)), .X(3)) dut (.a(a)); endmodule"
    assert vm.strip_parameter_overrides(tb, "mux") == "module testbench; mux  dut (.a(a)); endmodule"
    assert vm.strip_parameter_overrides("mux dut (.a(a));", "mux") == "mux dut (.a(a));"


@needs_tools
def test_every_library_cell_has_an_area_even_when_its_area_line_is_far_down():
    areas = vm.liberty_areas()
    assert len(areas) > 400
    assert areas["sky130_fd_sc_hd__mux4_2"] == pytest.approx(22.5216)      # its `area` sits ~7000 characters into the cell
    assert vm.netlist_totals("  sky130_fd_sc_hd__mux4_2 _0_ (\n    .A0(a)\n  );\n", areas) == (22.522, 1)
    with pytest.raises(KeyError):
        vm.netlist_totals("  sky130_fd_sc_hd__nosuchcell_1 _0_ (\n  );\n", areas)


@needs_tools
@pytest.mark.parametrize("key", ["counter", "mux", "adder"])
def test_built_in_designs_pass_all_three_checks(tmp_path, key):
    d = od.DESIGNS[key]
    models = vm.build_cell_models(tmp_path)
    res = vm.check_design(f"builtin-{key}", d["rtl"], d["tb"], models, vm.liberty_areas(), tmp_path)
    assert res["status"] == "OK", res


@needs_tools
@pytest.mark.parametrize("old, new", [("sky130_fd_sc_hd__maj3_1", "sky130_fd_sc_hd__and3_1"),     # carry becomes a plain AND
                                      ("sky130_fd_sc_hd__xor3_1", "sky130_fd_sc_hd__or3_1")])      # sum becomes a plain OR
def test_a_netlist_that_computes_something_else_is_caught(tmp_path, monkeypatch, old, new):
    """Sabotage the mapped netlist (same pins, different logic): the gate-level comparison must fail it.
    A checker that cannot fail would prove nothing, so the sabotage is asserted to have really happened."""
    d = od.DESIGNS["adder"]
    models = vm.build_cell_models(tmp_path)
    real = timing.run_timing
    edits = []
    def sabotaged(*a, **kw):
        r = real(*a, **kw)
        nl = Path(a[2]) / "netlist.v"
        text = nl.read_text()
        edits.append(old in text)
        nl.write_text(text.replace(old, new))
        return r
    monkeypatch.setattr(timing, "run_timing", sabotaged)
    res = vm.check_design("sabotaged", d["rtl"], d["tb"], models, vm.liberty_areas(), tmp_path)
    assert edits and all(edits), "the sabotage did not change the netlist, so this test proves nothing"
    assert res["status"] == "FAIL" and "gate-level simulation differs" in res["detail"], res
