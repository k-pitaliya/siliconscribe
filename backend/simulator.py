"""
Icarus-Verilog simulation engine.

Single, robust simulation path:
  write files -> ensure VCD dump -> iverilog compile -> vvp run -> parse results.

Compile errors, runtime errors, timeouts, and test failures are all surfaced as
a structured SimulationResult. The self-correction loop (orchestrator.py) feeds
ERROR/FAIL results back to the LLM, so we deliberately do NOT try to "repair"
SystemVerilog with regex here — that job belongs to the model.
"""

import subprocess
import re
import shutil
from pathlib import Path
from typing import Tuple, Optional, List

from models import SimulationResult, SimError

VCD_FILENAME = "design.vcd"
LOG_FILENAME = "transcript.log"

# --- Hardening constants ---
DESIGN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
MAX_CODE_BYTES = 200 * 1024  # 200 KB


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
        cmd = ["iverilog", "-o", str(output_vvp), "-g2012", "-Wall", str(rtl_file), str(tb_file)]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = (result.stderr or "") + (result.stdout or "")
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
                subprocess.run(["vvp", str(vvp_file)], cwd=design_dir,
                               stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired:
            return SimulationResult(status="TIMEOUT", module_name="",
                                    simulation_time_ns=timeout * 1000,
                                    errors=[SimError(message=f"Simulation exceeded {timeout}s timeout")],
                                    log_excerpt=f"Simulation exceeded {timeout}s timeout")
        except FileNotFoundError:
            return SimulationResult(status="ERROR", module_name="",
                                    errors=[SimError(message="vvp runtime not found")],
                                    log_excerpt="vvp runtime not found")

        return self.parse_results(log_file, vcd_file)

    def parse_results(self, log_file: Path, vcd_file: Path) -> SimulationResult:
        try:
            log_content = log_file.read_text()
        except FileNotFoundError:
            return SimulationResult(status="ERROR", module_name="",
                                    log_excerpt="Log file not found")

        pass_match = re.search(r"Passed:\s*(\d+)", log_content)
        fail_match = re.search(r"Failed:\s*(\d+)", log_content)
        pass_count = int(pass_match.group(1)) if pass_match else 0
        fail_count = int(fail_match.group(1)) if fail_match else 0

        # Runtime errors emitted by $error / $fatal or vvp itself.
        runtime_error = bool(re.search(r"\$?(fatal|FATAL)|vvp:.*error|ERROR:", log_content))
        explicit_pass = "ALL TESTS PASSED" in log_content

        if fail_count > 0:
            status = "FAIL"
        elif runtime_error and not explicit_pass:
            status = "ERROR"
        elif explicit_pass or pass_count > 0:
            status = "PASS"
        else:
            # No recognizable summary -> treat as error so the loop can react.
            status = "ERROR"

        errors: List[SimError] = []
        if status in ("FAIL", "ERROR"):
            for line in log_content.splitlines():
                if re.search(r'\b(FAIL|ERROR|FATAL|mismatch)\b', line, re.IGNORECASE):
                    errors.append(SimError(message=line.strip()))
            errors = errors[:20]

        # Simulated time, if the TB prints "$finish at <n>" or "time = <n>".
        time_match = re.search(r"\$finish\s+at\s+simulation\s+time\s+(\d+)", log_content)
        sim_time = float(time_match.group(1)) if time_match else 0.0

        return SimulationResult(
            status=status,
            module_name="",
            simulation_time_ns=sim_time,
            test_count=pass_count + fail_count,
            pass_count=pass_count,
            fail_count=fail_count,
            errors=errors,
            waveform_file=str(vcd_file) if vcd_file.exists() else None,
            transcript_file=str(log_file),
            log_excerpt=log_content[-2500:],
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
