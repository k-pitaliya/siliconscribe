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
