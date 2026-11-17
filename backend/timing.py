"""Pre-layout timing and mapped area: Yosys maps the RTL to real cells, OpenSTA times the netlist.

    RTL --yosys (sky130 liberty)--> gate netlist --OpenSTA--> slack at the target clock, area, power

What the numbers are, and are not (the UI repeats this):
  * one typical corner (sky130_fd_sc_hd, tt, 25 C, 1.8 V);
  * no placement or routing, so no wire delay; an ideal clock; zero input/output delays;
  * setup (max-delay) analysis only: hold needs a real clock tree to mean anything.
So this is an early estimate that answers "is this logic anywhere near the target clock?", not
sign-off. When a tool or the library is missing the report says so; it never invents a number.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import List, Optional

from models import TimingReport
from simulator import clean_env, sandbox_violations
from vcd_parser import _CLOCK_RE, ports_from_rtl

logger = logging.getLogger("siliconscribe.timing")

LIBERTY = Path(__file__).resolve().parent / "pdk" / "sky130hd_tt.lib"
LIBRARY_NAME = "sky130_fd_sc_hd, typical corner (25 C, 1.8 V)"
NOTE = ("Pre-layout estimate on one typical corner: no wire delay, ideal clock, zero I/O delays, "
        "setup analysis only. Not sign-off timing.")
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DONT_USE = "sky130_fd_sc_hd__lpflow_*"      # low-power isolation cells are not ordinary logic gates
MAX_CELL_TYPES = 8

_AREA_RE = re.compile(r"Chip area for module '[^']*':\s*([0-9.]+)")
_SEQ_AREA_RE = re.compile(r"used for sequential elements:\s*([0-9.]+)")
_CELL_LINE_RE = re.compile(r"^\s*(\d+)\s+([0-9.]+)\s+(sky130_\w+)\s*$", re.M)
_SLACK_RE = re.compile(r"^worst slack max\s+(-?[0-9.]+)", re.M)
_POWER_RE = re.compile(r"^Total\s+\S+\s+\S+\s+\S+\s+([0-9.eE+-]+)", re.M)


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


def find_clock(rtl_code: str) -> Optional[str]:
    """Name of the design's clock input, if it has one."""
    for name, direction in ports_from_rtl(rtl_code).items():
        if direction == "input" and _CLOCK_RE.match(name):
            return name
    return None


def parse_mapped_stats(text: str) -> dict:
    """Area and cell counts from `stat -liberty` (written to a file by `tee -o`)."""
    out: dict = {}
    m = _AREA_RE.search(text)
    if m:
        out["area_um2"] = round(float(m.group(1)), 3)
    m = _SEQ_AREA_RE.search(text)
    if m:
        out["sequential_area_um2"] = round(float(m.group(1)), 3)
    cells = [(name.replace("sky130_fd_sc_hd__", ""), int(n), float(a)) for n, a, name in _CELL_LINE_RE.findall(text)]
    if cells:
        cells.sort(key=lambda c: (-c[1], c[0]))
        out["cell_count"] = sum(c[1] for c in cells)
        out["cells"] = [[name, n] for name, n, _ in cells[:MAX_CELL_TYPES]]
        out["flip_flops"] = sum(n for name, n, _ in cells if name.startswith(("df", "sdf", "edf")))
    return out


def parse_sta(text: str, period_ns: float) -> dict:
    """Worst setup slack, the path it belongs to, and total power from OpenSTA's report."""
    out: dict = {}
    m = _SLACK_RE.search(text)
    if m:
        slack = float(m.group(1))
        out["slack_ns"] = round(slack, 3)
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
    m = _POWER_RE.search(text)
    if m:
        try:
            out["power_mw"] = round(float(m.group(1)) * 1000.0, 4)
        except ValueError:
            pass
    return out


def run_timing(rtl_code: str, module_name: str, work_dir: Path, target_mhz: Optional[float] = None) -> TimingReport:
    """Map *rtl_code* to sky130 cells and time it at *target_mhz* (default 100). Never raises."""
    target = float(target_mhz) if target_mhz and target_mhz > 0 else 100.0
    period = round(1000.0 / target, 4)
    base = dict(target_mhz=target, period_ns=period, library=LIBRARY_NAME, note=NOTE)
    missing = missing_requirements()
    if missing:
        return TimingReport(available=False, error="Timing needs " + ", ".join(missing) + ".", **base)
    if not _MODULE_RE.match(module_name or ""):
        return TimingReport(available=False, error="Invalid module name.", **base)
    blocked = sandbox_violations(rtl_code)
    if blocked:
        return TimingReport(available=False, error="Source not timed: " + "; ".join(blocked[:3]), **base)
    if len(rtl_code.encode("utf-8")) > 200 * 1024:
        return TimingReport(available=False, error="RTL exceeds the 200 KB limit.", **base)

    started = time.time()
    try:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "design.sv").write_text(rtl_code)
        for stale in ("stat.txt", "netlist.v"):
            (work_dir / stale).unlink(missing_ok=True)
        lib = str(LIBERTY)
        # Yosys' console output is cut short after ABC in the WebAssembly build, so the statistics
        # go to a file (`tee -o`) instead of being read from stdout.
        # Yosys scripts are not Tcl: quote the path with double quotes (braces would be literal).
        script = (f'read_verilog -sv design.sv; hierarchy -check -top {module_name}; synth -top {module_name}; '
                  f'dfflibmap -liberty "{lib}" -dont_use {_DONT_USE}; abc -liberty "{lib}" -dont_use {_DONT_USE}; '
                  f'opt_clean; tee -o stat.txt stat -liberty "{lib}"; write_verilog -noattr netlist.v')
        y = _run(["yosys", "-q", "-p", script], work_dir, 90)
        if not (work_dir / "netlist.v").exists() or not (work_dir / "stat.txt").exists():
            detail = ((y.stderr or "") + (y.stdout or "")).strip()[-300:]
            return TimingReport(available=True, error="The design could not be mapped to cells (not synthesizable as written)."
                                + (f" {detail}" if detail else ""), **base)
        stats = parse_mapped_stats((work_dir / "stat.txt").read_text())

        clock = find_clock(rtl_code)
        if clock:
            clocking = (f"create_clock -name clk -period {period} [get_ports {{{clock}}}]\n"
                        "set_input_delay 0 -clock clk [all_inputs -no_clocks]\n"
                        "set_output_delay 0 -clock clk [all_outputs]\n")
        else:   # purely combinational: time input-to-output paths against a virtual clock
            clocking = (f"create_clock -name clk -period {period}\n"
                        "set_input_delay 0 -clock clk [all_inputs]\n"
                        "set_output_delay 0 -clock clk [all_outputs]\n")
        (work_dir / "timing.tcl").write_text(
            f"read_liberty {{{lib}}}\nread_verilog netlist.v\nlink_design {module_name}\n" + clocking +
            "report_checks -path_delay max -format full\nreport_worst_slack -max\nreport_power\n")
        s = _run(["sta", "-no_init", "-no_splash", "-exit", "timing.tcl"], work_dir, 60)
        sta_out = (s.stdout or "") + (s.stderr or "")
        timing = parse_sta(sta_out, period)
        report = TimingReport(available=True, clock=clock or "virtual (combinational design)",
                              seconds=round(time.time() - started, 2), **base, **stats, **timing)
        if "slack_ns" not in timing:
            errs = [ln for ln in sta_out.splitlines() if ln.lower().startswith(("error", "warning"))][:2]
            report.error = "OpenSTA reported no constrained path." + (" " + " ".join(errs) if errs else "")
        return report
    except subprocess.TimeoutExpired:
        return TimingReport(available=True, error="Timing analysis timed out.", **base)
    except Exception:
        logger.exception("timing failed")
        return TimingReport(available=True, error="Timing analysis failed.", **base)


def timing_message(r: TimingReport) -> str:
    if not r.available or r.slack_ns is None:
        return f"Timing: {r.error or 'not available'}"
    verdict = "meets" if r.met else "misses"
    fmax = f", max about {r.fmax_mhz:g} MHz" if r.fmax_mhz else ""
    area = f"; {r.area_um2:g} um^2 in {r.cell_count} cells" if r.area_um2 else ""
    return f"Timing: {verdict} {r.target_mhz:g} MHz (slack {r.slack_ns:+.2f} ns{fmax}){area}."
