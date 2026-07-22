import shutil
import pytest

from vcd_parser import parse_vcd, _bin_to_hex
from simulator import IcarusSimulator
import offline_designs as od


def test_bin_to_hex():
    assert _bin_to_hex("1010") == "a"
    assert _bin_to_hex("0000") == "0"
    assert _bin_to_hex("1111") == "f"
    assert _bin_to_hex("xxxx") == "x"


def test_parse_synthetic_vcd(tmp_path):
    vcd = tmp_path / "design.vcd"
    vcd.write_text(
        "$timescale 1ns $end\n"
        "$var wire 1 ! clk $end\n"
        "$var wire 4 # data $end\n"
        "$enddefinitions $end\n"
        "#0\n0!\nb0000 #\n"
        "#5\n1!\n"
        "#10\n0!\nb1010 #\n"
    )
    wf = parse_vcd(vcd)
    assert wf is not None
    assert wf.end_time == 10
    names = {s.name: s for s in wf.signals}
    assert "clk" in names and "data" in names
    clk = names["clk"]
    assert clk.wave[0] == {"t": 0, "v": "0"}
    assert clk.wave[1] == {"t": 5, "v": "1"}
    data = names["data"]
    assert data.wave[-1] == {"t": 10, "v": "a"}


def test_parse_missing_file_returns_none(tmp_path):
    assert parse_vcd(tmp_path / "nope.vcd") is None


@pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
def test_parse_real_vcd(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    d = od.get_design("counter")
    r = sim.simulate("cnt", d["rtl"], d["tb"], timeout=15)
    assert r.waveform_file
    wf = parse_vcd(r.waveform_file)
    assert wf is not None and len(wf.signals) > 0
    assert any(s.name == "clk" for s in wf.signals)


def test_parse_synthetic_vcd_no_truncation(tmp_path):
    """Regression: a small VCD must report truncated=False."""
    vcd = tmp_path / "small.vcd"
    vcd.write_text(
        "$timescale 1ns $end\n"
        "$var wire 1 ! clk $end\n"
        "$enddefinitions $end\n"
        "#0\n0!\n#5\n1!\n"
    )
    wf = parse_vcd(vcd)
    assert wf is not None
    assert wf.truncated is False
    assert wf.dropped_signals == 0
    assert wf.changes_truncated is False


def test_parse_vcd_truncation_fields(tmp_path):
    """Regression: VCD parser must populate truncation metadata."""
    from vcd_parser import MAX_SIGNALS
    # Build a VCD with more signals than MAX_SIGNALS.
    lines = ["$timescale 1ns $end\n"]
    for i in range(MAX_SIGNALS + 5):
        lines.append(f"$var wire 1 {chr(33 + i)} sig{i} $end\n")
    lines.append("$enddefinitions $end\n")
    lines.append("#0\n")
    for i in range(MAX_SIGNALS + 5):
        lines.append(f"0{chr(33 + i)}\n")
    vcd = tmp_path / "big.vcd"
    vcd.write_text("\n".join(lines))
    wf = parse_vcd(vcd)
    assert wf is not None
    assert wf.truncated is True
    assert wf.dropped_signals == 5
    assert len(wf.signals) == MAX_SIGNALS
