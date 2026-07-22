import shutil
import pytest

from simulator import IcarusSimulator, ensure_vcd_dump
import offline_designs as od

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog not installed"
)


def test_ensure_vcd_dump_injects_when_missing():
    tb = "module testbench;\n  initial begin\n    #10 $finish;\n  end\nendmodule\n"
    out = ensure_vcd_dump(tb)
    assert "$dumpvars" in out and "$dumpfile" in out


def test_ensure_vcd_dump_idempotent():
    tb = 'module testbench;\n initial begin $dumpvars(0, testbench); end\nendmodule'
    assert ensure_vcd_dump(tb) == tb


@needs_iverilog
def test_full_adder_passes(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    d = od.get_design("adder")
    r = sim.simulate("fa", d["rtl"], d["tb"], timeout=15)
    assert r.status == "PASS"
    assert r.pass_count == 8 and r.fail_count == 0
    assert r.waveform_file is not None  # VCD produced


@needs_iverilog
def test_compile_error_is_structured(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    bad_rtl = "module broken (input a output b);\nassign b = a\nendmodule"  # missing comma/semicolon
    tb = "module testbench; initial $finish; endmodule"
    r = sim.simulate("bad", bad_rtl, tb, timeout=15)
    assert r.status == "ERROR"
    assert len(r.errors) >= 1


@needs_iverilog
def test_buggy_counter_fails(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    d = od.get_design("counter")
    r = sim.simulate("c", d["rtl_buggy"], d["tb"], timeout=15)
    assert r.status == "FAIL"
    assert r.fail_count > 0
