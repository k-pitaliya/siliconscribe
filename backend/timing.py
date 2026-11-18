"""Pre-layout timing and mapped area: Yosys maps the RTL to real cells, OpenSTA times the netlist.

    RTL --yosys (sky130 liberty)--> gate netlist --OpenSTA--> slack at the target clock, area

What the numbers are, and are not (the UI repeats this):
  * one typical corner (sky130_fd_sc_hd, tt, 25 C, 1.8 V);
  * no placement or routing, so no wire delay; an ideal clock; zero input/output delays;
  * setup (max-delay) analysis only: hold needs a real clock tree to mean anything.
So this is an early estimate that answers "is this logic anywhere near the target clock?", not
sign-off. When a tool or the library is missing, or the design is something this estimate cannot
time honestly (latches, tri-states, loops, derived clocks), the report says so; it never invents a
number and it never reports a verdict for logic it did not actually time.

Checked, not assumed (backend/tools/verify_mapping.py, tests/test_timing.py):
  * the mapped netlist is simulated against the same testbench as the RTL and must agree;
  * area and cell count are recomputed from the written netlist and the liberty file;
  * the design is flattened, so area covers every sub-module, not just the top one;
  * clocks are read from the mapped netlist (what the flip-flops are really wired to), not guessed
    from port names;
  * parameters the testbench overrides are applied, so the circuit timed is the circuit simulated.
"""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from models import TimingReport
from simulator import clean_env, sandbox_violations

logger = logging.getLogger("siliconscribe.timing")

LIBERTY = Path(__file__).resolve().parent / "pdk" / "sky130hd_tt.lib"
LIBRARY_NAME = "sky130_fd_sc_hd, typical corner (25 C, 1.8 V)"
NOTE = ("Pre-layout estimate on one typical corner: no wire delay, ideal clock, zero I/O delays, "
        "setup analysis only. Not sign-off timing.")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DONT_USE = "sky130_fd_sc_hd__lpflow_*"      # low-power isolation cells are not ordinary logic gates
_CELL_PREFIX = "sky130_fd_sc_hd__"
MAX_CELL_TYPES = 8
MAX_PARAMETER_VALUE = 1024                   # a testbench value larger than this is ignored, not synthesized

_AREA_RE = re.compile(r"Chip area for (?:top )?module '[^']*':\s*([0-9.]+)")
_SEQ_AREA_RE = re.compile(r"used for sequential elements:\s*([0-9.]+)")
_CELL_LINE_RE = re.compile(r"^\s*(\d+)\s+([0-9.]+)\s+(sky130_\w+)\s*$", re.M)
_SLACK_RE = re.compile(r"^worst slack max\s+(-?[0-9.]+)", re.M)
_LOOP_RE = re.compile(r"^\S+\s+\S+\s+\S+\s+loop\s*$", re.M)      # `report_disabled_edges`: "_0_ B X loop"

# Netlist as written by Yosys: "  <cell type> <instance> (\n    .PIN(net), ...\n  );"
_INSTANCE_RE = re.compile(r"^\s*(\\?\S+)\s+\\?\S+\s*\(\s*\n(.*?)\n\s*\);", re.M | re.S)
_CLK_PIN_RE = re.compile(r"\.CLK(?:_N)?\(\s*([^()]*?)\s*\)")
_INPUT_RE = re.compile(r"^\s*input\s+(\[[^\]]*\]\s*)?(\\?[^\s;]+)\s*;", re.M)
_FLOP_PREFIXES = ("df", "sdf", "edf")
_LATCH_RE = re.compile(r"^dl[xr]")                                # dlxtp, dlxtn, dlrtp ... (not dlclkp / dly*)
_GATE_PREFIXES = ("dlclkp", "sdlclkp")


def missing_requirements() -> List[str]:
    """What is needed and absent; empty when timing can run."""
    missing = []
    if shutil.which("yosys") is None:
        missing.append("Yosys")
    if shutil.which("sta") is None:
        missing.append("OpenSTA")
    if not LIBERTY.exists():
        missing.append("the sky130 cell library (see backend/pdk/README.md)")
    return missing


def _env() -> dict:
    env = clean_env()
    if "HOME" in os.environ:          # the yosys/sta shims and the WebAssembly cache live under HOME
        env["HOME"] = os.environ["HOME"]
    return env


def _run(cmd: List[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL, env=_env())


def _target(value) -> float:
    """The clock target in MHz; anything missing, non-numeric or outside 1..10000 means the 100 MHz default."""
    try:
        t = float(value)
    except (TypeError, ValueError):
        return 100.0
    return t if math.isfinite(t) and 1.0 <= t <= 10000.0 else 100.0


def parse_mapped_stats(text: str) -> dict:
    """Area and cell counts from `stat -liberty` (written to a file by `tee -o`)."""
    out: dict = {}
    areas = _AREA_RE.findall(text)
    if areas:
        out["area_um2"] = round(float(areas[-1]), 3)           # the last line is the whole design's total
    seq = _SEQ_AREA_RE.findall(text)
    if seq:
        out["sequential_area_um2"] = round(float(seq[-1]), 3)
    cells = [(name.replace(_CELL_PREFIX, ""), int(n), float(a)) for n, a, name in _CELL_LINE_RE.findall(text)]
    if cells:
        cells.sort(key=lambda c: (-c[1], c[0]))
        out["cell_count"] = sum(c[1] for c in cells)
        out["cells"] = [[name, n] for name, n, _ in cells[:MAX_CELL_TYPES]]
        out["flip_flops"] = sum(n for name, n, _ in cells if name.startswith(_FLOP_PREFIXES))
    return out


def analyze_netlist(text: str) -> dict:
    """What the mapped netlist really contains: which input ports clock the flip-flops, whether
    anything was left unmapped (for example tri-state buffers), latches, clock gates."""
    clock_nets: set = set()
    unmapped: List[str] = []
    flip_flops = latches = gates = 0
    for cell, body in _INSTANCE_RE.findall(text):
        cell = cell.lstrip("\\")
        if not cell.startswith(_CELL_PREFIX):
            if cell not in unmapped:
                unmapped.append(cell)
            continue
        short = cell[len(_CELL_PREFIX):]
        if short.startswith(_FLOP_PREFIXES):
            flip_flops += 1
            m = _CLK_PIN_RE.search(body)
            if m:
                clock_nets.add(m.group(1).strip().lstrip("\\"))
        elif _LATCH_RE.match(short):
            latches += 1
        elif short.startswith(_GATE_PREFIXES):
            gates += 1
    scalar_inputs = {m.group(2).lstrip("\\") for m in _INPUT_RE.finditer(text) if not m.group(1)}
    return {"clock_nets": clock_nets, "unmapped": unmapped, "flip_flops": flip_flops, "latches": latches,
            "gates": gates, "scalar_inputs": scalar_inputs}


def _declared_parameter_names(rtl_code: Optional[str], module_name: str) -> Optional[List[Optional[str]]]:
    """Names of the design's own `module <name> #( ... )` parameter list, in declaration order.
    None where a piece has no name; None overall when the header has no `#(` parameter list."""
    src = rtl_code or ""
    m = re.search(rf"\bmodule\s+{re.escape(module_name)}\s*#\s*\(", src)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(src) and depth:
        depth += (src[i] == "(") - (src[i] == ")")
        i += 1
    if depth:                                   # unbalanced: give up
        return None
    names: List[Optional[str]] = []
    cur, depth = "", 0
    for ch in src[m.end():i - 1] + ",":
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            nm = re.search(r"([A-Za-z_]\w*)\s*$", cur.split("=", 1)[0])
            names.append(nm.group(1) if nm else None)
            cur = ""
        else:
            cur += ch
    return names


def parameter_overrides(testbench_code: Optional[str], module_name: str,
                        rtl_code: Optional[str] = None) -> Tuple[Dict[str, int], bool]:
    """Integer parameter overrides the testbench gives the design under test, e.g. `mux #(.WIDTH(16)) dut`
    or positional `alu #(8) dut` (mapped in order to the parameters declared in *rtl_code*).

    Returns ({name: value}, some_were_skipped). Only plain decimal numbers are used; an expression is
    never guessed at (it is reported as skipped instead)."""
    tb = testbench_code or ""
    m = re.search(rf"\b{re.escape(module_name)}\s*#\s*\(", tb)
    if not m:
        return {}, False
    depth, i = 1, m.end()
    while i < len(tb) and depth:
        depth += (tb[i] == "(") - (tb[i] == ")")
        i += 1
    if depth:                                   # unbalanced: give up quietly
        return {}, False
    parts, cur, depth = [], "", 0
    for ch in tb[m.end():i - 1]:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    declared = _declared_parameter_names(rtl_code, module_name)
    found: Dict[str, int] = {}
    skipped = False
    for index, part in enumerate(p.strip() for p in parts):
        if not part:
            continue
        mm = re.fullmatch(r"\.(\w+)\s*\(\s*(\d+)\s*\)", part)
        if mm and int(mm.group(2)) <= MAX_PARAMETER_VALUE:
            found[mm.group(1)] = int(mm.group(2))
        elif (not part.startswith(".") and declared and index < len(declared) and declared[index]
              and re.fullmatch(r"[0-9]+", part) and int(part) <= MAX_PARAMETER_VALUE):
            found[declared[index]] = int(part)
        else:
            skipped = True
    return found, skipped


def parse_sta(text: str, period_ns: float) -> dict:
    """Worst setup slack and the path it belongs to, from OpenSTA's report."""
    out: dict = {}
    m = _SLACK_RE.search(text)
    if m:
        slack = float(m.group(1))
        out["slack_ns"] = round(slack, 4)
        out["met"] = slack >= 0
        used = period_ns - slack
        if used > 0:
            out["fmax_mhz"] = round(1000.0 / used, 1)
    # The path blocks: pick the one with the smallest slack (that is the critical path).
    worst = None
    for block in text.split("Startpoint:")[1:]:
        s = re.search(r"(-?[0-9.]+)\s+slack \((MET|VIOLATED)\)", block)
        e = re.search(r"Endpoint:\s*(\S+)", block)
        a = re.search(r"(-?[0-9.]+)\s+data arrival time", block)
        if not (s and e):
            continue
        cand = (float(s.group(1)), block.split()[0], e.group(1), float(a.group(1)) if a else None)
        if worst is None or cand[0] < worst[0]:
            worst = cand
    if worst:
        out["critical_start"], out["critical_end"], out["critical_delay_ns"] = worst[1], worst[2], worst[3]
    return out


def sta_errors(text: str) -> List[str]:
    """OpenSTA's error lines only. Warnings (activity propagation, command abbreviation ...) are noise."""
    return [ln.strip() for ln in text.splitlines() if ln.lower().startswith("error")][:2]


def _map_with_yosys(work_dir: Path, module_name: str, params: Dict[str, int]) -> subprocess.CompletedProcess:
    for stale in ("stat.txt", "netlist.v"):
        (work_dir / stale).unlink(missing_ok=True)
    lib = str(LIBERTY)
    chparam = "".join(f" -chparam {k} {v}" for k, v in params.items())      # names are \w+, values are integers
    # `proc; tribuf` first: a tri-state then survives synthesis as an unmappable buffer that we detect and
    # refuse, instead of being quietly optimised into a plain wire. `synth -flatten` makes the area and cell
    # count cover every sub-module. Yosys' console output is cut short after ABC in the WebAssembly build, so
    # the statistics go to a file (`tee -o`). Yosys scripts are not Tcl: quote the path with double quotes.
    script = (f'read_verilog -sv design.sv; hierarchy -check -top {module_name}{chparam}; proc; tribuf; '
              f'synth -flatten -top {module_name}; '
              f'dfflibmap -liberty "{lib}" -dont_use {_DONT_USE}; abc -liberty "{lib}" -dont_use {_DONT_USE}; '
              f'opt_clean; tee -o stat.txt stat -liberty "{lib}"; write_verilog -noattr netlist.v')
    return _run(["yosys", "-q", "-p", script], work_dir, 90)


def _constraints(clocks: List[str], period: float) -> str:
    if not clocks:   # purely combinational: time input-to-output paths against a virtual clock
        return (f"create_clock -name clk -period {period}\n"
                "set_input_delay 0 -clock clk [all_inputs]\n"
                "set_output_delay 0 -clock clk [all_outputs]\n")
    lines = [f"create_clock -name {c} -period {period} [get_ports {{{c}}}]" for c in clocks]
    if len(clocks) > 1:     # separate domains: a crossing is not a single-clock path, so it is not timed
        lines.append("set_clock_groups -asynchronous " + " ".join(f"-group [get_clocks {{{c}}}]" for c in clocks))
    lines += [f"set_input_delay 0 -clock {clocks[0]} [all_inputs -no_clocks]",
              f"set_output_delay 0 -clock {clocks[0]} [all_outputs]"]
    return "\n".join(lines) + "\n"


def run_timing(rtl_code: str, module_name: str, work_dir: Path, target_mhz: Optional[float] = None,
               testbench_code: Optional[str] = None) -> TimingReport:
    """Map *rtl_code* to sky130 cells and time it at *target_mhz* (default 100). Never raises.

    *testbench_code* is only read for numeric parameter overrides of the design under test, named
    (`#(.WIDTH(16))`) or positional (`#(16)`, matched in order to the parameters the design declares)."""
    started = time.time()
    target = _target(target_mhz)
    period = round(1000.0 / target, 4)
    base = dict(target_mhz=target, period_ns=period, library=LIBRARY_NAME, note=NOTE)

    def report(**kw) -> TimingReport:
        merged = {**base, **kw}
        return TimingReport(seconds=round(time.time() - started, 2), **merged)

    missing = missing_requirements()
    if missing:
        return report(available=False, error="Timing needs " + ", ".join(missing) + ".")
    if not _MODULE_RE.match(module_name or ""):
        return report(available=False, error="Invalid module name.")
    blocked = sandbox_violations(rtl_code)
    if blocked:
        return report(available=False, error="Source not timed: " + "; ".join(blocked[:3]))
    if len(rtl_code.encode("utf-8")) > 200 * 1024:
        return report(available=False, error="RTL exceeds the 200 KB limit.")

    try:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "design.sv").write_text(rtl_code)

        # The circuit we time must be the circuit that was simulated: apply the testbench's numeric overrides.
        wanted, skipped = parameter_overrides(testbench_code, module_name, rtl_code)
        params = {k: v for k, v in wanted.items() if re.search(rf"\b{k}\b", rtl_code)}
        skipped = skipped or len(params) != len(wanted)
        y = _map_with_yosys(work_dir, module_name, params)
        if params and not ((work_dir / "netlist.v").exists() and (work_dir / "stat.txt").exists()):
            params, skipped = {}, True              # Yosys rejected an override: time the design as declared
            y = _map_with_yosys(work_dir, module_name, {})
        if not ((work_dir / "netlist.v").exists() and (work_dir / "stat.txt").exists()):
            detail = ((y.stderr or "") + (y.stdout or "")).strip()[-300:]
            return report(available=True, error="The design could not be mapped to cells (not synthesizable as written)."
                          + (f" {detail}" if detail else ""))
        note = NOTE
        if params:
            note += " Parameters taken from the testbench: " + ", ".join(f"{k}={v}" for k, v in params.items()) + "."
        if skipped:
            note += " Testbench parameter values that are not plain numbers, or that name no parameter of the design, were not applied."
        base["note"] = note

        stats = parse_mapped_stats((work_dir / "stat.txt").read_text())
        net = analyze_netlist((work_dir / "netlist.v").read_text())

        # Refuse rather than report a verdict for logic that was not actually timed.
        if net["unmapped"]:
            return report(available=True, error="The design contains logic that is not mapped to library cells "
                          "(for example tri-state buffers), so it cannot be timed.")
        if not stats.get("cell_count"):
            return report(available=True, error="The design maps to no logic cells (only wires or constants), "
                          "so there is nothing to time.")
        if net["latches"]:
            return report(available=True, error="The design contains latches; timing of latch-based logic is not estimated.", **stats)
        clocks = sorted(net["clock_nets"])
        bad = [c for c in clocks if c not in net["scalar_inputs"] or not _MODULE_RE.match(c)]
        if bad or net["gates"]:
            names = ", ".join(bad[:2]) or "a clock-gating cell"
            return report(available=True, error=f"The design is clocked by a derived or gated signal ({names}), not directly "
                          "by an input port; only designs clocked by input ports are timed.", **stats)
        if len(clocks) > 1:
            base["note"] += (f" {len(clocks)} clocks ({', '.join(clocks)}): each is timed at the target; "
                             "paths between clocks are not timed.")

        (work_dir / "timing.tcl").write_text(
            f"read_liberty {{{LIBERTY}}}\nread_verilog netlist.v\nlink_design {module_name}\n" + _constraints(clocks, period) +
            "report_checks -path_delay max -format full -digits 4\nreport_worst_slack -max -digits 4\n"
            "puts \"DISABLED_EDGES\"\nreport_disabled_edges\n")
        s = _run(["sta", "-no_init", "-no_splash", "-exit", "timing.tcl"], work_dir, 60)
        sta_out = (s.stdout or "") + (s.stderr or "")
        if _LOOP_RE.search(sta_out.split("DISABLED_EDGES")[-1]):
            return report(available=True, error="The design contains a combinational loop, so path timing is not defined.", **stats)
        timing = parse_sta(sta_out, period)
        result = report(available=True, clock=", ".join(clocks) if clocks else "virtual (combinational design)",
                        **stats, **timing)
        if "slack_ns" not in timing:
            errs = sta_errors(sta_out)
            result.error = "OpenSTA reported no constrained path." + (" " + " ".join(errs) if errs else "")
        return result
    except subprocess.TimeoutExpired:
        return report(available=True, error="Timing analysis timed out.")
    except Exception:
        logger.exception("timing failed")
        return report(available=True, error="Timing analysis failed.")


def timing_message(r: TimingReport) -> str:
    if not r.available or r.slack_ns is None:
        return f"Timing: {r.error or 'not available'}"
    verdict = "meets" if r.met else "misses"
    fmax = f", max about {r.fmax_mhz:g} MHz" if r.fmax_mhz else ""
    area = f"; {r.area_um2:g} um^2 in {r.cell_count} cells" if r.area_um2 else ""
    return f"Timing: {verdict} {r.target_mhz:g} MHz (slack {r.slack_ns:+.2f} ns{fmax}){area}."
