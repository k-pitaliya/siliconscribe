"""Mutation tests: a testbench that cannot fail is not a testbench.

For each curated design we run the known-good RTL to prove the TB passes, then
inject one small semantic bug and require the TB to report FAIL. This is the
guard against the "DUT and TB are wrong together" failure mode: it proves the
testbench actually compares against an expected value instead of merely
observing activity.
"""

import shutil

import pytest

import offline_designs as od
from simulator import IcarusSimulator

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog not installed"
)

# (design key, exact source fragment, semantic mutant)
MUTANTS = [
    # counter: arithmetic, reset, enable
    ("counter", "count <= count + 1'b1;", "count <= count + 2'd2;"),
    ("counter", "count <= count + 1'b1;", "count <= count - 1'b1;"),
    ("counter", "if (!rst_n)", "if (rst_n)"),                       # reset polarity inverted
    ("counter", "if (!rst_n)\n            count <= {WIDTH{1'b0}};\n        else if (enable)",
                "if (1'b0)\n            count <= {WIDTH{1'b0}};\n        else if (enable)"),  # reset ignored
    ("counter", "count <= {WIDTH{1'b0}};", "count <= {{(WIDTH-1){1'b0}},1'b1};"),  # wrong reset value
    ("counter", "else if (enable)", "else if (1'b1)"),               # enable ignored
    # 4-bit ALU: opcode decode, overflow flag, undefined opcodes
    ("alu", "3'b010: result = a & b;", "3'b010: result = a | b;"),
    ("alu", "3'b000: {overflow, result} = a + b;", "3'b000: {overflow, result} = a - b;"),
    ("alu", "3'b001: {overflow, result} = a - b;", "3'b001: {overflow, result} = a + b;"),
    ("alu", "3'b100: result = a ^ b;", "3'b100: result = a | b;"),
    ("alu", "3'b000: {overflow, result} = a + b;", "3'b000: result = a + b;"),          # overflow stuck 0
    ("alu", "default: result = {WIDTH{1'b0}};", "default: result = {WIDTH{1'b1}};"),    # undefined opcode
    # 8-bit ALU
    ("alu8", "3'b000: {overflow, result} = a + b;", "3'b000: result = a + b;"),         # overflow stuck 0
    ("alu8", "default: result = {WIDTH{1'b0}};", "default: result = {WIDTH{1'b1}};"),   # undefined opcode
    # combinational blocks
    ("adder", "assign sum  = a ^ b ^ cin;", "assign sum  = a ^ b;"),
    ("mux", "2'b00: y = d0;", "2'b00: y = d1;"),
]


@needs_iverilog
@pytest.mark.parametrize("key,fragment,mutant", MUTANTS)
def test_testbench_catches_semantic_mutant(tmp_path, key, fragment, mutant):
    design = od.get_design(key)
    assert fragment in design["rtl"], f"mutation anchor missing for {key}"

    sim = IcarusSimulator(workspace=str(tmp_path))

    # 1. The TB must PASS the known-good RTL (otherwise it is simply broken).
    good = sim.simulate(f"{key}-good", design["rtl"], design["tb"], timeout=30)
    assert good.status == "PASS", f"{key} TB rejected its own golden RTL:\n{good.log_excerpt}"

    # 2. The same TB must FAIL a semantically wrong RTL.
    bad_rtl = design["rtl"].replace(fragment, mutant, 1)
    bad = sim.simulate(f"{key}-mutant", bad_rtl, design["tb"], timeout=30)
    assert bad.status == "FAIL", (
        f"{key} TB did not catch mutation {fragment!r} -> {mutant!r} "
        f"(status={bad.status}). The TB is not checking this behaviour.\n"
        f"{bad.log_excerpt}"
    )
    assert bad.fail_count > 0, f"{key} mutant FAILed without incrementing fail_count"


def test_tb_check_counter_recognises_curated_tbs():
    """Every curated TB must contain explicit self-checks."""
    from orchestrator import _tb_check_count

    for key in ("counter", "alu", "adder", "mux"):
        tb = od.get_design(key)["tb"]
        assert _tb_check_count(tb) > 0, f"{key} TB has no detectable self-checks"
