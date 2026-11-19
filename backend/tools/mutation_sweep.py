"""Mutation sweep over the curated designs.

Injects one semantic bug at a time into each curated RTL and checks that the
curated testbench turns PASS into FAIL/ERROR. Reproduces the "14 / 14 mutants
killed" figure in the final report.

    cd backend && python3 tools/mutation_sweep.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFLINE_MODE", "1")

import offline_designs as od  # noqa: E402
from simulator import IcarusSimulator  # noqa: E402

# (design, label, anchor in the golden RTL, mutant text)
MUTANTS = [
    ("counter", "increment by 2", "count <= count + 1'b1;", "count <= count + 2'd2;"),
    ("counter", "decrement", "count <= count + 1'b1;", "count <= count - 1'b1;"),
    ("counter", "reset polarity inverted", "if (!rst_n)", "if (rst_n)"),
    ("counter", "reset ignored",
     "if (!rst_n)\n            count <= {WIDTH{1'b0}};\n        else if (enable)",
     "if (1'b0)\n            count <= {WIDTH{1'b0}};\n        else if (enable)"),
    ("counter", "wrong reset value", "count <= {WIDTH{1'b0}};", "count <= {{(WIDTH-1){1'b0}},1'b1};"),
    ("counter", "enable ignored", "else if (enable)", "else if (1'b1)"),
    ("alu", "AND replaced by OR", "3'b010: result = a & b;", "3'b010: result = a | b;"),
    ("alu", "ADD replaced by SUB", "3'b000: {overflow, result} = a + b;", "3'b000: {overflow, result} = a - b;"),
    ("alu", "SUB replaced by ADD", "3'b001: {overflow, result} = a - b;", "3'b001: {overflow, result} = a + b;"),
    ("alu", "XOR replaced by OR", "3'b100: result = a ^ b;", "3'b100: result = a | b;"),
    ("alu", "overflow stuck at 0", "3'b000: {overflow, result} = a + b;", "3'b000: result = a + b;"),
    ("alu", "undefined opcode not zero", "default: result = {WIDTH{1'b0}};", "default: result = {WIDTH{1'b1}};"),
    ("adder", "sum drops carry-in", "assign sum  = a ^ b ^ cin;", "assign sum  = a ^ b;"),
    ("mux", "d0 and d1 swapped", "2'b00: y = d0;", "2'b00: y = d1;"),
    # --- Added after the verification review: bugs the first testbenches let SURVIVE. ---
    ("counter", "enable has priority over reset",
     "if (!rst_n)\n            count <= {WIDTH{1'b0}};\n        else if (enable)\n            count <= count + 1'b1;",
     "if (enable)\n            count <= count + 1'b1;\n        else if (!rst_n)\n            count <= {WIDTH{1'b0}};"),
    ("counter", "hold clears the count at state 3", "else if (enable)\n            count <= count + 1'b1;",
     "else if (enable)\n            count <= count + 1'b1;\n        else if (count == 4'd3)\n            count <= {WIDTH{1'b0}};"),
    ("counter", "hold clears the count at state 7", "else if (enable)\n            count <= count + 1'b1;",
     "else if (enable)\n            count <= count + 1'b1;\n        else if (count == 4'd7)\n            count <= {WIDTH{1'b0}};"),
    ("counter", "hold clears the count at state 12", "else if (enable)\n            count <= count + 1'b1;",
     "else if (enable)\n            count <= count + 1'b1;\n        else if (count == 4'd12)\n            count <= {WIDTH{1'b0}};"),
    ("alu8", "AND replaced by OR", "3'b010: result = a & b;", "3'b010: result = a | b;"),
    ("alu8", "add overflow off-by-one at sum==255", "3'b000: {overflow, result} = a + b;",
     "3'b000: begin {overflow, result} = a + b; if (a + b == 8'd255) overflow = 1'b1; end"),
    ("alu8", "sub borrow wrong when a==b", "3'b001: {overflow, result} = a - b;",
     "3'b001: begin {overflow, result} = a - b; if (a == b) overflow = 1'b1; end"),
    ("alu8", "sub borrow wrong when b==0", "3'b001: {overflow, result} = a - b;",
     "3'b001: begin {overflow, result} = a - b; if (b == 8'd0) overflow = 1'b1; end"),
    ("alu8", "0+0 sets overflow", "3'b000: {overflow, result} = a + b;",
     "3'b000: begin {overflow, result} = a + b; if (a == 8'd0 && b == 8'd0) overflow = 1'b1; end"),
    ("alu", "sensitivity list misses a, b and opcode", "always @(*) begin", "always @(opcode) begin"),
    ("alu", "sensitivity list misses opcode", "always @(*) begin", "always @(a or b) begin"),
    ("alu8", "sensitivity list misses b", "always @(*) begin", "always @(a or opcode) begin"),
    ("mux", "sensitivity list only sel", "always @(*) begin", "always @(sel) begin"),
]


def run_sweep(verbose: bool = False):
    """Run every mutant; return a list of (design, label, killed, golden, mutant, failed, total)."""
    sim = IcarusSimulator(workspace=tempfile.mkdtemp())
    rows = []
    for i, (key, label, old, new) in enumerate(MUTANTS):
        d = od.get_design(key)
        if old not in d["rtl"]:
            rows.append((key, label, False, "ANCHOR MISSING", "-", 0, 0))
            if verbose:
                print(f"{key:8s} {label:40s} ANCHOR MISSING")
            continue
        good = sim.simulate(f"g{i}", d["rtl"], d["tb"], timeout=60)
        bad = sim.simulate(f"m{i}", d["rtl"].replace(old, new, 1), d["tb"], timeout=60)
        ok = good.status == "PASS" and bad.status in ("FAIL", "ERROR")
        rows.append((key, label, ok, good.status, bad.status, bad.fail_count, bad.test_count))
        if verbose:
            print(f"{key:8s} {label:40s} {'KILLED  ' if ok else 'SURVIVED'} "
                  f"(golden={good.status}, mutant={bad.status}, failed {bad.fail_count}/{bad.test_count})")
    return rows


def main() -> int:
    rows = run_sweep(verbose=True)
    killed = sum(1 for r in rows if r[2])
    print(f"\nKILL RATE: {killed}/{len(rows)}")
    return 0 if killed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
