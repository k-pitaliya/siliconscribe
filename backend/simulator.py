"""
Icarus-Verilog simulation engine.

Single, robust simulation path:
  write files -> ensure VCD dump -> iverilog compile -> vvp run -> parse results.

Compile errors, runtime errors, timeouts, and test failures are all surfaced as
a structured SimulationResult. The self-correction loop (orchestrator.py) feeds
ERROR/FAIL results back to the LLM, so we deliberately do NOT try to "repair"
SystemVerilog with regex here — that job belongs to the model.
"""

import os
import subprocess
import re
import shutil
import threading
from pathlib import Path
from typing import Tuple, Optional, List

from checks import parse_checks
from vcd_parser import toggle_coverage
from models import SimulationResult, SimError

VCD_FILENAME = "design.vcd"
_PORT_WIDTH_RE = re.compile(r"Port \d+ \(\w+\) of \w+ expects \d+ bits, got \d+")
LOG_FILENAME = "transcript.log"

# --- Hardening constants ---
DESIGN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
MAX_CODE_BYTES = 200 * 1024  # 200 KB


# --- Sandbox policy ----------------------------------------------------------
# Generated (or user-edited) Verilog is executed by `vvp` with the server's
# privileges. Verilog file-I/O system tasks can read or write ANY path the
# process can reach, so they are rejected before anything is compiled. This is
# defence in depth, not a security boundary: for multi-user deployment run the
# simulator in a container / jail (see report, Limitations).
_FORBIDDEN_TASKS = (
    "fopen", "fclose", "fflush", "fseek", "ftell", "rewind", "ungetc",
    "fwrite", "fwriteb", "fwriteh", "fwriteo",
    "fdisplay", "fdisplayb", "fdisplayh", "fdisplayo",
    "fstrobe", "fstrobeb", "fstrobeh", "fstrobeo",
    "fmonitor", "fmonitorb", "fmonitorh", "fmonitoro",
    "fgets", "fgetc", "fscanf", "fread",
    "readmemh", "readmemb", "writememh", "writememb",
    "system", "sdf_annotate", "dumpports",
)
_FORBIDDEN_RE = re.compile(r"\$(?:" + "|".join(_FORBIDDEN_TASKS) + r")\b")

# A denylist always misses something: Icarus ships many VPI tasks ($fopena, $fputc,
# $ivlh_file_open, ...) that read or write files. Review finding, reproduced live:
# a testbench using $fopena + $fputc wrote a file outside its folder and got PASS.
# So every system task must also be on this ALLOWLIST of side-effect-free tasks.
ALLOWED_SYSTEM_TASKS = frozenset({
    # printing (stdout only)
    "display", "displayb", "displayh", "displayo", "write", "writeb", "writeh", "writeo",
    "strobe", "strobeb", "strobeh", "strobeo", "monitor", "monitorb", "monitorh", "monitoro",
    "monitoron", "monitoroff", "timeformat", "printtimescale",
    # simulation control and severity
    "finish", "stop", "fatal", "error", "warning", "info",
    # time and randomness
    "time", "stime", "realtime", "random", "urandom", "urandom_range",
    # waveform dump (the file name itself is checked separately)
    "dumpfile", "dumpvars", "dumpall", "dumpon", "dumpoff", "dumpflush", "dumplimit",
    # string formatting into a variable (no file access)
    "sformat", "sformatf", "swrite", "swriteb", "swriteh", "swriteo",
    # conversion, math and bit utilities
    "signed", "unsigned", "clog2", "bits", "size", "left", "right", "high", "low",
    "increment", "dimensions", "countones", "onehot", "onehot0", "isunknown",
    "itor", "rtoi", "realtobits", "bitstoreal", "shortrealtobits", "bitstoshortreal",
    "ln", "log10", "exp", "sqrt", "pow", "floor", "ceil", "sin", "cos", "tan",
    "asin", "acos", "atan", "atan2", "hypot", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
    # assertion helpers and scope names
    "rose", "fell", "stable", "changed", "past", "root", "unit",
})
_SYSTEM_TASK_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_$]*)")

# The design under test must not be able to write the verdict the simulator trusts.
_RTL_FORBIDDEN_TOKENS = ("Passed:", "Failed:", "ALL TESTS PASSED", "$finish", "$stop", "$fatal")
_RTL_TB_HIERARCHY_RE = re.compile(r"\btestbench\s*\.")
_INCLUDE_RE = re.compile(r"`\s*include\b")
_DUMPFILE_RE = re.compile(r"\$dumpfile\s*\(\s*(\"[^\"]*\"|[^)]*)\)")
_SAFE_DUMP_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
_SAFE_ENV_KEYS = ("PATH", "LANG", "LC_ALL", "TMPDIR")
# Cap on any single file the simulator may write (transcript / VCD), in the
# units of `ulimit -f` (>= 64 MB). Stops a runaway $display loop filling the disk.
_MAX_OUTPUT_BLOCKS = 131072
# Per-simulation CPU-time and memory caps (the review reproduced a ~1 GB, ~20 s
# testbench inside the old limits). `ulimit -v` is enforced on Linux (the Docker
# image) but not by macOS; the wall-clock timeout and `ulimit -t` apply everywhere.
_MAX_MEMORY_KB = int(os.getenv("SIM_MAX_MEMORY_MB", "1024")) * 1024
_CPU_SECONDS_SLACK = 5
# At most this many compile+simulate jobs at once. Each one is a compiler plus a vvp process under the
# caps above; on a small shared host a burst of requests would otherwise run them all in parallel and
# exhaust memory. Extra requests simply wait their turn (the per-IP rate limit bounds the queue).
_SIM_SLOTS = threading.BoundedSemaphore(max(1, int(os.getenv("SIM_MAX_CONCURRENT", "2"))))


def sandbox_violations(*sources: str) -> List[str]:
    """Return human-readable policy violations found in the given sources.

    The scan is deliberately conservative and does NOT strip comments: a naive
    comment stripper can be fooled by `"//"` inside a string literal into
    hiding a forbidden call, so a forbidden token inside a comment is rejected
    too (false positives are cheap, false negatives are not).
    """
    found: List[str] = []
    for src in sources:
        for m in _FORBIDDEN_RE.finditer(src or ""):
            found.append(f"{m.group(0)} is not allowed (file or process access)")
        if _INCLUDE_RE.search(src or ""):
            found.append("`include is not allowed")
        if "``" in (src or "") or "$`" in (src or ""):
            found.append("macro token pasting is not allowed")
        for m in _DUMPFILE_RE.finditer(src or ""):
            arg = m.group(1).strip()
            if len(arg) < 2 or arg[0] != '"' or arg[-1] != '"':
                found.append("$dumpfile must be given a string literal")
            elif not _SAFE_DUMP_NAME_RE.match(arg[1:-1]):
                found.append("$dumpfile must be a plain file name (no path separators)")
    for src in sources:
        for m in _SYSTEM_TASK_RE.finditer(src or ""):
            name = m.group(1)
            if name not in ALLOWED_SYSTEM_TASKS and not _FORBIDDEN_RE.fullmatch("$" + name):
                found.append(f"${name} is not an allowed system task")
    seen, out = set(), []
    for v in found:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def rtl_integrity_violations(rtl: str) -> List[str]:
    """Reject RTL that could forge the testbench's verdict or end the run itself.

    Review finding (all reproduced): a DUT whose ``initial`` block prints
    ``Passed: 200 / Failed: 0 / ALL TESTS PASSED`` (optionally followed by $finish at
    t=0) was reported as PASS. Real RTL has no business printing the summary lines,
    ending the simulation, or reaching into the testbench hierarchy.
    """
    found = [f"RTL must not contain {tok!r} (it could forge the test verdict)"
             for tok in _RTL_FORBIDDEN_TOKENS if tok in (rtl or "")]
    if _RTL_TB_HIERARCHY_RE.search(rtl or ""):
        found.append("RTL must not reference the testbench hierarchy (testbench.*)")
    return found


def _policy_violations(rtl_code: str, testbench_code: str) -> List[str]:
    return sandbox_violations(rtl_code, testbench_code) + rtl_integrity_violations(rtl_code)


def clean_env() -> dict:
    """Minimal environment for EDA subprocesses: API keys never reach them."""
    env = {k: os.environ[k] for k in _SAFE_ENV_KEYS if k in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def _validate_design_id(design_id: str) -> None:
    """Validate design_id against strict allow-list; raise ValueError on violation."""
    if not isinstance(design_id, str) or not DESIGN_ID_RE.match(design_id):
        raise ValueError(f"Invalid design_id: {design_id!r} must match ^[a-zA-Z0-9_-]{{1,32}}$")
    # Extra defense even though regex excludes these
    if "/" in design_id or "\\" in design_id or ".." in design_id:
        raise ValueError(f"Invalid design_id: {design_id!r} contains illegal path characters")


def ensure_vcd_dump(testbench_code: str, top_module: str = "testbench") -> str:
    """Inject $dumpfile/$dumpvars into a testbench if it has none, so a VCD is
    always produced for the waveform viewer. Best-effort, idempotent."""
    # Idempotent: if either dump primitive exists (any variant), leave untouched
    # to avoid double-injection or breaking a user-supplied dump configuration.
    if "$dumpfile" in testbench_code or "$dumpvars" in testbench_code or "$dumpall" in testbench_code:
        return testbench_code

    dump_block = (
        f'\n    initial begin\n'
        f'        $dumpfile("{VCD_FILENAME}");\n'
        f'        $dumpvars(0, {top_module});\n'
        f'    end\n'
    )

    # Insert right after the first "module <top> ... ;" header.
    match = re.search(r'(\bmodule\b\s+\w+\b[^;]*;)', testbench_code)
    if match:
        idx = match.end()
        return testbench_code[:idx] + dump_block + testbench_code[idx:]

    # Fallback: append (still compiles; dump lives in its own scope).
    # Use append rather than prepend to avoid breaking `timescale directives.
    return testbench_code + dump_block


def _parse_compile_errors(output: str) -> List[SimError]:
    """Parse iverilog diagnostics like 'design.sv:12: error: <msg>'."""
    errors: List[SimError] = []
    for line in output.splitlines():
        m = re.match(r'\s*([^\s:]+):(\d+):\s*(.*)', line)
        if m and ("error" in m.group(3).lower() or "syntax" in m.group(3).lower()):
            errors.append(SimError(file=m.group(1), line=int(m.group(2)), message=m.group(3).strip()))
        elif "error" in line.lower():
            errors.append(SimError(message=line.strip()))
    if not errors and output.strip():
        errors.append(SimError(message=output.strip()[:500]))
    return errors


_SUMMARY_PASSED_RE = re.compile(r"^[ \t]*Passed:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_SUMMARY_FAILED_RE = re.compile(r"^[ \t]*Failed:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
_FAILURE_LINE_RE = re.compile(r"^[ \t]*(?:FAIL|FAILED|ERROR|FATAL)\b", re.MULTILINE)
_FINISH_RE = re.compile(r"\$finish called at (\d+) \((\d+)?(fs|ps|ns|us|ms|s)\)")
_UNIT_TO_NS = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}


def _decide_verdict(log: str, returncode: Optional[int] = None):
    """Decide PASS/FAIL/ERROR from the transcript. Returns (status, passed, failed, notes).

    The testbench prints the summary, so the parser must not trust the first or the
    loosest match. Review findings (all reproduced): taking the FIRST ``Passed:`` anywhere
    let a mid-run phase line or a design-printed line decide the verdict, a ``Failed: x``
    (uninitialised counter) was read as 0, and ``ALL TESTS PASSED`` overrode printed errors.
    Rules now:
      * the summary lines must occupy a whole line, and the LAST pair wins;
      * both counts must be numeric, otherwise the run is an ERROR;
      * any FAIL/ERROR/FATAL line contradicts ``Failed: 0`` and makes the run a FAIL;
      * a run that executed zero checks is not a PASS;
      * a simulator exit code other than 0 (killed by a limit) is not a PASS.
    """
    notes: List[str] = []
    passed_raw = _SUMMARY_PASSED_RE.findall(log)
    failed_raw = _SUMMARY_FAILED_RE.findall(log)
    failure_lines = len(_FAILURE_LINE_RE.findall(log))

    def _num(vals):
        return int(vals[-1]) if vals and vals[-1].isdigit() else None
    passed, failed = _num(passed_raw), _num(failed_raw)

    if passed is None or failed is None:
        notes.append("No valid summary: the testbench must end with whole lines "
                     "'Passed: <number>' and 'Failed: <number>'.")
        return "ERROR", passed or 0, failed or 0, notes
    if failed > 0:
        return "FAIL", passed, failed, notes
    if failure_lines:
        notes.append(f"Summary says 'Failed: 0' but the log contains {failure_lines} "
                     "FAIL/ERROR line(s); treating the run as FAIL.")
        return "FAIL", passed, failure_lines, notes
    if passed == 0:
        notes.append("No checks were executed (Passed: 0), so there is nothing to call a PASS.")
        return "ERROR", 0, 0, notes
    if returncode not in (None, 0):
        notes.append(f"The simulator exited with code {returncode} (killed by a resource limit or crashed).")
        return "ERROR", passed, failed, notes
    return "PASS", passed, failed, notes


def _finish_time_ns(log: str) -> float:
    m = _FINISH_RE.search(log)
    if not m:
        return 0.0
    return float(m.group(1)) * (int(m.group(2)) if m.group(2) else 1) * _UNIT_TO_NS[m.group(3)]


def _excerpt(log: str, head: int = 1000, tail: int = 1500) -> str:
    """Head+tail of the transcript, never just the tail.

    The fixer is told to start from the FIRST failing vector, but a plain tail slice
    dropped it whenever more than ~2500 characters were printed.
    """
    # Passing CHK lines are display data (delivered as structured rows); they would only
    # crowd the failures out of the 2.5 KB the fixer gets to read.
    log = "\n".join(ln for ln in log.splitlines() if not ln.startswith("CHK|PASS|"))
    if len(log) <= head + tail:
        return log
    return f"{log[:head]}\n...[{len(log) - head - tail} characters omitted]...\n{log[-tail:]}"


class IcarusSimulator:
    """Compile + run a design/testbench pair with Icarus Verilog."""

    def __init__(self, workspace: str = "./workspace"):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = 60

    def available(self) -> bool:
        return shutil.which("iverilog") is not None and shutil.which("vvp") is not None

    def _design_dir(self, design_id: str) -> Path:
        _validate_design_id(design_id)
        # Resolve and ensure is_relative_to workspace to block traversal (e.g. design_id crafted
        # to escape via symlink or .. even if regex were bypassed)
        d = (self.workspace / design_id).resolve()
        try:
            # Python 3.9+: Path.is_relative_to
            if not d.is_relative_to(self.workspace):
                raise ValueError(f"Invalid design_id: {design_id!r} escapes workspace")
        except AttributeError:
            # Fallback for older Python: use relative_to with try
            try:
                d.relative_to(self.workspace)
            except ValueError:
                raise ValueError(f"Invalid design_id: {design_id!r} escapes workspace")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_files(self, design_id: str, rtl_code: str, testbench_code: str) -> Tuple[Path, Path]:
        # Input size guard: refuse unreasonably large payloads (200 KB each)
        if len(rtl_code.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError(f"rtl_code exceeds {MAX_CODE_BYTES} bytes limit")
        if len(testbench_code.encode("utf-8")) > MAX_CODE_BYTES:
            raise ValueError(f"testbench_code exceeds {MAX_CODE_BYTES} bytes limit")
        violations = _policy_violations(rtl_code, testbench_code)
        if violations:
            raise ValueError("Rejected by sandbox policy: " + "; ".join(violations))
        design_dir = self._design_dir(design_id)
        rtl_file = design_dir / "design.sv"
        tb_file = design_dir / "testbench.sv"
        # Ensure resolved file paths remain inside workspace (sanitize artifact paths)
        for p in (rtl_file.resolve(), tb_file.resolve()):
            try:
                if not p.is_relative_to(self.workspace):
                    raise ValueError(f"Artifact path escapes workspace: {p}")
            except AttributeError:
                try:
                    p.relative_to(self.workspace)
                except ValueError:
                    raise ValueError(f"Artifact path escapes workspace: {p}")
        rtl_file.write_text(rtl_code)
        tb_file.write_text(ensure_vcd_dump(testbench_code))
        return rtl_file, tb_file

    def compile(self, rtl_file: Path, tb_file: Path, top_module: str = "testbench") -> Tuple[bool, str]:
        output_vvp = rtl_file.parent / f"{top_module}.vvp"
        # A one-line shim compiled FIRST gives every file a default timescale without
        # shifting any line numbers: RTL using `#1` delays compiled before the
        # testbench's own timescale otherwise ran with 1 s delays (false FAIL), and
        # testbenches without a timescale produced a 1 s VCD unit.
        shim = rtl_file.parent / "_timescale.v"
        shim.write_text("`timescale 1ns/1ps\n")
        cmd = ["iverilog", "-o", str(output_vvp), "-g2012", "-Wall",
               str(shim), str(rtl_file), str(tb_file)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                                    cwd=str(rtl_file.parent), env=clean_env())
            output = (result.stderr or "") + (result.stdout or "")
            if result.returncode == 0 and _PORT_WIDTH_RE.search(output):
                # Icarus only WARNS here, but a testbench wire narrower than the DUT
                # port silently hides the upper bits, so a wrong DUT can pass.
                return False, ("ERROR: port width mismatch between the testbench and the design "
                               "(treated as an error because it can hide bugs):\n" + output)
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, "Compilation timeout"
        except FileNotFoundError:
            return False, "Icarus Verilog (iverilog) not installed"

    def run(self, design_id: str, top_module: str = "testbench",
            timeout: Optional[int] = None) -> SimulationResult:
        design_dir = self._design_dir(design_id)
        vvp_file = design_dir / f"{top_module}.vvp"
        vcd_file = design_dir / VCD_FILENAME
        log_file = design_dir / LOG_FILENAME
        if timeout is None:
            timeout = self.timeout_seconds
        # Clamp to sane bounds even if called bypassing Pydantic validation
        if not isinstance(timeout, int) or timeout < 1:
            timeout = 1
        if timeout > 120:
            timeout = 120

        if not vvp_file.exists():
            return SimulationResult(status="ERROR", module_name="",
                                    errors=[SimError(message="Compiled VVP file not found")],
                                    log_excerpt="Compiled VVP file not found")
        try:
            with open(log_file, 'w') as log:
                # `sh -c 'ulimit -f N; exec "$@"'` caps output file size without
                # preexec_fn (which is unsafe in a multi-threaded server).
                # The same wrapper also caps CPU time and (on Linux) memory, and stdin is
                # /dev/null so a stray $stop can never wait for input.
                limits = (f'ulimit -f {_MAX_OUTPUT_BLOCKS} 2>/dev/null; '
                          f'ulimit -t {timeout + _CPU_SECONDS_SLACK} 2>/dev/null; '
                          f'ulimit -v {_MAX_MEMORY_KB} 2>/dev/null; exec "$@"')
                proc = subprocess.run(
                    ["/bin/sh", "-c", limits, "sh", "vvp", str(vvp_file)],
                    cwd=design_dir, stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, timeout=timeout, env=clean_env())
        except subprocess.TimeoutExpired:
            try:  # keep what the testbench printed so the fixer can see where it hung
                tail = log_file.read_text(errors="replace")[-1500:]
            except OSError:
                tail = ""
            msg = f"Simulation exceeded {timeout}s timeout (no $finish reached)."
            return SimulationResult(status="TIMEOUT", module_name="",
                                    simulation_time_ns=timeout * 1000,
                                    errors=[SimError(message=msg)],
                                    log_excerpt=msg + (f"\nLast output:\n{tail}" if tail else ""))
        except FileNotFoundError:
            return SimulationResult(status="ERROR", module_name="",
                                    errors=[SimError(message="vvp runtime not found")],
                                    log_excerpt="vvp runtime not found")

        return self.parse_results(log_file, vcd_file, returncode=proc.returncode)

    def parse_results(self, log_file: Path, vcd_file: Path,
                      returncode: Optional[int] = None) -> SimulationResult:
        try:
            log_content = log_file.read_text(errors="replace")
        except FileNotFoundError:
            return SimulationResult(status="ERROR", module_name="",
                                    log_excerpt="Log file not found")

        status, pass_count, fail_count, notes = _decide_verdict(log_content, returncode)

        errors: List[SimError] = [SimError(message=n) for n in notes]
        if status in ("FAIL", "ERROR"):
            for line in log_content.splitlines():
                if line.startswith("CHK|"):
                    continue
                if re.search(r'\b(FAIL|ERROR|FATAL|mismatch)\b', line, re.IGNORECASE):
                    errors.append(SimError(message=line.strip()))
            errors = errors[:20]

        sim_time = _finish_time_ns(log_content)
        check_fields = parse_checks(log_content, pass_count, fail_count)
        try:
            measured_toggle = toggle_coverage(vcd_file)
        except Exception:  # a measurement must never break the verdict
            measured_toggle = None

        return SimulationResult(
            status=status,
            module_name="",
            simulation_time_ns=sim_time,
            test_count=pass_count + fail_count,
            pass_count=pass_count,
            fail_count=fail_count,
            errors=errors,
            waveform_file=str(vcd_file) if vcd_file.exists() else None,
            measured_toggle=measured_toggle,
            transcript_file=str(log_file),
            log_excerpt=_excerpt(log_content),
            **check_fields,
        )

    def simulate(self, design_id: str, rtl_code: str, testbench_code: str,
                 timeout: int = 60) -> SimulationResult:
        _validate_design_id(design_id)
        # Also ensure workspace containment before any file ops
        resolved = (self.workspace / design_id).resolve()
        try:
            if not resolved.is_relative_to(self.workspace):
                raise ValueError(f"Invalid design_id: {design_id!r} escapes workspace")
        except AttributeError:
            try:
                resolved.relative_to(self.workspace)
            except ValueError:
                raise ValueError(f"Invalid design_id: {design_id!r} escapes workspace")
        violations = _policy_violations(rtl_code, testbench_code)
        if violations:
            msg = "Rejected by sandbox policy: " + "; ".join(violations)
            return SimulationResult(
                status="ERROR", module_name="",
                errors=[SimError(message=v) for v in violations],
                log_excerpt=msg,
            )
        with _SIM_SLOTS:
            rtl_file, tb_file = self.write_files(design_id, rtl_code, testbench_code)
            ok, compile_log = self.compile(rtl_file, tb_file)
            if not ok:
                return SimulationResult(
                    status="ERROR",
                    module_name="",
                    errors=_parse_compile_errors(compile_log),
                    log_excerpt=f"Compilation failed:\n{compile_log}"[-2500:],
                )
            return self.run(design_id, timeout=timeout)
