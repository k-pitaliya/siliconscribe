#!/usr/bin/env python3
"""Check each evaluated design against an INDEPENDENT reference testbench (written by hand, not by the model).

The pipeline's own PASS comes from a testbench the model wrote. This asks a different question: is the
final design actually correct? Run:  cd backend && python3 evaluation/independent/run.py
A design with no reference here (the sequential ones need a hand-written cycle model) is listed as such.
"""
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACTS = HERE.parent / "artifacts"


def main() -> int:
    bad_total = 0
    for design in sorted(ARTIFACTS.glob("*_design.sv")):
        pid = design.name.split("_")[0]
        tb = HERE / f"tb_{pid}.v"
        if not tb.exists():
            print(f"{pid}: no independent reference yet")
            continue
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sim.vvp"
            c = subprocess.run(["iverilog", "-g2012", "-o", str(out), str(design), str(tb)], capture_output=True, text=True)
            if c.returncode != 0:
                print(f"{pid}: COMPILE ERROR {c.stderr.strip()[:120]}")
                bad_total += 1
                continue
            r = subprocess.run(["vvp", "-n", str(out)], capture_output=True, text=True)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith(pid)), r.stdout.strip()[:100])
        nums = [int(n) for n in re.findall(r"(\d+) (?:result |signed-overflow )?mismatches", line)]
        verdict = "CORRECT" if nums and all(n == 0 for n in nums) else "MISMATCH"
        bad_total += verdict != "CORRECT"
        print(f"{pid}: {verdict:8s} {line}")
    return 1 if bad_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
