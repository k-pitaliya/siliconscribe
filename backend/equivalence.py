"""Formal equivalence of the RTL and its sky130-mapped netlist, with Yosys' built-in SAT solver.

The timing stage maps the RTL to sky130 cells (netlist.v). This module proves that the mapped netlist computes the
same function as the RTL, so the timing and area numbers describe the design that was simulated:

* Combinational designs: a miter of RTL ("gold") and netlist ("gate") is handed to `sat -prove`. A pass is a proof
  over every possible input value (inputs are restricted to real 0/1 values; X is not a hardware input).
* Sequential designs: `equiv_make` pairs the registers of both designs by name and `equiv_induct` tries to prove
  every pair by temporal induction. When synthesis re-encodes state (for example an FSM), registers no longer pair
  up and induction cannot decide: that is reported as "not proven", never as a pass or a failure.

The netlist cells are read from the liberty file's own logic functions (read_liberty), so the proof is about the
real cells, not about a hand-written model of them. No external solver is needed.
"""
import re
import subprocess
from pathlib import Path
from typing import Dict, Optional

# Register cells in sky130_fd_sc_hd: flip-flops (df*, edf*, sdf*). A netlist with none of them is combinational.
_SEQ_CELL_RE = re.compile(r"\bsky130_fd_sc_hd__(?:df|edf|sdf)\w*")
_POINTS_RE = re.compile(r"Of those cells (\d+) are proven and (\d+) are unproven\.")


def _script(module: str, liberty: str, params: Dict[str, int], sequential: bool) -> str:
    chparam = "".join(f" -chparam {k} {v}" for k, v in params.items())   # same overrides the netlist was mapped with
    # `memory`: arrays and lookup tables become plain logic and registers, as synthesis does (SAT cannot model
    # memory initialisation directly).
    gold = (f"read_verilog -sv design.sv; hierarchy -check -top {module}{chparam}; proc; flatten; memory; opt; opt_clean; "
            f"rename {module} gold; design -stash gold; ")
    # -ignore_miss_func: the library also has cells without a logic function (clock gates, fills); none is used.
    gate = (f'read_liberty -ignore_miss_func "{liberty}"; read_verilog netlist.v; hierarchy -top {module}; '
            f"flatten; opt_clean; rename {module} gate; design -stash gate; ")
    load = "design -copy-from gold -as gold gold; design -copy-from gate -as gate gate; "
    if sequential:
        check = ("equiv_make gold gate equiv; hierarchy -top equiv; async2sync; "
                 "equiv_simple -seq 5; equiv_induct -seq 5; equiv_status")
    else:
        check = ("miter -equiv -flatten -make_assert -ignore_gold_x gold gate miter; hierarchy -top miter; "
                 "sat -prove-asserts -set-def-inputs -enable_undef miter")
    return gold + gate + load + check


def interpret(output: str, sequential: bool) -> dict:
    """Yosys output -> {status, method}. status: proven | different | not_proven | None (could not run)."""
    if sequential:
        m = _POINTS_RE.findall(output)
        if not m:
            return {"status": None, "method": "The equivalence check could not be run on this design."}
        proven, unproven = (int(x) for x in m[-1])
        total = proven + unproven
        if total and unproven == 0:
            return {"status": "proven", "method": f"temporal induction: all {total} register and output points proven"}
        return {"status": "not_proven",
                "method": (f"temporal induction proved {proven} of {total} points; the rest could not be decided "
                           "(usually because synthesis re-encoded the state, for example an FSM)")}
    if "SUCCESS!" in output:
        return {"status": "proven", "method": "SAT proof over every input value"}
    if "FAIL!" in output:
        return {"status": "different", "method": "SAT found input values where the netlist and the RTL disagree"}
    return {"status": None, "method": "The equivalence check could not be run on this design."}


_CLK_PIN_RE = re.compile(r"\.(CLK_N|CLK)\(\s*\\?([A-Za-z_][\w$]*)")
# Any reg/logic/bit declaration with an initialiser (also "reg [3:0] a, s = 5;" and "logic s = 5;"), and initial blocks
# (self-review verification: those forms were still "proven"). Bounded so the scan stays linear.
_DECL_INIT_RE = re.compile(r"\b(?:reg|logic|bit)\b[^;=()]{0,200}=(?!=)|\binitial\b")


def _sequential_limits(rtl: str, netlist: str) -> Optional[str]:
    """Reasons the sequential proof must not say "proven" (self-review findings, both reproduced):

    * equiv_induct treats every flip-flop as ticking on the same step, so a netlist whose flip-flop used the OTHER clock
      edge was "proven". Each flip-flop's edge in the netlist is checked against the RTL's `posedge`/`negedge` uses.
    * A register given a declaration value (`reg [3:0] s = 5;`) starts at that value in simulation but not in the
      netlist (x at power-up), yet the proof passed. Such designs depend on power-up values: not proven.
    """
    code = re.sub(r"//[^\n]*|/\*.*?\*/", " ", rtl, flags=re.S)
    if _DECL_INIT_RE.search(code):
        return ("not proven: a register gets a starting value from its declaration or an initial block (for example "
                "reg q = 0), which simulation uses but the netlist does not keep at power-up; reset it explicitly instead")
    for pin, net in set(_CLK_PIN_RE.findall(netlist)):
        edge = "negedge" if pin == "CLK_N" else "posedge"
        if not re.search(rf"\b{edge}\s+{re.escape(net)}\b", code):
            return (f"not proven: a netlist flip-flop is clocked on the {edge.replace('edge', ' edge')} of {net}, which "
                    "the RTL does not use; the proof treats all flip-flops as ticking together, so it cannot decide this")
    if len({net for _, net in _CLK_PIN_RE.findall(netlist)}) > 1:
        return ("not proven: more than one clock; the proof treats all flip-flops as ticking together, which only holds "
                "for a single clock")
    return None


def prove_equivalence(work_dir: Path, module: str, liberty: str, params: Optional[Dict[str, int]] = None,
                      env: Optional[dict] = None, timeout: int = 20) -> dict:
    """Run the proof in `work_dir` (which holds design.sv and netlist.v from the timing stage)."""
    work_dir = Path(work_dir)
    netlist = (work_dir / "netlist.v").read_text()
    sequential = bool(_SEQ_CELL_RE.search(netlist))
    try:
        from simulator import run_tool      # kills the whole process group on timeout
        p = run_tool(["yosys", "-p", _script(module, liberty, params or {}, sequential)], timeout, cwd=str(work_dir),
                     capture_output=True, text=True, env=env)
    except subprocess.TimeoutExpired:
        return {"status": None, "method": f"The proof did not finish within {timeout} s, so it was stopped", "sequential": sequential}
    except FileNotFoundError:
        return {"status": None, "method": "Yosys is not installed, so the proof could not run", "sequential": sequential}
    out = interpret((p.stdout or "") + (p.stderr or ""), sequential)
    out["sequential"] = sequential
    if sequential and out["status"] == "proven":
        try:
            limit = _sequential_limits((work_dir / "design.sv").read_text(), netlist)
        except OSError:
            limit = None
        if limit:
            out["status"], out["method"] = "not_proven", limit
    return out
