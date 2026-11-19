"""Yosys warnings shown in the results keep the message but not the server's temporary paths."""
from schematic import _yosys_warnings


def test_absolute_paths_in_warnings_are_reduced_to_file_names():
    out = ("Warning: Replacing memory \\mem with list of registers. See /private/var/folders/zp/k8q/T/docrun_x/doc_fifo/design.sv:43\n"
           "Warning: Replacing memory \\mem with list of registers. See /private/var/folders/zp/k8q/T/docrun_x/doc_fifo/design.sv:43\n"
           "Warning: Driver-driver conflict for \\y between cell $1.Y and constant 1'0 in top\n")
    got = _yosys_warnings(out)
    assert got[0] == "Replacing memory \\mem with list of registers. See design.sv:43"
    assert len(got) == 2 and "/private" not in " ".join(got)                # de-duplicated, no directories
    assert got[1].startswith("Driver-driver conflict")                       # messages without paths are untouched


def test_synthesis_refuses_sources_that_reach_local_files(tmp_path):
    """Yosys evaluates `include and $readmemh itself, so synthesis applies the same sandbox policy."""
    import shutil
    import pytest
    from schematic import synthesize_with_yosys
    if shutil.which("yosys") is None:
        pytest.skip("yosys not installed")
    secret = tmp_path / "secret.hex"
    secret.write_text("de\nad\nbe\nef\n")
    bad = {
        "readmemh": f'module m(input [1:0] a, output [7:0] y);\n reg [7:0] mem [0:3];\n'
                    f' initial $readmemh("{secret}", mem);\n assign y = mem[a];\nendmodule',
        "include": f'module m(input a, output y);\n`include "{secret}"\nassign y = a;\nendmodule',
    }
    for name, rtl in bad.items():
        r = synthesize_with_yosys(rtl, "m", tmp_path / name)
        assert r.get("error", "").startswith("Source not synthesized"), (name, r)
        assert "cell_count" not in r and "json_netlist" not in r, name
    ok = synthesize_with_yosys("module m(input a, b, output y);\nassign y = a & b;\nendmodule", "m", tmp_path / "ok")
    assert ok.get("error") is None and ok.get("cell_count", 0) >= 1          # clean RTL still synthesizes


def test_synthesis_returns_clean_rtl_and_gate_netlists_for_the_schematic(tmp_path):
    """Both schematic netlists: valid Yosys JSON for the top module, ports + cells only, no server paths."""
    import json
    import shutil
    import pytest
    from schematic import synthesize_with_yosys
    import offline_designs
    if shutil.which("yosys") is None:
        pytest.skip("yosys not installed")
    r = synthesize_with_yosys(offline_designs.COUNTER_RTL, "counter", tmp_path / "w")
    assert r.get("error") is None, r.get("error")
    rtl, gate = r["rtl_netlist"]["modules"]["counter"], r["json_netlist"]["modules"]["counter"]
    for m in (rtl, gate):
        assert m["attributes"] == {"top": 1}
        assert set(m) == {"attributes", "ports", "cells"}
        assert {"clk", "rst_n", "enable", "count"} <= set(m["ports"])
        assert all(set(c) == {"type", "port_directions", "connections"} for c in m["cells"].values())
    rtl_types = {c["type"] for c in rtl["cells"].values()}
    gate_types = {c["type"] for c in gate["cells"].values()}
    assert "$add" in rtl_types and any("dff" in t.lower() for t in rtl_types)       # word-level RTL cells
    assert "$add" not in gate_types and any(t.startswith("$_") for t in gate_types)  # single-bit gates
    assert len(gate["cells"]) == r["cell_count"]                                     # same design the metrics describe
    text = json.dumps(r["rtl_netlist"]) + json.dumps(r["json_netlist"])
    assert str(tmp_path) not in text and "/private/" not in text and '"src"' not in text
