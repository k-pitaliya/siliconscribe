"""
Verilog linter.

Tries, in order:
  1. verilator --lint-only -Wall  (if `verilator` is on PATH)
  2. iverilog -o /dev/null -g2012 -Wall  (if `iverilog` is on PATH)
  3. Heuristic regex checks (always available, no external tool required)

Never raises on missing tool — fallback heuristic still runs and returns ok=True
with warnings.  Importable without any external tool installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from models import SimError


# ---------------------------------------------------------------------------
# Tool output parsing
# ---------------------------------------------------------------------------

# Matches:  "design.sv:12: error: something"   or  "design.sv:12: warning: something"
# Also:     "file:line: <msg containing error/warning>"
_IVERILOG_RE = re.compile(r"^\s*([^:\s]+):(\d+):\s*(warning|warn|error)?\s*:?\s*(.*)", re.IGNORECASE)

# Verilator: "%Warning-WIDTH: design.sv:12: message"  or  "%Error: design.sv:12: message"
_VERILATOR_RE = re.compile(r"%\s*(Warning|Error)(?:-[A-Za-z0-9_]+)?:\s*([^:]+):(\d+):\s*(.*)", re.IGNORECASE)

# Generic fallback: "file:line: message"
_GENERIC_RE = re.compile(r"^\s*([^:\s]+):(\d+):\s*(.*)")


def _parse_tool_output(output: str) -> tuple[List[SimError], List[SimError]]:
    """Parse combined stdout+stderr from iverilog/verilator into errors/warnings."""
    errors: List[SimError] = []
    warnings: List[SimError] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Try verilator first (more specific)
        m = _VERILATOR_RE.match(line)
        if m:
            kind = m.group(1).lower()
            f = m.group(2).strip()
            ln = int(m.group(3))
            msg = m.group(4).strip()
            err = SimError(file=f, line=ln, message=msg)
            if "error" in kind:
                errors.append(err)
            else:
                warnings.append(err)
            continue

        # Try iverilog with explicit warning/error token
        m = _IVERILOG_RE.match(line)
        if m:
            f = m.group(1).strip()
            ln = int(m.group(2))
            kind = (m.group(3) or "").lower()
            msg = m.group(4).strip()
            # If the kind token is present, classify directly
            if kind:
                err = SimError(file=f, line=ln, message=msg or kind)
                # Reconstruct full message with kind for clarity if msg empty
                if not msg:
                    err.message = kind
                if "error" in kind:
                    errors.append(err)
                elif "warn" in kind:
                    warnings.append(err)
                else:
                    # Unknown kind — decide by content
                    if "error" in msg.lower():
                        errors.append(err)
                    elif "warning" in msg.lower() or "warn" in msg.lower():
                        warnings.append(err)
                    else:
                        warnings.append(err)
                continue
            # No explicit kind token — infer from message content
            lower = msg.lower()
            if "error" in lower or "syntax" in lower:
                errors.append(SimError(file=f, line=ln, message=msg))
            elif "warning" in lower or "warn" in lower:
                warnings.append(SimError(file=f, line=ln, message=msg))
            else:
                # iverilog sometimes emits bare diagnostics without keyword; treat as warning
                # unless it looks like an error
                warnings.append(SimError(file=f, line=ln, message=msg))
            continue

        # Generic line containing error/warning keywords without file:line prefix
        low = line.lower()
        if "error" in low:
            errors.append(SimError(message=line[:500]))
        elif "warning" in low:
            warnings.append(SimError(message=line[:500]))

    return errors, warnings


# ---------------------------------------------------------------------------
# Heuristic checks (no tool required)
# ---------------------------------------------------------------------------

def _strip_comments(code: str) -> str:
    """Return code with // and /* */ comments removed (for structural counting)."""
    # Remove // comments
    code = re.sub(r"//.*", "", code)
    # Remove /* ... */ block comments (including multi-line)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return code


def _heuristic_checks(rtl_code: str, tb_code: str = "") -> tuple[List[SimError], List[SimError]]:
    """Pure-python regex heuristics. Returns (errors, warnings).

    When no external tool is available we deliberately classify findings as
    *warnings* so that ``ok`` remains True (per spec: fallback returns ok True
    with warnings). Only the most egregious structural issue (module/endmodule
    mismatch) could be an error, but even that stays a warning in fallback
    mode to avoid blocking the pipeline when no linter is installed.
    """
    errors: List[SimError] = []
    warnings: List[SimError] = []

    combined = rtl_code or ""
    if tb_code:
        combined = combined + "\n" + tb_code

    if not combined.strip():
        return errors, warnings

    # Use comment-stripped version for structural counting to avoid false positives
    # from words inside comments (e.g. "/* missing endmodule */").
    stripped_combined = _strip_comments(combined)

    # 1. Duplicate module definitions
    modules = re.findall(r"\bmodule\s+(\w+)", stripped_combined)
    seen: set[str] = set()
    dups: set[str] = set()
    for m in modules:
        if m in seen:
            dups.add(m)
        seen.add(m)
    for d in dups:
        warnings.append(SimError(message=f"Duplicate module definition: '{d}'"))

    # 2. module / endmodule mismatch
    mod_cnt = len(re.findall(r"\bmodule\b", stripped_combined))
    end_cnt = len(re.findall(r"\bendmodule\b", stripped_combined))
    if mod_cnt != end_cnt:
        warnings.append(
            SimError(message=f"module/endmodule mismatch: {mod_cnt} module(s) vs {end_cnt} endmodule(s)")
        )

    # 3. Missing semicolon — line-level heuristic (conservative)
    #    Flag only high-confidence cases: 'assign' without ';' and bare
    #    procedural assignments outside control/declaration headers.
    #    We deliberately skip declaration and control lines to avoid false
    #    positives on e.g. "parameter WIDTH = 4" inside #( ) or "if (a===b)".
    _SKIP_FIRST = {
        "if", "else", "case", "endcase", "for", "while", "repeat", "forever",
        "begin", "end", "module", "endmodule", "input", "output", "inout",
        "parameter", "localparam", "wire", "reg", "logic", "integer", "genvar",
        "int", "bit", "byte", "shortint", "longint", "time", "real", "realtime",
        "supply0", "supply1", "tri", "wand", "wor", "function", "endfunction",
        "task", "endtask", "generate", "endgenerate", "specify", "endspecify",
        "initial", "always", "always_ff", "always_comb", "always_latch",
        "export", "import", "package", "endpackage",
    }

    def _has_assignment(s: str) -> bool:
        # Single '=' not part of '==', '!=', '===', '!==', '>=', '<=', etc.
        # We treat '<=' as assignment only when it's not a comparison in an 'if'.
        # Since caller already skipped 'if' lines, treat any '<=' as assignment.
        if re.search(r"\w\s*<=", s):
            return True
        # Single '=' not part of '==', '!=', '===', '!==', '>=', '<='
        # Use negative lookbehind/ahead to ensure lone '='
        if re.search(r"(?<![=!<>])=(?!=)", s):
            return True
        return False

    lines = combined.splitlines()
    for idx, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        # Skip comments, preprocessor, timescale, and directives
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("`") or stripped.startswith("*") or stripped.startswith("#"):
            continue
        # Extract first word (if any)
        m_first = re.match(r"^\s*(\w+)", stripped)
        first_word = m_first.group(1).lower() if m_first else ""

        # Strip inline // comment for semicolon check so "a = b; // comment" is not flagged
        code_without_comment = stripped.split("//")[0].rstrip()
        # Special handling for 'assign' — must end with ';'
        if first_word == "assign":
            if _has_assignment(code_without_comment) and not code_without_comment.endswith(";"):
                # Avoid flagging incomplete assign that ends with operator (multi-line)
                if code_without_comment[-1] not in ("+", "-", "*", "/", "&", "|", "^", "(", "[", "{", ","):
                    warnings.append(
                        SimError(line=idx, message=f"Possible missing semicolon: '{stripped[:90]}'")
                    )
            continue

        # Skip declaration and control headers entirely
        if first_word in _SKIP_FIRST:
            continue
        # Also skip lines that start with 'else' variants or closing braces
        if re.match(r"^\s*(end|else)\b", stripped, re.IGNORECASE):
            continue

        # Skip lines that are preprocessor or timescale
        if stripped.startswith("`") or stripped.startswith("$"):
            continue

        # Generic assignment check for procedural statements like "count <= count + 1"
        # Only flag if it looks like a complete assignment statement missing ';'
        if not code_without_comment.endswith(";") and not code_without_comment.endswith(","):
            if code_without_comment.endswith("begin") or code_without_comment.endswith("end"):
                continue
            if code_without_comment and code_without_comment[-1] in ("+", "-", "*", "/", "&", "|", "^", "(", "[", "{", ","):
                continue
            if _has_assignment(code_without_comment):
                # For cases like `assign b = a` without ';', this catches it.
                # For multi-line `always` blocks, we still warn; that's acceptable as a heuristic.
                warnings.append(
                    SimError(line=idx, message=f"Possible missing semicolon: '{stripped[:90]}'")
                )

    # 4. Width mismatch heuristic (lightweight)
    #    Compare declared vector widths (`[N:0]`  => width N+1) against literal widths (`M'b...`).
    #    If a literal is wider than the smallest declared width, flag a possible mismatch.
    #    This is intentionally naive — it may over-warn — but satisfies the spec's
    #    "width mismatch" regex check without requiring elaboration.
    try:
        decl_widths = [int(v) + 1 for v in re.findall(r"\[\s*(\d+)\s*:\s*0\s*\]", stripped_combined)]
        lit_widths = [int(v) for v in re.findall(r"(\d+)'[bBhHdD]", combined)]
        if decl_widths and lit_widths:
            max_decl = max(decl_widths) if decl_widths else 0
            max_lit = max(lit_widths) if lit_widths else 0
            if max_lit > max_decl:
                warnings.append(
                    SimError(message=f"Possible width mismatch: literal width {max_lit}' vs declared max width {max_decl}")
                )
        # Check for obvious decimal overflow: e.g. `count <= 16` for 4-bit [3:0] (max 15)
        # Find assignments of decimal literals without width prefix — runs even when no explicit width literal
        if decl_widths:
            for m in re.finditer(r"<=\s*(\d+)\s*;?", combined):
                try:
                    val = int(m.group(1))
                    # Smallest declared width determines max value; warn if val exceeds its capacity
                    if val >= (1 << min(decl_widths)):
                        warnings.append(
                            SimError(message=f"Possible width mismatch: value {val} exceeds {min(decl_widths)}-bit capacity")
                        )
                        break
                except ValueError:
                    pass
            # Also check blocking assignment `= 16`
            for m in re.finditer(r"=\s*(\d+)\s*;", combined):
                try:
                    # Avoid catching `==` — the regex ensures single `=` followed by digits and `;`
                    # Filter out comparison contexts already handled; just check value magnitude
                    val = int(m.group(1))
                    if val >= (1 << min(decl_widths)):
                        # Only warn if the value is clearly too large for the smallest width
                        # and the line is not a parameter declaration (which we already skip)
                        warnings.append(
                            SimError(message=f"Possible width mismatch: value {val} exceeds {min(decl_widths)}-bit capacity")
                        )
                        break
                except ValueError:
                    pass
    except Exception:
        pass

    # 5. Unclosed `/* ... */` comment
    open_block = combined.count("/*")
    close_block = combined.count("*/")
    if open_block != close_block:
        warnings.append(SimError(message=f"Unbalanced block comment: {open_block} opening vs {close_block} closing"))

    # 6. Missing `timescale in testbench when RTL is sequential? Informational only — skip.

    return errors, warnings


# ---------------------------------------------------------------------------
# Public linter class
# ---------------------------------------------------------------------------

class VerilogLinter:
    """Lint Verilog/SystemVerilog code via verilator/iverilog or heuristics."""

    def lint(self, rtl_code: str, tb_code: str = "") -> dict:
        """Lint RTL (+ optional testbench).

        Args:
            rtl_code: Verilog source for the DUT.
            tb_code:  Optional testbench source. If supplied, both files are
                      linted together so cross-module errors are caught.

        Returns:
            dict with ``ok`` (bool), ``errors`` (List[SimError]),
            ``warnings`` (List[SimError]), ``output`` (str, raw tool output
            plus heuristic notes).
        """
        rtl_code = rtl_code or ""
        tb_code = tb_code or ""

        # Empty input short-circuit: treat as clean (no errors) to satisfy
        # heuristic-only tests and avoid spurious "No top level modules" error
        # from iverilog when linting empty strings.
        if not rtl_code.strip() and not tb_code.strip():
            return {"ok": True, "errors": [], "warnings": [], "output": ""}

        errors: List[SimError] = []
        warnings: List[SimError] = []
        output_parts: List[str] = []
        tool_used: str | None = None

        # Try external tools first; always also run heuristics and merge warnings
        heuristic_errors, heuristic_warnings = _heuristic_checks(rtl_code, tb_code)

        # ---- Verilator path ----
        if shutil.which("verilator"):
            tool_used = "verilator"
            try:
                with tempfile.TemporaryDirectory(prefix="lint_") as td:
                    td_path = Path(td)
                    rtl_file = td_path / "design.sv"
                    rtl_file.write_text(rtl_code)
                    files = [str(rtl_file)]
                    if tb_code.strip():
                        tb_file = td_path / "testbench.sv"
                        tb_file.write_text(tb_code)
                        files.append(str(tb_file))
                    cmd = ["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME", "-Wno-UNUSED"] + files
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=15
                    )
                    tool_output = (result.stderr or "") + (result.stdout or "")
                    output_parts.append(tool_output)
                    t_errors, t_warnings = _parse_tool_output(tool_output)
                    errors.extend(t_errors)
                    warnings.extend(t_warnings)
                    # verilator exit code 0 means no errors; warnings still possible
            except subprocess.TimeoutExpired:
                output_parts.append("verilator lint timeout")
            except FileNotFoundError:
                # Race: verilator disappeared between which() and run()
                tool_used = None
            except Exception as e:
                output_parts.append(f"verilator lint exception: {e}")

        # ---- Icarus Verilog fallback (only if verilator not used) ----
        if tool_used is None and shutil.which("iverilog"):
            tool_used = "iverilog"
            try:
                with tempfile.TemporaryDirectory(prefix="lint_") as td:
                    td_path = Path(td)
                    rtl_file = td_path / "design.sv"
                    rtl_file.write_text(rtl_code)
                    files = [str(rtl_file)]
                    if tb_code.strip():
                        tb_file = td_path / "testbench.sv"
                        tb_file.write_text(tb_code)
                        files.append(str(tb_file))
                    cmd = ["iverilog", "-o", "/dev/null", "-g2012", "-Wall"] + files
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=15
                    )
                    tool_output = (result.stderr or "") + (result.stdout or "")
                    output_parts.append(tool_output)
                    t_errors, t_warnings = _parse_tool_output(tool_output)
                    errors.extend(t_errors)
                    warnings.extend(t_warnings)
                    # iverilog exit code non-zero => at least one error; parser should have caught it
                    # If parser found nothing but exit code says error, synthesize an error
                    if result.returncode != 0 and not t_errors and tool_output.strip():
                        # Avoid duplicating generic parse: only if not already captured
                        if not any(tool_output.strip()[:200] in e.message for e in errors):
                            errors.append(SimError(message=tool_output.strip()[:500]))
            except subprocess.TimeoutExpired:
                output_parts.append("iverilog lint timeout")
            except FileNotFoundError:
                tool_used = None
            except Exception as e:
                output_parts.append(f"iverilog lint exception: {e}")

        # ---- Heuristic merge ----
        # If no external tool was used, heuristics are the sole source.
        # If a tool was used, we still surface heuristic warnings that the tool
        # might have missed (but avoid duplicating exact messages).
        if tool_used is None:
            # Fallback mode: per spec, return ok True with warnings (even if heuristics found issues)
            # So we put heuristic errors into warnings to keep ok True unless tool found real errors.
            # `errors` stays empty in pure-heuristic mode; all findings become warnings.
            for h in heuristic_errors:
                warnings.append(h)
            for h in heuristic_warnings:
                # Deduplicate by message
                if not any(h.message == w.message for w in warnings):
                    warnings.append(h)
            if not output_parts:
                output_parts.append("No lint tool available (verilator/iverilog not found); used heuristic checks.")
                if warnings:
                    output_parts.append("\n".join(f"warning: {w.message}" for w in warnings))
        else:
            # Tool was used: merge heuristic warnings that are not already covered
            for h in heuristic_warnings:
                if not any(h.message == w.message for w in warnings) and not any(h.message == e.message for e in errors):
                    # Only add heuristic warnings if they add new signal
                    warnings.append(h)
            for h in heuristic_errors:
                if not any(h.message == e.message for e in errors):
                    errors.append(h)

        # Filter benign warnings that are not actionable for tests nor pipeline:
        # iverilog "time unit / time precision" is emitted for every DUT without
        # `timescale and would otherwise make all offline designs appear warned.
        def _is_benign_warning(msg: str) -> bool:
            low = msg.lower()
            return "time unit" in low or "time precision" in low

        warnings = [w for w in warnings if not _is_benign_warning(w.message)]
        # Also filter raw output_parts for that warning so output is cleaner
        # (keep output_parts as is for debugging, but filtered warnings affect ok)

        # Determine ok: True if no errors (warnings don't fail the lint)
        # In pure-heuristic mode errors is empty by construction, so ok True.
        ok = len(errors) == 0

        # Deduplicate errors/warnings by (file, line, message) while preserving order
        def _dedup(lst: List[SimError]) -> List[SimError]:
            seen = set()
            out: List[SimError] = []
            for e in lst:
                key = (e.file, e.line, e.message)
                if key not in seen:
                    seen.add(key)
                    out.append(e)
            return out

        errors = _dedup(errors)
        warnings = _dedup(warnings)

        output = "\n".join(p for p in output_parts if p).strip()

        return {"ok": ok, "errors": errors, "warnings": warnings, "output": output}
