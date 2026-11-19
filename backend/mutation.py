"""Testbench strength: inject small bugs into a design and see whether its testbench notices.

A PASS only means the testbench found nothing wrong. Whether the testbench *could* have found
something is a separate question, and for a model-written testbench nobody has asked it. This
module asks it the classic way (DeMillo, Lipton and Sayward, 1978, mutation testing): make a
handful of one-token changes to the design (``+`` to ``-``, ``&`` to ``|``, a flipped constant,
a negated ``if``) and run the SAME testbench against every changed copy. A mutant that still
passes is a bug the testbench cannot see.

Honest limits, which the report to the user repeats:
  * some mutants are *equivalent* (the changed design behaves identically), so a survivor is
    "not detected", not "proven missed";
  * the sample is small and syntactic, so the score is evidence about the testbench, not a proof.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from models import MutantInfo, StrengthReport

logger = logging.getLogger("siliconscribe.mutation")

MAX_MUTANTS = int(os.getenv("STRENGTH_MAX_MUTANTS", "12"))
BUDGET_SECONDS = float(os.getenv("STRENGTH_BUDGET_SECONDS", "40"))
PER_MUTANT_TIMEOUT = 6          # a mutant that hangs must not eat the whole budget
MIN_MUTANTS_FOR_WARNING = 5     # too few mutants say nothing about the testbench
WEAK_KILL_RATE = 0.5            # below this the PASS is flagged as weak evidence

_COMMENT_OR_STRING_RE = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"', re.S)
_DIRECTIVE_RE = re.compile(r"^[ \t]*`[^\n]*", re.M)
_PARAM_RE = re.compile(r"\b(?:parameter|localparam)\b[^;,)]*", re.S)
_LOOP_HEAD_RE = re.compile(r"\b(?:for|while|repeat|forever)\b")


def _blank(match: "re.Match[str]") -> str:
    """Replace text by spaces of the SAME length (newlines kept) so offsets stay valid."""
    return re.sub(r"[^\n]", " ", match.group(0))


def mask_code(code: str) -> str:
    """Same-length copy of *code* with comments, strings, directives and parameters blanked."""
    masked = _COMMENT_OR_STRING_RE.sub(_blank, code)
    masked = _DIRECTIVE_RE.sub(_blank, masked)
    return _PARAM_RE.sub(_blank, masked)


def _matching_paren(text: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _protected_spans(masked: str) -> List[Tuple[int, int]]:
    """Regions never mutated: bit-range brackets and loop headers.

    Changing ``[WIDTH-1:0]`` alters a declaration, not behaviour, and changing ``i = i + 1`` in a
    ``for`` header can create an endless loop that only the timeout would stop.
    """
    spans: List[Tuple[int, int]] = []
    depth, start = 0, 0
    for i, ch in enumerate(masked):
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]" and depth:
            depth -= 1
            if depth == 0:
                spans.append((start, i + 1))
    for m in _LOOP_HEAD_RE.finditer(masked):
        j = m.end()
        while j < len(masked) and masked[j] in " \t\r\n":
            j += 1
        if j < len(masked) and masked[j] == "(":
            end = _matching_paren(masked, j)
            if end != -1:
                spans.append((m.start(), end + 1))
    return spans


@dataclass(frozen=True)
class Mutant:
    kind: str
    start: int
    end: int
    replacement: str
    description: str
    line: int


def _line_of(code: str, offset: int) -> int:
    return code.count("\n", 0, offset) + 1


def _prev_is_operand(masked: str, idx: int) -> bool:
    """True when the previous non-space character ends an operand, i.e. a binary operator follows."""
    j = idx - 1
    while j >= 0 and masked[j] in " \t\r\n":
        j -= 1
    return j >= 0 and (masked[j].isalnum() or masked[j] in ")]_'")


# (kind, regex, replacement-or-callable, description, require_binary)
_SIMPLE_OPS = [
    ("add", re.compile(r"(?<![+\-])\+(?![+=:])"), "-", "`+` to `-`", True),
    ("sub", re.compile(r"(?<![\-<>=!])-(?![\-=>:])"), "+", "`-` to `+`", True),
    ("and", re.compile(r"(?<![&~])&(?![&=])"), "|", "`&` to `|`", False),
    ("or", re.compile(r"(?<![|~])\|(?![|=])"), "&", "`|` to `&`", False),
    ("xor", re.compile(r"(?<![\^~])\^(?![\^~=])"), "|", "`^` to `|`", False),
    ("land", re.compile(r"&&"), "||", "`&&` to `||`", False),
    ("lor", re.compile(r"\|\|"), "&&", "`||` to `&&`", False),
    ("eq", re.compile(r"(?<![=!<>])==(?!=)"), "!=", "`==` to `!=`", False),
    ("ne", re.compile(r"!=(?!=)"), "==", "`!=` to `==`", False),
    ("gt", re.compile(r"(?<![<>=-])>(?![>=])"), ">=", "`>` to `>=`", False),
    ("ge", re.compile(r">=(?!=)"), ">", "`>=` to `>`", False),
    ("lt", re.compile(r"(?<![<])<(?![<=])"), "<=", "`<` to `<=`", False),
    ("bnot", re.compile(r"(?<![~\w])~(?![&|^~])"), "", "bitwise `~` removed", False),
    ("lnot", re.compile(r"(?<![!=])!(?![=])"), "", "logical `!` removed", False),
    ("edge_p", re.compile(r"\bposedge\b"), "negedge", "`posedge` to `negedge`", False),
    ("edge_n", re.compile(r"\bnegedge\b"), "posedge", "`negedge` to `posedge`", False),
    ("bit1", re.compile(r"\b1'b1\b"), "1'b0", "`1'b1` to `1'b0`", False),
    ("bit0", re.compile(r"\b1'b0\b"), "1'b1", "`1'b0` to `1'b1`", False),
]
_SIZED_DEC_RE = re.compile(r"\b(\d+)'d(\d+)\b")
_SIZED_BIN_RE = re.compile(r"\b(\d+)'b([01_]*[01])\b")
_SIZED_HEX_RE = re.compile(r"\b(\d+)'h([0-9a-fA-F_]*[0-9a-fA-F])\b")
_IF_RE = re.compile(r"\bif\s*\(")


def candidate_mutants(code: str) -> List[Mutant]:
    """Every distinct one-edit mutant the operators can produce (unordered by usefulness)."""
    masked = mask_code(code)
    protected = _protected_spans(masked)

    def blocked(a: int, b: int) -> bool:
        return any(s < b and a < e for s, e in protected)

    out: List[Mutant] = []
    for kind, rx, repl, desc, need_binary in _SIMPLE_OPS:
        for m in rx.finditer(masked):
            if blocked(m.start(), m.end()):
                continue
            if need_binary and not _prev_is_operand(masked, m.start()):
                continue
            out.append(Mutant(kind, m.start(), m.end(), repl, desc, _line_of(code, m.start())))

    for m in _SIZED_DEC_RE.finditer(masked):
        if blocked(m.start(), m.end()):
            continue
        width, value = int(m.group(1)), int(m.group(2))
        if width < 2 or width > 64:      # 1-bit constants are covered by bit0/bit1 above
            continue
        new = value + 1 if value + 1 < 2 ** width else max(value - 1, 0)
        if new == value:
            continue
        out.append(Mutant("const", m.start(), m.end(), f"{width}'d{new}",
                          f"`{m.group(0)}` to `{width}'d{new}`", _line_of(code, m.start())))

    # Multi-bit binary / hex literals: flip the lowest bit. In a `case` this re-points one label
    # (e.g. 2'b01 -> 2'b00), the typical decode bug a mux or decoder testbench must catch.
    for m in _SIZED_BIN_RE.finditer(masked):
        width = int(m.group(1))
        if width < 2 or blocked(m.start(), m.end()):
            continue
        digits = m.group(2)
        flipped = digits[:-1] + ("0" if digits[-1] == "1" else "1")
        out.append(Mutant("lit", m.start(), m.end(), f"{width}'b{flipped}",
                          f"`{m.group(0)}` to `{width}'b{flipped}`", _line_of(code, m.start())))
    for m in _SIZED_HEX_RE.finditer(masked):
        width = int(m.group(1))
        if width < 2 or blocked(m.start(), m.end()):
            continue
        digits = m.group(2)
        flipped = digits[:-1] + format(int(digits[-1], 16) ^ 1, "x")
        out.append(Mutant("lit", m.start(), m.end(), f"{width}'h{flipped}",
                          f"`{m.group(0)}` to `{width}'h{flipped}`", _line_of(code, m.start())))

    for m in _IF_RE.finditer(masked):
        open_idx = m.end() - 1
        close_idx = _matching_paren(masked, open_idx)
        if close_idx == -1 or blocked(m.start(), close_idx + 1):
            continue
        cond = code[open_idx + 1:close_idx]
        out.append(Mutant("ifneg", open_idx, close_idx + 1, f"(!({cond}))",
                          "`if` condition negated", _line_of(code, m.start())))

    unique = {(x.start, x.end, x.replacement): x for x in out}
    return sorted(unique.values(), key=lambda x: (x.start, x.kind))


def select_mutants(candidates: List[Mutant], limit: int = MAX_MUTANTS) -> List[Mutant]:
    """Pick up to *limit* mutants, spread across operator kinds, deterministically.

    Round-robin over kinds in order of first appearance so a design with forty ``+`` and one
    ``if`` still tests the ``if``. Within a kind, mutants are spread along the file.
    """
    by_kind: dict[str, List[Mutant]] = {}
    for c in candidates:
        by_kind.setdefault(c.kind, []).append(c)
    for kind, items in by_kind.items():
        if len(items) > limit:               # thin a long list evenly instead of taking the first few
            step = len(items) / limit
            by_kind[kind] = [items[int(i * step)] for i in range(limit)]
    chosen: List[Mutant] = []
    cursor = {k: 0 for k in by_kind}
    while len(chosen) < limit and any(cursor[k] < len(by_kind[k]) for k in by_kind):
        for kind in list(by_kind):
            if cursor[kind] < len(by_kind[kind]) and len(chosen) < limit:
                chosen.append(by_kind[kind][cursor[kind]])
                cursor[kind] += 1
    return sorted(chosen, key=lambda x: x.start)


def apply_mutant(code: str, m: Mutant) -> str:
    return code[:m.start] + m.replacement + code[m.end:]


def _is_invalid(res) -> bool:
    """A mutant that does not compile (or is refused by the sandbox) says nothing about the testbench."""
    log = (res.log_excerpt or "")
    return res.status == "ERROR" and (log.startswith("Compilation failed") or log.startswith("Rejected by sandbox"))


def run_strength(simulator, design_id: str, rtl_code: str, testbench_code: str,
                 limit: int = MAX_MUTANTS, budget_seconds: float = BUDGET_SECONDS) -> StrengthReport:
    """Run *testbench_code* against mutants of *rtl_code* and report how many it catches.

    The caller must only ask for a design whose real run PASSED; the score is relative to that.
    Never raises: a failure here must not break the run it decorates.
    """
    started = time.time()
    try:
        chosen = select_mutants(candidate_mutants(rtl_code), limit)
    except Exception:  # pragma: no cover - defensive; the operators are pure string work
        logger.exception("mutant generation failed")
        return StrengthReport(status="skipped", note="Could not generate mutants for this design.")
    if not chosen:
        return StrengthReport(status="skipped", note="No mutable operators found in this design.")

    scratch = (design_id[:26] + "_mu")[:32]        # fits DESIGN_ID_RE; one scratch folder, reused
    killed, invalid, inconclusive = 0, 0, 0
    # Baseline: how long does the UNMUTATED design take with this testbench? A mutant that times out only
    # counts as caught when the original finishes well inside the per-mutant limit (review finding: a slow
    # testbench with one check scored 3/3 because every mutant "timed out").
    baseline_fast = True
    try:
        t0 = time.time()
        base = simulator.simulate(scratch, rtl_code, testbench_code, timeout=PER_MUTANT_TIMEOUT)
        baseline_fast = base.status == "PASS" and (time.time() - t0) < PER_MUTANT_TIMEOUT / 3
    except Exception:
        baseline_fast = False
    survivors: List[MutantInfo] = []
    evaluated = 0
    partial = False
    try:
        for m in chosen:
            if time.time() - started > budget_seconds:
                partial = True
                break
            mutated = apply_mutant(rtl_code, m)
            if mutated == rtl_code:
                continue
            try:
                res = simulator.simulate(scratch, mutated, testbench_code, timeout=PER_MUTANT_TIMEOUT)
            except Exception:
                logger.exception("mutant simulation failed")
                invalid += 1
                continue
            if _is_invalid(res):
                invalid += 1
                continue
            if res.status == "PASS":
                evaluated += 1
                survivors.append(MutantInfo(description=m.description, line=m.line))
            elif res.status == "FAIL" or (res.status == "TIMEOUT" and baseline_fast):
                evaluated += 1
                killed += 1                 # the testbench reported a failure (or the mutant made the design hang)
            else:
                inconclusive += 1           # a crash, or a timeout of a testbench that is slow anyway: not a detection
    finally:
        try:
            shutil.rmtree(simulator.workspace / scratch, ignore_errors=True)
        except Exception:  # pragma: no cover
            pass

    if evaluated == 0:
        return StrengthReport(status="skipped", invalid=invalid, inconclusive=inconclusive,
                              note=("The testbench was too slow, or crashed, on every injected change, so it could not be scored."
                                    if inconclusive else "None of the injected changes compiled, so the testbench could not be scored."),
                              seconds=round(time.time() - started, 1))
    return StrengthReport(
        status="partial" if partial else "ok", total=evaluated, killed=killed, invalid=invalid,
        inconclusive=inconclusive,
        survivors=survivors,
        note=("A survivor is a change the testbench did not notice; some survivors may be equivalent "
              "to the original design, so this is evidence about the testbench, not a proof."),
        seconds=round(time.time() - started, 1),
    )


def weak_strength_note(report: Optional[StrengthReport]) -> Optional[str]:
    """Warning text when the testbench missed too many injected bugs for the PASS to be trusted."""
    if not report or report.status not in ("ok", "partial") or report.total < 1:
        return None
    if report.total < MIN_MUTANTS_FOR_WARNING:
        # Few mutants say little, but catching NONE of them is still worth saying (review finding: a testbench that
        # caught 0 of 3 got no warning at all).
        if report.killed == 0:
            return (f"Weak testbench: it caught none of the {report.total} injected bugs (only {report.total} could be "
                    "made for this small design), so this PASS may hide real defects.")
        return None
    if report.killed / report.total >= WEAK_KILL_RATE:
        return None
    return (f"Weak testbench: it caught only {report.killed} of {report.total} injected bugs, "
            "so this PASS may hide real defects.")
