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
import signal
import subprocess
import re
import shutil
import tempfile
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
# Whitespace or comments may sit between tokens (Icarus accepts `testbench/**/.x` and
# `$dumpfile/**/("..")`), so every check below that spans tokens allows them.
# Block comments written "unrolled" (no lazy .*? inside a repeated group): the earlier form backtracked exponentially, so a
# 100-byte input of repeated /**/ took over 30 s (self-review verification finding, reproduced).
_BLOCK_COMMENT = r"/\*[^*]*\*+(?:[^/*][^*]*\*+)*/"
# The token-spanning checks below run on COMMENT-STRIPPED text (linear scanner), with bounded arguments: patterns that
# skipped comments themselves were quadratic on repeated "$dumpfile/*" or "testbench/*" (self-review verification).
_RTL_TB_HIERARCHY_RE = re.compile(r"\btestbench\s*\.|\$root\b")
# Real RTL never prints (the RTL prompt forbids it) and has no `final` block; both were
# used to forge the summary after $finish (review: `final $write("%cassed: 16",80)`).
_RTL_PRINT_RE = re.compile(r"\$(?:display|write|strobe|monitor)[bho]?\b|\bfinal\b")
# A macro whose body contains `$` can build a system task name the scanner never sees
# (review: `define D $ / `define E fopen / `D`E("/abs/path","w") wrote outside the workspace).
_DIRECTIVE_RE = re.compile(r"`(?!timescale\b)[A-Za-z_]")      # any macro use or directive other than `timescale
_INCLUDE_RE = re.compile(r"`\s*include\b")
_DUMPFILE_RE = re.compile(r"\$dumpfile\b(\s*)(\(([^)]{0,512})\))?")
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


# One run at a time per design folder: two concurrent runs of the same design_id (two tabs, a double-clicked
# Re-run) overwrote each other's files and produced false verdicts in 25 of 25 tries (self-review finding).
_DIR_LOCKS: dict = {}
_DIR_LOCKS_GUARD = threading.Lock()
COMPILE_TIMEOUT = 30


def _dir_lock(path: Path) -> threading.Lock:
    with _DIR_LOCKS_GUARD:
        return _DIR_LOCKS.setdefault(str(path), threading.Lock())


def run_tool(cmd: List[str], timeout: float, grace: float = 0, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run that kills the WHOLE process group on timeout.

    `iverilog` is a driver that starts `ivl` as a grandchild; subprocess.run(timeout=) killed only the driver and
    left `ivl` spinning at 100% CPU after "Compilation timeout" (self-review finding, reproduced). The same holds
    for any tool that forks. Raises subprocess.TimeoutExpired like subprocess.run.

    With `grace` > 0 the group first gets SIGTERM and that many seconds to exit, then SIGKILL. `vvp` flushes its
    output on SIGTERM; SIGKILL lost the last few kilobytes the testbench printed (an SR-latch run that hung after
    552 passing checks kept only 466 of them).
    """
    kwargs.setdefault("stdin", subprocess.DEVNULL)
    capture = kwargs.pop("capture_output", False)
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    with subprocess.Popen(cmd, start_new_session=True, **kwargs) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if grace > 0:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.communicate(timeout=grace)
                except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
                    pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            proc.communicate()
            raise
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _scan(src: str, found: List[str]) -> None:
    """The text rules, applied to one piece of source (original or preprocessed)."""
    for m in _FORBIDDEN_RE.finditer(src):
        found.append(f"{m.group(0)} is not allowed (file or process access)")
    if _INCLUDE_RE.search(src):
        found.append("`include is not allowed")
    if "``" in src or "$`" in src:
        found.append("macro token pasting is not allowed")
    code = _strip_comments(src)
    for m in _DUMPFILE_RE.finditer(code):
        if m.group(2) is None:
            if code[m.end():m.end() + 1] not in ("", ";"):
                found.append("$dumpfile must be given a string literal")
            continue
        arg = (m.group(3) or "").strip()
        if len(arg) < 2 or arg[0] != '"' or arg[-1] != '"':
            found.append("$dumpfile must be given a string literal")
        elif not _SAFE_DUMP_NAME_RE.match(arg[1:-1]):
            found.append("$dumpfile must be a plain file name (no path separators)")
    for m in _SYSTEM_TASK_RE.finditer(src):
        name = m.group(1)
        if name not in ALLOWED_SYSTEM_TASKS and not _FORBIDDEN_RE.fullmatch("$" + name):
            found.append(f"${name} is not an allowed system task")


def preprocess(*sources: str) -> Optional[str]:
    """The sources after macro expansion by Icarus' own preprocessor, in compile order (macros defined in an earlier file
    apply to later ones). None when they cannot be preprocessed. Never reads other files: `include is refused before
    this is called."""
    with tempfile.TemporaryDirectory(prefix="ss_pp_") as td:
        paths = []
        for i, src in enumerate(sources):
            p = Path(td) / f"s{i}.sv"
            p.write_text(src or "")
            paths.append(str(p))
        try:
            r = run_tool(["iverilog", "-E", "-o", "-", *paths], 15, capture_output=True, text=True, cwd=td, env=clean_env())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        return r.stdout if r.returncode == 0 else None


def sandbox_violations(*sources: str) -> List[str]:
    """Return human-readable policy violations found in the given sources.

    The scan is deliberately conservative and does NOT strip comments: a naive
    comment stripper can be fooled by `"//"` inside a string literal into
    hiding a forbidden call, so a forbidden token inside a comment is rejected
    too (false positives are cheap, false negatives are not).

    Macros can build any name the text scan never sees (`define ID(a) a / `ID($)fopen, self-review verification finding),
    so whenever a macro or directive is used the rules are applied AGAIN to the preprocessed text.
    """
    found: List[str] = []
    for src in sources:
        _scan(src or "", found)
    if not found and any(_DIRECTIVE_RE.search(src or "") for src in sources):
        expanded = preprocess(*sources)
        if expanded is None:
            found.append("the code uses macros but could not be preprocessed, so it cannot be checked safely")
        else:
            _scan(expanded, found)
    seen, out = set(), []
    for v in found:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


_TOKEN_SCAN_RE = re.compile(r'"(?:\\.|[^"\\\n])*"|' + _BLOCK_COMMENT + r'|//[^\n]*')


def _mask_comments(src: str) -> str:
    """Like _strip_comments, but every comment character becomes a space, so positions in the result match the input."""
    src = src or ""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"' and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            i = j + 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j == -1 else j
            out[i:j] = " " * (j - i)
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out[i:j] = [ch if ch == "\n" else " " for ch in src[i:j]]
            i = j
        else:
            i += 1
    return "".join(out)


def _strip_comments(src: str) -> str:
    """Remove comments but keep string literals (so a "//" inside a string hides nothing).

    One linear pass, not a regex: an unterminated "/*" repeated 60,000 times made the regex form quadratic (52 s,
    self-review). An unterminated block comment runs to the end of the text, as in Verilog.
    """
    src = src or ""
    out: List[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            j = i + 1
            while j < n and src[j] != '"' and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:j + 1])
            i = j + 1
        elif c == "/" and src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
            out.append(" ")
        elif c == "/" and src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        else:
            j = i
            while j < n and src[j] not in '"/':
                j += 1
            out.append(src[i:j] if j > i else c)
            i = j if j > i else i + 1
    return "".join(out)


def _rtl_integrity_text(rtl: str) -> List[str]:
    """Reject RTL that could forge the testbench's verdict or end the run itself.

    Review finding (all reproduced): a DUT whose ``initial`` block prints
    ``Passed: 200 / Failed: 0 / ALL TESTS PASSED`` (optionally followed by $finish at
    t=0) was reported as PASS. Real RTL has no business printing the summary lines,
    ending the simulation, or reaching into the testbench hierarchy.
    """
    found = [f"RTL must not contain {tok!r} (it could forge the test verdict)"
             for tok in _RTL_FORBIDDEN_TOKENS if tok in (rtl or "")]
    if _RTL_TB_HIERARCHY_RE.search(_strip_comments(rtl)):
        found.append("RTL must not reference the testbench hierarchy (testbench.* or $root)")
    if _RTL_PRINT_RE.search(_strip_comments(rtl)):
        found.append("RTL must not print ($display/$write/$strobe/$monitor) or use a final block "
                     "(only the testbench reports results)")
    return found


def rtl_integrity_violations(rtl: str) -> List[str]:
    """Reject RTL that could forge the testbench's verdict or end the run itself (see _rtl_integrity_text). Applied to the
    macro-expanded RTL too: `define T testbench / `T.fail_count = 0 forged a PASS (self-review verification finding)."""
    found = _rtl_integrity_text(rtl or "")
    if not found and _DIRECTIVE_RE.search(rtl or ""):
        expanded = preprocess(rtl)
        found = _rtl_integrity_text(expanded) if expanded is not None else [
            "RTL uses macros but could not be preprocessed, so it cannot be checked safely"]
    return found


def _policy_violations(rtl_code: str, testbench_code: str) -> List[str]:
    return sandbox_violations(rtl_code, testbench_code) + rtl_integrity_violations(rtl_code)


def dut_instance_names(rtl_code: str, testbench_code: str) -> set:
    """Instance names, in the testbench, of modules DEFINED IN THE RTL (the design under test). Toggle coverage counts
    only signals under these instances (self-review finding: a testbench-side stimulus or reference module counted as
    design and raised coverage from 46% to 77%)."""
    rtl_modules = set(re.findall(r"\bmodule\s+([A-Za-z_]\w*)", _strip_comments(rtl_code)))
    tb = _strip_comments(testbench_code)
    names = set()
    for mod in rtl_modules:
        for m in re.finditer(rf"\b{re.escape(mod)}\s*(?:#\s*\((?:[^()]|\([^()]*\))*\))?\s*([A-Za-z_]\w*)\s*\(", tb):
            names.add(m.group(1))
    return names


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
    # Comments do not count (self-review: the word "$dumpvars" in a comment disabled the waveform).
    code = _strip_comments(testbench_code)
    if "$dumpfile" in code or "$dumpvars" in code or "$dumpall" in code:
        return testbench_code

    dump_block = (
        f'\n    initial begin\n'
        f'        $dumpfile("{VCD_FILENAME}");\n'
        f'        $dumpvars(0, {top_module});\n'
        f'    end\n'
    )

    # Insert right after the first "module <top> ... ;" header.
    # Anchored at the start of a line, so a comment such as "// testbench for the add4 module under test; ..." is never
    # taken as the header (self-review finding: the dump block was injected inside that comment and broke compilation).
    # The first module header that is NOT inside a comment (so "// testbench for the add4 module under test;" is skipped,
    # while "/* tb */ module testbench;" or "(* keep *) module testbench;" on one line still work: self-review findings).
    masked = _mask_comments(testbench_code)
    match = re.search(r'\bmodule\b\s+\w+\b[^;]{0,4000};', masked)
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
_FAILURE_LINE_RE = re.compile(r"^[ \t]*(?:FAIL|FAILED|ERROR|FATAL)\b|^[ \t]*CHK\|FAIL\|", re.MULTILINE)
_FINISH_RE = re.compile(r"\$finish called at (\d+) \((\d+)?(fs|ps|ns|us|ms|s)\)")
_UNIT_TO_NS = {"fs": 1e-6, "ps": 1e-3, "ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}


def _decide_verdict(log: str, returncode: Optional[int] = None):
    """Decide PASS/FAIL/ERROR from the transcript. Returns (status, passed, failed, notes).

    The testbench prints the summary, so the parser must not trust the first or the
    loosest match. Review findings (all reproduced): taking the FIRST ``Passed:`` anywhere
    let a mid-run phase line or a design-printed line decide the verdict, a ``Failed: x``
    (uninitialised counter) was read as 0, and ``ALL TESTS PASSED`` overrode printed errors.
    Rules now:
      * the summary lines must occupy a whole line, and the LAST pair wins, except that
        a ``Failed: N`` with N > 0 ANYWHERE makes the run a FAIL (a testbench that resets
        its counters per phase must not hide an earlier phase's failures);
      * FAIL/FATAL lines without a summary are a FAIL, not an ERROR (an ERROR lets the
        repair loop treat the oracle as broken and rewrite it);
      * both counts must be numeric, otherwise the run is an ERROR;
      * any FAIL/ERROR/FATAL line contradicts ``Failed: 0`` and makes the run a FAIL;
      * a run that executed zero checks is not a PASS;
      * a simulator exit code other than 0 (killed by a limit) is not a PASS.
    """
    notes: List[str] = []
    passed_raw = _SUMMARY_PASSED_RE.findall(log)
    failed_raw = _SUMMARY_FAILED_RE.findall(log)
    failure_lines = len(_FAILURE_LINE_RE.findall(log))

    def _is_num(v):
        return re.fullmatch(r"[0-9]+", v) is not None

    def _num(vals):
        return int(vals[-1]) if vals and _is_num(vals[-1]) else None
    passed, failed = _num(passed_raw), _num(failed_raw)
    earlier_failed = max((int(v) for v in failed_raw if _is_num(v)), default=0)

    if earlier_failed > 0 and (failed is None or failed == 0):
        notes.append(f"An earlier summary line reports 'Failed: {earlier_failed}'; a later "
                     "'Failed: 0' does not cancel it.")
        return "FAIL", passed or 0, earlier_failed, notes
    if (passed is None or failed is None) and failure_lines:
        notes.append(f"No valid summary, but the log contains {failure_lines} FAIL/FATAL line(s); "
                     "treating the run as FAIL.")
        return "FAIL", passed or 0, failure_lines, notes
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


_STOP_GRACE_SECONDS = 2   # time vvp gets after SIGTERM to flush what the testbench printed

# Said whenever a run hits the wall-clock limit. A testbench watchdog (#delay, then $finish) only helps while simulated
# time advances; a zero-delay feedback loop oscillates inside one time step, so the watchdog never fires. Seen live
# (20 Nov): an SR latch made of cross-coupled NANDs passed 552 checks, then the testbench released the forbidden
# s_n=r_n=0 input on both pins at once and the outputs flipped 1,1 -> 0,0 -> 1,1 forever at the same time.
_TIMEOUT_HINT = (
    "No $finish was reached, so any watchdog in the testbench never fired either: simulated time stopped advancing, "
    "or the simulation needs far longer than the limit. Simulated time stops when a zero-delay feedback loop "
    "oscillates within one time step: cross-coupled gates (for example an SR latch whose forbidden input is released "
    "on both pins at the same instant), an assign that feeds itself, or an always block that retriggers itself. "
    "Release such inputs one at a time, and check the design for an unintended combinational loop.")


def _timeout_result(log_file: Path, timeout: int) -> SimulationResult:
    """A run stopped by the wall clock: still TIMEOUT with no verdict counts, but the checks the testbench printed
    before it stopped are kept for display (the UI showed "0 checks" for a run that had passed 552 of them)."""
    try:
        log = log_file.read_text(errors="replace")   # bounded by the ulimit -f output cap
    except OSError:
        log = ""
    msg = f"Simulation exceeded {timeout}s timeout (no $finish reached)."
    logged = parse_checks(log, 0, 0)
    ran = ""
    if logged.get("checks_source") == "structured":
        groups = logged["check_groups"]
        passed, failed = sum(g.passed for g in groups), sum(g.failed for g in groups)
        lasts = re.findall(r"^CHK\|(?:PASS|FAIL)\|[^|\n]*\|([^|\n]{1,60})", log[-4000:], re.M)
        ran = (f" Before it was stopped, the testbench ran {passed + failed} check(s): {passed} passed, {failed} failed"
               + (f"; the last one printed was '{lasts[-1].strip()}'." if lasts else "."))
        logged["checks_consistent"] = True   # no summary exists to disagree with; these are progress, not a verdict
    else:
        logged = {}
    tail = log[-1500:]
    return SimulationResult(status="TIMEOUT", module_name="",
                            simulation_time_ns=0.0,   # unknown: the run was stopped by the wall clock (was seconds*1000)
                            errors=[SimError(message=msg + ran), SimError(message=_TIMEOUT_HINT)],
                            log_excerpt=msg + ran + "\n" + _TIMEOUT_HINT + (f"\nLast output:\n{tail}" if tail else ""),
                            **logged)


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
            # Same CPU/memory/file caps as the simulation (self-review: a generate loop of 3 million wires took the
            # compiler to ~3 GB in 5 s). run_tool kills the whole group on the wall-clock limit.
            limits = (f'ulimit -t {COMPILE_TIMEOUT + _CPU_SECONDS_SLACK} 2>/dev/null; ulimit -v {_MAX_MEMORY_KB} 2>/dev/null; '
                      f'ulimit -f {_MAX_OUTPUT_BLOCKS} 2>/dev/null; exec "$@"')
            result = run_tool(["/bin/sh", "-c", limits, "sh", *cmd], COMPILE_TIMEOUT, capture_output=True, text=True,
                              cwd=str(rtl_file.parent), env=clean_env())
            output = (result.stderr or "") + (result.stdout or "")
            if result.returncode == 127 and "not found" in output:     # the shell wrapper could not find iverilog
                return False, "Icarus Verilog (iverilog) not installed"
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
            timeout: Optional[int] = None, dut_instances: Optional[set] = None) -> SimulationResult:
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
                proc = run_tool(
                    ["/bin/sh", "-c", limits, "sh", "vvp", str(vvp_file)], timeout, grace=_STOP_GRACE_SECONDS,
                    cwd=design_dir, stdout=log, stderr=subprocess.STDOUT, env=clean_env())
        except subprocess.TimeoutExpired:
            return _timeout_result(log_file, timeout)
        except FileNotFoundError:
            return SimulationResult(status="ERROR", module_name="",
                                    errors=[SimError(message="vvp runtime not found")],
                                    log_excerpt="vvp runtime not found")

        return self.parse_results(log_file, vcd_file, returncode=proc.returncode, dut_instances=dut_instances)

    def parse_results(self, log_file: Path, vcd_file: Path,
                      returncode: Optional[int] = None, dut_instances: Optional[set] = None) -> SimulationResult:
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
            measured_toggle = toggle_coverage(vcd_file, dut_instances=dut_instances)
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
        with _dir_lock(resolved), _SIM_SLOTS:
            # Never report a previous run's waveform or transcript as this run's (self-review finding: a testbench
            # that dumps to its own file name left the OLD design.vcd in place, and it was shown for the new run).
            if resolved.is_dir():
                for stale in [*resolved.glob("*.vcd"), resolved / LOG_FILENAME, resolved / "testbench.vvp"]:
                    try:
                        stale.unlink()
                    except (FileNotFoundError, IsADirectoryError):
                        pass
            rtl_file, tb_file = self.write_files(design_id, rtl_code, testbench_code)
            ok, compile_log = self.compile(rtl_file, tb_file)
            if not ok:
                return SimulationResult(
                    status="ERROR",
                    module_name="",
                    errors=_parse_compile_errors(compile_log),
                    log_excerpt=f"Compilation failed:\n{compile_log}"[-2500:],
                )
            return self.run(design_id, timeout=timeout, dut_instances=dut_instance_names(rtl_code, testbench_code))
