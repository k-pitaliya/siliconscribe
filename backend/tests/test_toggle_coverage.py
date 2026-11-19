"""Toggle coverage is MEASURED from the simulator's VCD, only for design signals, and never affects the verdict."""
import shutil

import pytest

import offline_designs as od
import vcd_parser
from simulator import IcarusSimulator
from vcd_parser import _pad_bits, toggle_coverage

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")

HEADER = """$timescale 1ns $end
$scope module testbench $end
$var wire 1 ! clk $end
$var reg 1 " en $end
$var integer 32 # pass_count [31:0] $end
$var wire 4 $ q [3:0] $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 1 " enable $end
$var reg 4 $ q [3:0] $end
$var reg 2 % state [1:0] $end
$var parameter 32 & WIDTH [31:0] $end
$var integer 32 ' i [31:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
"""


def _vcd(tmp_path, body, header=HEADER):
    p = tmp_path / "t.vcd"
    p.write_text(header + body)
    return p


def test_counts_only_design_nets_and_uses_their_design_names(tmp_path):
    body = "#0\n0!\n0\"\nb0 $\nb0 %\nb100 #\nb100 &\nb0 '\n#5\n1!\n1\"\nb1111 $\nb11 %\nb1 '\n#10\n0!\n0\"\nb0 $\nb0 %\nb0 '\n"
    t = toggle_coverage(_vcd(tmp_path, body))
    # clk(1) + enable(1) + q(4) + state(2) = 8 bits; the testbench integer, the parameter and the
    # loop integer are not design nets even though they toggled.
    assert (t.signals, t.bits_total, t.bits_toggled, t.percent) == (4, 8, 8, 100.0)
    assert t.untoggled == [] and t.partial is False


def test_a_port_first_seen_at_testbench_level_is_still_a_design_signal(tmp_path):
    body = "#0\n0!\n0\"\nb0 $\nb0 %\n#5\n1!\nb1 $\n#10\n0!\nb0 $\n"       # `en`/`enable` (code ") never changes
    t = toggle_coverage(_vcd(tmp_path, body))
    names = {u.signal for u in t.untoggled}
    assert "enable" in names and "en" not in names            # reported under the design's own name
    en = next(u for u in t.untoggled if u.signal == "enable")
    assert en.never_rose == [0] and en.never_fell == [0]


def test_a_bit_needs_both_directions_and_changes_through_x_do_not_count(tmp_path):
    body = ("#0\nx!\nx\"\nbx $\nb0 %\n"          # start unknown
            "#5\n1!\n0\"\nb0 $\n"                 # x -> 1 is NOT a rise; x -> 0 is not a fall
            "#10\n0!\n1\"\nb1 $\nb1 %\n"          # clk falls; enable rises; q[0], state[0] rise
            "#15\n1!\n")                           # clk rises -> clk now covered
    t = toggle_coverage(_vcd(tmp_path, body))
    by = {u.signal: u for u in t.untoggled}
    assert "clk" not in by                                         # rose and fell
    assert by["enable"].never_fell == [0] and by["enable"].never_rose == []
    assert by["q"].never_rose == [1, 2, 3] and by["q"].never_fell == [0, 1, 2, 3]
    assert t.bits_toggled == 1 and t.bits_total == 8 and t.percent == 12.5


def test_vector_values_are_padded_the_way_vcd_abbreviates_them():
    assert _pad_bits("1", 4) == "0001"
    assert _pad_bits("x", 4) == "xxxx"
    assert _pad_bits("z1", 4) == "zzz1"
    assert _pad_bits("101010", 4) == "1010"


def test_no_design_hierarchy_or_no_file_gives_none(tmp_path):
    flat = "$scope module testbench $end\n$var reg 1 ! a $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#1\n1!\n"
    assert toggle_coverage(_vcd(tmp_path, "", header=flat)) is None
    assert toggle_coverage(tmp_path / "missing.vcd") is None
    (tmp_path / "junk.vcd").write_text("not a vcd")
    assert toggle_coverage(tmp_path / "junk.vcd") is None


def test_the_untoggled_list_is_capped_worst_first_and_a_cut_file_is_marked_partial(tmp_path, monkeypatch):
    decl = "".join(f"$var reg {w} s{i} sig{i} [{w-1}:0] $end\n" for i, w in enumerate([1] * 14 + [8]))
    header = "$scope module testbench $end\n$scope module dut $end\n" + decl + "$upscope $end\n$upscope $end\n$enddefinitions $end\n"
    t = toggle_coverage(_vcd(tmp_path, "#0\n" + "".join(f"b0 s{i}\n" for i in range(15)), header=header))
    assert len(t.untoggled) == vcd_parser.MAX_UNTOGGLED_LISTED and t.untoggled_more == 3
    assert t.untoggled[0].signal == "sig14"                         # the 8-bit signal has the most missing bits
    monkeypatch.setattr(vcd_parser, "MAX_VCD_BYTES", len(header) + 10)
    assert toggle_coverage(tmp_path / "t.vcd").partial is True


@needs_iverilog
def test_real_runs_counter_is_fully_toggled_and_the_plus_two_bug_shows_as_a_stuck_bit(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    d = od.get_design("counter")
    good = sim.simulate("tgood", d["rtl"], d["tb"]).measured_toggle
    assert good.percent == 100.0 and good.signals == 4 and good.bits_total == 7      # clk, rst_n, enable, count[3:0]
    bad = sim.simulate("tbad", d["rtl_buggy"], d["tb"]).measured_toggle
    stuck = {u.signal: u for u in bad.untoggled}
    assert stuck["count"].never_rose == [0] and stuck["count"].never_fell == [0]       # counting by 2 never moves bit 0


@needs_iverilog
def test_a_single_sweep_testbench_is_honestly_reported_below_100_percent(tmp_path):
    d = od.get_design("adder")
    r = IcarusSimulator(workspace=str(tmp_path)).simulate("tadd", d["rtl"], d["tb"])
    assert r.status == "PASS" and r.measured_toggle.percent < 100.0                     # PASS and coverage are separate facts


@needs_iverilog
def test_a_failing_measurement_never_changes_the_verdict(tmp_path, monkeypatch):
    import simulator
    monkeypatch.setattr(simulator, "toggle_coverage", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    d = od.get_design("counter")
    r = IcarusSimulator(workspace=str(tmp_path)).simulate("tboom", d["rtl"], d["tb"])
    assert r.status == "PASS" and r.measured_toggle is None


# ------------------------------------------------------------------ self-review finding (19 Nov 2026)
@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
def test_a_testbench_side_helper_module_does_not_count_as_design(tmp_path):
    """A stimulus LFSR instantiated in the testbench raised the adder's toggle coverage from 46% to 77%."""
    from simulator import IcarusSimulator, dut_instance_names
    rtl = "module add4(input [3:0] a, b, output [4:0] s); assign s = a + b; endmodule\n"
    helper = ("module stim_gen(input clk, output reg [15:0] r); initial r = 16'hACE1;\n"
              "  always @(posedge clk) r <= {r[14:0], r[15] ^ r[13] ^ r[12] ^ r[10]}; endmodule\n")
    tb = ("module testbench; reg clk = 0; reg [3:0] a = 0, b = 0; wire [4:0] s; wire [15:0] r;\n"
          "  integer pass_count = 0, fail_count = 0;\n  add4 dut(.a(a), .b(b), .s(s));\n  stim_gen g(.clk(clk), .r(r));\n"
          "  always #5 clk = ~clk;\n  initial begin #1 a = 1; b = 1; #1 if (s === 2) pass_count = pass_count + 1; else fail_count = fail_count + 1;\n"
          "    #200 $display(\"Passed: %0d\", pass_count); $display(\"Failed: %0d\", fail_count); $finish; end\nendmodule\n" + helper)
    assert dut_instance_names(rtl, tb) == {"dut"}
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("tog1", rtl, tb, timeout=20)
    assert res.status == "PASS" and res.measured_toggle is not None
    assert res.measured_toggle.bits_total == 13           # a, b and s of the adder only (4 + 4 + 5), not the LFSR's 17


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
@pytest.mark.parametrize("inst", [
    "wrap w(.a(a), .b(b), .s(s));",
    "generate if (1) begin : g\n    add4 dut(.a(a), .b(b), .s(s));\n  end endgenerate",
], ids=["inside a wrapper", "inside a generate block"])
def test_a_design_inside_a_wrapper_or_generate_block_is_still_measured(tmp_path, inst):
    rtl = "module add4(input [3:0] a, b, output [4:0] s); assign s = a + b; endmodule\n"
    wrap = ("module wrap(input [3:0] a, b, output [4:0] s); add4 dut(.a(a), .b(b), .s(s)); endmodule\n"
            "module stim_gen(input clk, output reg [15:0] r); initial r = 16'hACE1; always @(posedge clk) r <= {r[14:0], r[15]};"
            " endmodule\n")
    tb = ("module testbench; reg clk = 0; reg [3:0] a = 0, b = 0; wire [4:0] s; wire [15:0] r; integer pass_count = 0, fail_count = 0;\n"
          "  stim_gen helper(.clk(clk), .r(r)); always #5 clk = ~clk;\n  " + inst +
          "\n  initial begin #1 a = 1; b = 1; #1 if (s === 2) pass_count = pass_count + 1; else fail_count = fail_count + 1;\n"
          "    $display(\"Passed: %0d\", pass_count); $display(\"Failed: %0d\", fail_count); $finish; end\nendmodule\n" + wrap)
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("tog2", rtl, tb, timeout=20)
    assert res.status == "PASS" and res.measured_toggle is not None
    assert res.measured_toggle.bits_total == 13          # the adder's a, b, s only: not the helper LFSR next to it
