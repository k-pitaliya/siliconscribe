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
