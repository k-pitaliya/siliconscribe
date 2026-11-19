"""Waveform data the viewer relies on: roles, ordering, de-duplication, truncation, x/z nibbles."""

from vcd_parser import MAX_CHANGES_PER_SIGNAL, _bin_to_hex, parse_vcd, ports_from_rtl


def test_hex_is_per_nibble_and_unknown_bits_stay_visible():
    assert _bin_to_hex("1010xxxx") == "ax"
    assert _bin_to_hex("00001111") == "f"
    assert _bin_to_hex("1x01") == "x"
    assert _bin_to_hex("zzzz") == "z"
    assert _bin_to_hex("xxxxxxxx") == "x"
    assert _bin_to_hex("0000") == "0"


VCD = """$timescale 1ps $end
$scope module testbench $end
$var reg 1 ! clk $end
$var reg 1 " rst_n $end
$var reg 4 # d [3:0] $end
$var wire 4 $ q [3:0] $end
$var integer 32 % pass_count [31:0] $end
$scope task chk $end
$var reg 64 & exp_v [63:0] $end
$upscope $end
$scope module dut $end
$var parameter 32 ' WIDTH [31:0] $end
$var reg 4 ( q [3:0] $end
$var reg 4 ) state [3:0] $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0!
0"
b0000 #
bxxxx $
b0 %
b0 &
b100 '
bxxxx (
b0000 )
#5000
1!
b0101 #
b0101 $
b1 %
"""


def test_roles_ordering_and_duplicate_removal(tmp_path):
    f = tmp_path / "w.vcd"
    f.write_text(VCD)
    wf = parse_vcd(f, ports={"clk": "input", "rst_n": "input", "d": "input", "q": "output"})
    by = {s.path: s for s in wf.signals}
    roles = [s.role for s in wf.signals]
    assert roles == sorted(roles, key=["clock", "reset", "in", "out", "dut_internal", "internal", "tb", "aux", "param"].index)
    assert by["testbench.clk"].role == "clock" and by["testbench.rst_n"].role == "reset"
    assert by["testbench.d"].role == "in" and by["testbench.q"].role == "out"
    assert by["testbench.pass_count"].role == "tb"
    assert by["testbench.chk.exp_v"].role == "aux"
    assert by["testbench.dut.WIDTH"].role == "param"
    assert by["testbench.dut.state"].role == "dut_internal"
    assert "testbench.dut.q" not in by, "the DUT copy of an already-shown net must be dropped"
    assert (by["testbench.d"].msb, by["testbench.d"].lsb) == (3, 0)
    assert wf.timescale_ps == 1.0 and wf.timescale_defaulted is False


def test_the_signal_cap_drops_testbench_noise_before_design_signals(tmp_path):
    lines = ["$timescale 1ns $end\n$scope module testbench $end\n",
             "$var reg 1 ! clk $end\n$var wire 4 \" y [3:0] $end\n"]
    for i in range(60):
        lines.append(f"$var integer 32 s{i} counter{i} [31:0] $end\n")
    lines.append("$upscope $end\n$enddefinitions $end\n#0\n0!\nb0 \"\n")
    f = tmp_path / "many.vcd"
    f.write_text("".join(lines))
    wf = parse_vcd(f, max_signals=5, ports={"y": "output"})
    names = [s.name for s in wf.signals]
    assert "clk" in names and "y" in names
    assert wf.dropped_signals == 57 and wf.truncated is True


def test_capped_signal_reports_where_its_data_stops(tmp_path):
    body = "".join(f"#{i}\n{i % 2}!\n" for i in range(MAX_CHANGES_PER_SIGNAL + 50))
    f = tmp_path / "long.vcd"
    f.write_text("$timescale 1ns $end\n$var reg 1 ! clk $end\n$enddefinitions $end\n" + body)
    sig = parse_vcd(f).signals[0]
    assert len(sig.wave) == MAX_CHANGES_PER_SIGNAL
    assert sig.truncated_at == sig.wave[-1]["t"]


def test_timescale_default_is_flagged(tmp_path):
    f = tmp_path / "d.vcd"
    f.write_text("$timescale 1s $end\n$var reg 1 ! clk $end\n$enddefinitions $end\n#0\n0!\n")
    assert parse_vcd(f).timescale_defaulted is True


def test_ports_can_be_recovered_from_an_rtl_header():
    rtl = """module counter #(parameter WIDTH = 4)(
        input  wire             clk,
        input  wire             rst_n,
        input  wire             enable,
        output reg  [WIDTH-1:0] count
    );
    endmodule"""
    assert ports_from_rtl(rtl) == {"clk": "input", "rst_n": "input", "enable": "input", "count": "output"}
    assert ports_from_rtl("module m(input a, b, output y); endmodule") == {"a": "input", "b": "input", "y": "output"}
    assert ports_from_rtl("not verilog") == {}
