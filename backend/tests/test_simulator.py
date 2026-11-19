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


# ------------------------------------------------------------------ self-review findings (19 Nov 2026)
def test_dump_injection_ignores_comments():
    from simulator import ensure_vcd_dump
    tb = ("// Testbench for the add4 module under test; checks all 16 vectors\n"
          "module testbench;\n  // we do not call $dumpvars ourselves\n  initial $finish;\nendmodule\n")
    out = ensure_vcd_dump(tb)
    assert out.startswith("// Testbench for the add4 module under test; checks all 16 vectors\nmodule testbench;\n    initial begin")
    assert '$dumpfile("design.vcd")' in out


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
def test_the_standard_check_task_compares_ports_wider_than_64_bits(tmp_path):
    """DV3: the 64-bit chk task let a 72-bit design that drops its top byte PASS."""
    import offline_designs as od
    from simulator import IcarusSimulator
    rtl = "module wide(input [71:0] d, output [71:0] q); assign q = {8'h00, d[63:0]}; endmodule"
    tb = ("module testbench; integer pass_count = 0, fail_count = 0; reg [71:0] d; wire [71:0] q; wide dut(.d(d), .q(q));\n"
          + od.CHK_TASK + "initial begin d = 72'hAB_DEADBEEF_00000000; #1; chk(\"random\", \"top_byte\", d, q);\n"
          "$display(\"Passed: %0d\", pass_count); $display(\"Failed: %0d\", fail_count); $finish; end endmodule")
    assert IcarusSimulator(workspace=str(tmp_path)).simulate("wide1", rtl, tb, timeout=10).status == "FAIL"


@pytest.mark.parametrize("header", ["/* tb */ module testbench;", "`timescale 1ns/1ps module testbench;", "(* keep *) module testbench;"])
def test_dump_injection_works_when_the_header_is_not_at_the_start_of_a_line(header):
    from simulator import ensure_vcd_dump
    out = ensure_vcd_dump(header + "\n  initial $finish;\nendmodule\n")
    assert out.index("$dumpfile") < out.index("endmodule") and out.index("module testbench;") < out.index("$dumpfile")
