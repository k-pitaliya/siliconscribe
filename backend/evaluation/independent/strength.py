#!/usr/bin/env python3
"""How strong are the hand-written reference testbenches? Inject bugs, count how many they notice.

    cd backend && PATH="$HOME/.local/bin:$PATH" python3 evaluation/independent/strength.py [ids...]

A reference testbench that reports "0 mismatches" on a correct design proves nothing unless it would report
mismatches on a wrong one. For each design that has a reference (tb_<id>.v) this runs EVERY one-token mutant the
app's own mutation generator can make (not the sample of 12 used inside the app) against the reference:
  killed    = the reference reports at least one mismatch
  survived  = the reference reports 0 mismatches (an equivalent mutant, or a gap in the reference: reviewed by hand)
  invalid   = the mutant does not compile or does not finish: says nothing and is not counted
"""
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
import mutation  # noqa: E402

ARTIFACTS = HERE.parent / "artifacts"
_MISMATCH = re.compile(r"(\d+) (?:result |signed-overflow )?mismatches")


def run_mutant(pid: str, code: str, tb: Path, workdir: Path, tag: str) -> str:
    src = workdir / f"{tag}.sv"
    src.write_text(code)
    vvp = workdir / f"{tag}.vvp"
    c = subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(src), str(tb)], capture_output=True, text=True, timeout=60)
    if c.returncode:
        return "invalid"
    try:
        r = subprocess.run(["vvp", "-n", str(vvp)], capture_output=True, text=True, timeout=40, cwd=str(workdir))
    except subprocess.TimeoutExpired:
        return "invalid"
    line = next((ln for ln in r.stdout.splitlines() if ln.startswith(pid)), "")
    nums = [int(x) for x in _MISMATCH.findall(line)]
    if not nums:
        return "invalid"
    return "killed" if any(nums) else "survived"


def sweep(pid: str) -> dict:
    design = (ARTIFACTS / f"{pid}_design.sv").read_text()
    tb = HERE / f"tb_{pid}.v"
    muts = mutation.candidate_mutants(design)
    with tempfile.TemporaryDirectory() as td, ThreadPoolExecutor(max_workers=4) as pool:
        wd = Path(td)
        outcomes = list(pool.map(lambda im: run_mutant(pid, mutation.apply_mutant(design, im[1]), tb, wd, f"m{im[0]}"), enumerate(muts)))
    res = {"killed": 0, "survived": 0, "invalid": 0, "survivors": []}
    for m, o in zip(muts, outcomes):
        res[o] += 1
        if o == "survived":
            res["survivors"].append(f"line {m.line}: {m.description}")
    return res


def main(argv) -> int:
    ids = argv or sorted(p.name[3:-2] for p in HERE.glob("tb_*.v"))
    for pid in ids:
        if not (ARTIFACTS / f"{pid}_design.sv").exists():
            print(f"{pid}: no saved design")
            continue
        r = sweep(pid)
        valid = r["killed"] + r["survived"]
        print(f"{pid}: reference caught {r['killed']}/{valid} injected bugs ({r['invalid']} invalid mutants skipped)", flush=True)
        for s in r["survivors"]:
            print(f"    survived: {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
