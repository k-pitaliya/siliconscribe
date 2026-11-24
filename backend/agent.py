"""
agent.py: the debugging agent behind "Ask about this run".

The user asks a question about the code in the editor ("why does count skip 9?", "why did check 3 fail?").
The agent answers it from EVIDENCE, not from reading the source alone:

1. The editor's code is simulated again (the same sandboxed Icarus run as Re-run), so every answer is about
   exactly the code on screen.
2. The model is given a short overview (verdict, first failing checks, clocks, signals, numbered RTL) and a set
   of tools. Each turn it replies with ONE JSON object: either a tool call or the final answer.
3. Tools read the simulation's waveform (values at a time, changes in a window, a per-clock-cycle table, when a
   value occurred), search the code (what drives a signal, read lines) and, at most MAX_FIX_TESTS times, test a
   candidate fix in a fresh simulation.
4. A fix in the final answer is simulated once more by the server before it is shown, and its verdict is shown
   next to it. The model's own claim that a fix works is never trusted.

The protocol is plain JSON text rather than a provider's native function calling, so it works with every model the
app can use (the OpenCode app, Cloudflare, NVIDIA NIM, any OpenAI-compatible endpoint).

When no AI model is connected, or the model fails, `rule_based_answer` collects the same kind of evidence with fixed
rules and says plainly that it is not an AI diagnosis.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Callable, Dict, Iterator, List, Optional, Tuple

import llm_service
import wave_query
from wave_query import WaveDB, fmt_value, parse_value
from vcd_parser import ports_from_rtl

logger = logging.getLogger("siliconscribe.agent")

MAX_STEPS = 10              # model calls per question (tool calls + the answer)
MAX_FIX_TESTS = 3           # test_fix calls per question
TOOL_RESULT_CHARS = 3000    # one tool result, as the model sees it
OLD_RESULT_CHARS = 400      # results older than KEEP_FULL_STEPS are shortened to this
KEEP_FULL_STEPS = 5
RTL_PROMPT_LINES = 400      # numbered RTL lines included up front (the rest via read_code)
MAX_TABLE_ROWS = 32
MAX_SIGNALS_PER_CALL = 12
# Tools that read the simulation itself. An answer must rest on at least one of them (asked once; see ask()).
WAVE_TOOLS = {"values_at", "changes", "cycle_table", "find_value", "test_fix"}

SYSTEM_PROMPT = """You are the debugging assistant inside SiliconScribe, a Verilog/SystemVerilog playground.
You answer the user's question about ONE simulation run of the design and testbench shown in their editor.
You must ground every claim in evidence from the tools: values at specific times, specific source lines.

Each reply must be EXACTLY ONE JSON object and nothing else. Either call a tool:
  {"thought": "<one short sentence: what you are checking and why>", "tool": "<name>", "args": {...}}
or give the final answer:
  {"answer": "<markdown>", "suspect": "design" | "testbench" | "both" | "unclear" | "none",
   "confidence": "high" | "medium" | "low",
   "fix": {"file": "rtl" | "testbench", "code": "<the COMPLETE corrected file>"}}
("fix" is optional: include it only when you found a concrete bug.)

Tools (times are in nanoseconds; signal names may be bare like "count" or hierarchical like "dut.count"):
- failing_checks {"offset": 0, "limit": 10}: the testbench's failed comparisons (time, name, expected, actual).
- values_at {"t_ns": 120, "signals": ["count", "en"]}: each signal's value at that time (after updates at t)
  and just before it. Omit "signals" to get the design's ports.
- changes {"signal": "count", "from_ns": 0, "to_ns": 200}: every value change in the window (max 40).
- cycle_table {"signals": ["en", "count"], "from_ns": 80, "to_ns": 200, "clock": "clk", "edge": "posedge"}:
  one row per clock edge, values sampled just BEFORE the edge (what the flip-flops see) and the value AFTER the
  edge for each signal. Best tool for sequential logic. "clock" is optional when there is one clock.
- find_value {"signal": "count", "value": "9", "from_ns": 0}: when the signal held that value (decimal, 4'h9,
  4'b1001, x or z).
- drivers {"signal": "count"}: source lines that assign the signal (a text search of both files, with the
  enclosing always/assign block) and instance ports connected to it.
- read_code {"file": "rtl" | "testbench", "from_line": 1, "to_line": 60}: numbered source lines (max 120).
- test_fix {"file": "rtl" | "testbench", "code": "<COMPLETE file>"}: simulate a candidate fix with the other
  file unchanged and get the verdict. At most 3 per question.

How to work:
- Start from the evidence that matters for the question (usually the first failing check, then a cycle_table
  around it, then drivers of the wrong signal). Do not guess what a waveform shows: query it.
- Remember the testbench can be wrong too (wrong expected value, sampling one cycle early or late, missing
  reset). Compare the expected value with what the specification in the question/code comments implies.
- If you propose a fix, test it with test_fix first when you can. Never claim a fix works unless test_fix
  returned PASS. (The server also re-simulates the fix in your final answer and shows that verdict.) Fixing the testbench changes the checker itself: say so clearly.
- Query the waveform (values_at, changes, cycle_table or find_value) at least once before answering; the
  overview alone is not evidence of what the hardware did.
- Keep the answer short: what happened, the evidence (ALWAYS write times as "@125ns" so the user can click
  them, signals in `backticks`, source lines as "line 14"), the cause, and the fix. Use at most 3 to 4 short paragraphs or a short list.
- If the run PASSED and the user asks why something works, explain with evidence the same way.
- If you run out of useful tools, answer with what you know and say what is uncertain."""


# ============================================================================ code search helpers
def _strip_comments(code: str) -> str:
    """Comments and string literals replaced by spaces, line breaks kept, so line numbers stay right."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    code = re.sub(r"/\*[\s\S]*?\*/", blank, code)
    code = re.sub(r"//[^\n]*", blank, code)
    return re.sub(r'"(?:[^"\\\n]|\\.)*"', blank, code)


_BLOCK_RE = re.compile(r"\b(always_ff|always_comb|always_latch|always|assign|initial|task|function|module)\b")


_BLOCK_END_RE = re.compile(r"\b(endtask|endfunction|endmodule)\b")


def _enclosing_block(lines: List[str], idx: int) -> Optional[Tuple[int, str]]:
    for j in range(idx, max(-1, idx - 80), -1):
        if j < idx and _BLOCK_END_RE.search(lines[j]):
            return None                     # a task/function above us already ended: we are not inside it
        if _BLOCK_RE.search(lines[j]):
            return j + 1, lines[j].strip()
    return None


def find_drivers(name: str, rtl: str, tb: str, limit: int = 12) -> List[dict]:
    """Lines that assign `name` (LHS of =, <=, assign) or connect it to an instance port."""
    bare = name.split(".")[-1]
    bare = re.sub(r"\[.*$", "", bare).strip()
    if not re.fullmatch(r"[A-Za-z_]\w*", bare or ""):
        return []
    n = re.escape(bare)
    lhs = re.compile(
        r"(?:^|[;:]|\bbegin\b|\belse\b|\bassign\b|\)|\bforce\b)\s*(?:\{[^}]*\b" + n + r"\b[^}]*\}|" + n +
        r"(?:\s*\[[^\]]*\])*)\s*(?:<=|=)(?!=)")
    port = re.compile(r"\.\s*\w+\s*\(\s*" + n + r"(?:\s*\[[^\]]*\])?\s*\)")
    out: List[dict] = []
    for label, code in (("rtl", rtl), ("testbench", tb)):
        clean = _strip_comments(code or "").splitlines()
        original = (code or "").splitlines()
        for i, line in enumerate(clean):
            kind = None
            if lhs.search(line):
                kind = "assigns"
            elif port.search(line):
                kind = "instance port"
            if not kind:
                continue
            item = {"file": label, "line": i + 1, "code": original[i].strip()[:200], "kind": kind}
            blk = _enclosing_block(clean, i) if kind == "assigns" else None
            if blk and blk[0] != i + 1:
                item["block"] = f"line {blk[0]}: {original[blk[0] - 1].strip()[:160]}"
            out.append(item)
            if len(out) >= limit:
                return out
    return out


def numbered(code: str, start: int = 1, end: Optional[int] = None) -> str:
    lines = (code or "").splitlines()
    end = len(lines) if end is None else min(end, len(lines))
    start = max(1, start)
    return "\n".join(f"{i:4d}| {lines[i - 1]}" for i in range(start, end + 1))


# ============================================================================ tools
class ToolError(Exception):
    """A bad tool call: the message goes back to the model so it can correct itself."""


class Toolbox:
    """The tools of one question. Holds the run being discussed and the code it came from."""

    def __init__(self, db: Optional[WaveDB], result, rtl: str, tb: str,
                 simulate: Callable[[str, str], object]):
        self.db = db
        self.result = result
        self.rtl = rtl
        self.tb = tb
        self._simulate = simulate          # (rtl, tb) -> SimulationResult, sandboxed
        self.fix_tests = 0
        self.fix_results: Dict[Tuple[str, str], object] = {}

    # ---------------------------------------------------------------- helpers
    def _need_db(self) -> WaveDB:
        if self.db is None:
            raise ToolError("This run produced no waveform (it did not compile or did not dump a VCD). "
                            "Use failing_checks, drivers, read_code or test_fix instead.")
        return self.db

    def _sig(self, name) -> wave_query.Signal:
        db = self._need_db()
        if not isinstance(name, str) or not name.strip():
            raise ToolError("A signal name is required.")
        sig, _ = db.resolve(name)
        if sig is None:
            close = [s.path for s in db.signals if name.split(".")[-1].lower() in s.name.lower()][:8]
            hint = f" Similar: {', '.join(close)}." if close else " Use a name from the signal list in the overview."
            raise ToolError(f"No signal named '{name}' in the waveform.{hint}")
        return sig

    def _t(self, v, what: str) -> int:
        try:
            ns = float(v)
        except (TypeError, ValueError):
            raise ToolError(f"'{what}' must be a number of nanoseconds.")
        if ns < 0:
            raise ToolError(f"'{what}' cannot be negative.")
        return self._need_db().to_ticks(ns)

    def _ns(self, ticks: int) -> str:
        return f"{self._need_db().to_ns(ticks):g}ns"

    def _clock(self, name) -> wave_query.Signal:
        db = self._need_db()
        if name:
            sig = self._sig(name)
            if sig.width != 1:
                raise ToolError(f"'{sig.path}' is {sig.width} bits wide; a clock must be 1 bit.")
            return sig
        clocks = db.clocks()
        if not clocks:
            raise ToolError("No clock found by name (clk/clock...). Pass \"clock\" explicitly.")
        clocks.sort(key=lambda s: (not s.in_design, s.depth))
        return clocks[0]

    def _ports(self) -> List[str]:
        return list(ports_from_rtl(self.rtl).keys())

    # ---------------------------------------------------------------- the tools
    def failing_checks(self, offset=0, limit=10) -> str:
        r = self.result
        try:
            offset, limit = max(0, int(offset)), max(1, min(int(limit), 25))
        except (TypeError, ValueError):
            raise ToolError("offset and limit must be integers.")
        fails = [c for c in (r.checks or []) if c.status == "FAIL"]
        head = f"Verdict {r.status}: {r.fail_count} failed of {r.test_count} counted checks."
        if not fails:
            errs = "; ".join(e.message for e in (r.errors or [])[:5])
            return head + (" No failed check rows were logged." + (f" Errors: {errs}" if errs else ""))
        rows = [head]
        for c in fails[offset:offset + limit]:
            when = self._ns(c.t) if (c.t is not None and self.db) else (f"t={c.t}" if c.t is not None else "time unknown")
            rows.append(f"#{c.idx} @{when} [{c.category}] {c.name}: expected {c.expected} got {c.actual}"
                        + (f" ({c.detail})" if c.detail else ""))
        if len(fails) > offset + limit:
            rows.append(f"... {len(fails) - offset - limit} more (use offset).")
        return "\n".join(rows)

    def values_at(self, t_ns=None, signals=None) -> str:
        db = self._need_db()
        if t_ns is None:
            raise ToolError("'t_ns' is required.")
        t = self._t(t_ns, "t_ns")
        names = signals if isinstance(signals, list) and signals else self._ports()
        if not names:
            raise ToolError("Give a list of signal names in 'signals'.")
        rows = [f"At {db.to_ns(t):g}ns (value just before -> value after updates at this time):"]
        for n in names[:MAX_SIGNALS_PER_CALL]:
            try:
                s = self._sig(n)
            except ToolError as e:
                rows.append(f"  {n}: {e}")
                continue
            before, after = fmt_value(s.value_before(t), s.width), fmt_value(s.value_at(t), s.width)
            rows.append(f"  {s.path} = {after}" + (f"   (was {before})" if before != after else ""))
        return "\n".join(rows)

    def changes(self, signal=None, from_ns=0, to_ns=None) -> str:
        db = self._need_db()
        s = self._sig(signal)
        t0 = self._t(from_ns, "from_ns")
        t1 = db.end_time if to_ns is None else self._t(to_ns, "to_ns")
        rows, more = db.changes(s, t0, t1)
        start_val = fmt_value(s.value_before(t0), s.width) if t0 > 0 else None
        out = [f"{s.path} ({s.width} bit{'s' if s.width > 1 else ''}) from {db.to_ns(t0):g}ns to {db.to_ns(t1):g}ns:"]
        if start_val is not None:
            out.append(f"  value entering the window: {start_val}")
        out += [f"  @{db.to_ns(t):g}ns -> {fmt_value(v, s.width)}" for t, v in rows]
        if not rows:
            out.append("  no changes in this window")
        if more:
            out.append("  ... more changes (narrow the window)")
        return "\n".join(out)

    def cycle_table(self, signals=None, from_ns=0, to_ns=None, clock=None, edge="posedge") -> str:
        db = self._need_db()
        clk = self._clock(clock)
        if edge not in ("posedge", "negedge"):
            raise ToolError("'edge' must be posedge or negedge.")
        names = signals if isinstance(signals, list) and signals else [p for p in self._ports() if p != clk.name]
        sigs, missing = [], []
        for n in names[:MAX_SIGNALS_PER_CALL]:
            try:
                sigs.append(self._sig(n))
            except ToolError:
                missing.append(str(n))
        if not sigs:
            raise ToolError(f"None of these signals is in the waveform: {', '.join(missing)}.")
        t0 = self._t(from_ns, "from_ns")
        t1 = db.end_time if to_ns is None else self._t(to_ns, "to_ns")
        edges = db.edges(clk, t0, t1, edge, limit=MAX_TABLE_ROWS + 1)
        if not edges:
            return f"No {edge} of {clk.path} between {db.to_ns(t0):g}ns and {db.to_ns(t1):g}ns."
        head = "cycle | time    | " + " | ".join(f"{s.name} before -> after" for s in sigs)
        out = [f"{edge} of {clk.path}; 'before' = sampled by flip-flops at the edge, 'after' = value once the edge's updates settled.", head]
        for k, t in enumerate(edges[:MAX_TABLE_ROWS]):
            cells = []
            for s in sigs:
                b, a = s.value_before(t), s.value_at(t)
                cells.append(fmt_value(b, s.width) if b == a else f"{fmt_value(b, s.width)} -> {fmt_value(a, s.width)}")
            out.append(f"{k:5d} | {db.to_ns(t):g}ns | " + " | ".join(cells))
        if len(edges) > MAX_TABLE_ROWS:
            out.append("... more edges (narrow the window)")
        if missing:
            out.append(f"Not in the waveform: {', '.join(missing)}.")
        return "\n".join(out)

    def find_value(self, signal=None, value=None, from_ns=0, to_ns=None) -> str:
        db = self._need_db()
        s = self._sig(signal)
        bits = parse_value(value, s.width) if value is not None else None
        if bits is None:
            raise ToolError("'value' could not be read. Use decimal (9), hex (4'h9 or 0x9), binary (4'b1001), x or z.")
        t0 = self._t(from_ns, "from_ns")
        t1 = db.end_time if to_ns is None else self._t(to_ns, "to_ns")
        hits = db.find_value(s, bits, t0, t1)
        if not hits:
            return f"{s.path} never held {fmt_value(bits, s.width)} between {db.to_ns(t0):g}ns and {db.to_ns(t1):g}ns."
        rows = [f"{s.path} held {fmt_value(bits, s.width)}:"]
        for a, b in hits:
            rows.append(f"  from @{db.to_ns(a):g}ns " + (f"to @{db.to_ns(b):g}ns" if b is not None else "to the end of the run"))
        return "\n".join(rows)

    def drivers(self, signal=None) -> str:
        if not isinstance(signal, str) or not signal.strip():
            raise ToolError("A signal name is required.")
        hits = find_drivers(signal, self.rtl, self.tb)
        if not hits:
            return (f"No assignment to '{signal}' found by text search. It may be an input port, driven through a "
                    "concatenation, or named differently in the code.")
        rows = [f"Text search for assignments to '{signal.split('.')[-1]}' (not a full elaboration):"]
        for h in hits:
            rows.append(f"  {h['file']} line {h['line']} ({h['kind']}): {h['code']}" + (f"\n      in {h['block']}" if h.get("block") else ""))
        return "\n".join(rows)

    def read_code(self, file="rtl", from_line=1, to_line=None) -> str:
        code = self.rtl if file == "rtl" else self.tb if file == "testbench" else None
        if code is None:
            raise ToolError("'file' must be rtl or testbench.")
        try:
            a = max(1, int(from_line))
            b = int(to_line) if to_line is not None else a + 79
        except (TypeError, ValueError):
            raise ToolError("from_line and to_line must be integers.")
        b = min(b, a + 119)
        total = len(code.splitlines())
        if a > total:
            raise ToolError(f"The {file} has only {total} lines.")
        return f"{file} lines {a}-{min(b, total)} of {total}:\n" + numbered(code, a, b)

    def test_fix(self, file=None, code=None) -> str:
        if file not in ("rtl", "testbench"):
            raise ToolError("'file' must be rtl or testbench.")
        if not isinstance(code, str) or "module" not in code:
            raise ToolError("'code' must be the COMPLETE corrected file (with its module ... endmodule).")
        if self.fix_tests >= MAX_FIX_TESTS:
            raise ToolError(f"test_fix was already used {MAX_FIX_TESTS} times for this question. Give your answer.")
        self.fix_tests += 1
        res = self.run_fix(file, code)
        return describe_result(res, "Candidate fix")

    def run_fix(self, file: str, code: str):
        rtl, tb = (code, self.tb) if file == "rtl" else (self.rtl, code)
        key = (rtl, tb)
        if key not in self.fix_results:
            self.fix_results[key] = self._simulate(rtl, tb)
        return self.fix_results[key]

    TOOLS = ("failing_checks", "values_at", "changes", "cycle_table", "find_value", "drivers", "read_code", "test_fix")

    def call(self, name: str, args: dict) -> str:
        if name not in self.TOOLS:
            raise ToolError(f"Unknown tool '{name}'. Tools: {', '.join(self.TOOLS)}.")
        if not isinstance(args, dict):
            raise ToolError("'args' must be a JSON object.")
        fn = getattr(self, name)
        try:
            return fn(**args)
        except TypeError as e:
            raise ToolError(f"Bad arguments for {name}: {e}")


def describe_result(res, label: str = "Run") -> str:
    status = getattr(res, "status", "ERROR")
    line = f"{label}: {status}, {res.pass_count} passed / {res.fail_count} failed of {res.test_count} checks."
    if status == "PASS":
        return line
    fails = [c for c in (res.checks or []) if c.status == "FAIL"][:5]
    extra = [f"  {c.name}: expected {c.expected} got {c.actual}" for c in fails]
    if not fails:
        extra = [f"  {e.message[:200]}" for e in (res.errors or [])[:5]] or [f"  {(res.log_excerpt or '')[:400]}"]
    return "\n".join([line, *extra])


# ============================================================================ overview for the model
def overview(tb: Toolbox) -> str:
    r, db = tb.result, tb.db
    parts = [f"Verdict: {r.status} ({r.pass_count} passed, {r.fail_count} failed of {r.test_count} checks)."]
    if r.status in ("ERROR", "TIMEOUT"):
        parts.append("Errors: " + "; ".join(e.message[:200] for e in (r.errors or [])[:5]))
        if r.log_excerpt:
            parts.append("Log excerpt:\n" + r.log_excerpt[-1500:])
    fails = [c for c in (r.checks or []) if c.status == "FAIL"]
    if fails:
        parts.append("First failing checks:\n" + tb.failing_checks(0, 6).split("\n", 1)[-1])
    if db is not None:
        parts.append(f"Simulation ran to {db.to_ns(db.end_time):g}ns (1 VCD tick = {db.timescale_ps:g}ps)."
                     + (" The VCD was larger than the read limit, so late changes are missing." if db.partial else ""))
        for clk in db.clocks()[:2]:
            e = db.edges(clk, 0, db.end_time, "posedge", limit=3)
            if len(e) >= 3:
                parts.append(f"Clock {clk.path}: period about {db.to_ns(e[2] - e[1]):g}ns, first posedge @{db.to_ns(e[0]):g}ns.")
        sigs = sorted(db.signals, key=lambda s: (not s.in_design, s.depth, s.path))
        listing = ", ".join(f"{s.path}[{s.width}]" if s.width > 1 else s.path for s in sigs[:80])
        parts.append(f"Signals in the waveform ({len(db.signals)}): {listing}" + (" ..." if len(sigs) > 80 else ""))
    else:
        parts.append("No waveform is available for this run.")
    rtl_lines = tb.rtl.splitlines()
    parts.append(f"RTL ({len(rtl_lines)} lines):\n" + numbered(tb.rtl, 1, RTL_PROMPT_LINES)
                 + ("\n... (use read_code for the rest)" if len(rtl_lines) > RTL_PROMPT_LINES else ""))
    parts.append(f"Testbench: {len(tb.tb.splitlines())} lines (use read_code to read it).")
    return "\n\n".join(parts)


# ============================================================================ the loop
def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f"\n...[{len(text) - n} more characters cut]"


def _history_block(history: List[dict]) -> str:
    if not history:
        return ""
    rows = ["Earlier in this conversation:"]
    for h in history[-4:]:
        rows.append(f"User: {str(h.get('question', ''))[:500]}")
        rows.append(f"You: {str(h.get('answer', ''))[:1200]}")
    return "\n".join(rows)


def _transcript(base: str, steps: List[dict]) -> str:
    out = [base]
    if steps:
        out.append("Your steps so far (tool calls and their results):")
    for i, st in enumerate(steps):
        keep = i >= len(steps) - KEEP_FULL_STEPS
        res = st["result"] if keep else _clip(st["result"], OLD_RESULT_CHARS)
        out.append(f"[{i + 1}] {json.dumps({'tool': st['tool'], 'args': st['args']})[:600]}\nResult:\n{res}")
    out.append("Reply with ONE JSON object: the next tool call, or the final answer."
               + (" You have used most of your steps: give the final answer now." if len(steps) >= MAX_STEPS - 2 else ""))
    return "\n\n".join(out)


def _parse_reply(text: str) -> Optional[dict]:
    try:
        obj = llm_service._extract_json(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if "answer" in obj and isinstance(obj.get("answer"), str):
        return obj
    if isinstance(obj.get("tool"), str):
        return obj
    return None


def _short(result: str) -> str:
    first = result.strip().splitlines()[0] if result.strip() else ""
    return first[:160]


def _verified_fix(tools: Toolbox, fix) -> Optional[dict]:
    """Simulate the answer's fix (or reuse the identical test_fix run) and attach that verdict."""
    if not isinstance(fix, dict):
        return None
    file, code = fix.get("file"), fix.get("code")
    if file not in ("rtl", "testbench") or not isinstance(code, str) or "module" not in code or len(code) > 50000:
        return None
    if code.strip() == (tools.rtl if file == "rtl" else tools.tb).strip():
        return None
    try:
        res = tools.run_fix(file, code)
    except Exception as e:                       # a fix that cannot even be simulated is reported, not hidden
        logger.warning("fix verification failed: %s", e)
        return {"file": file, "code": code, "status": "ERROR", "pass_count": 0, "fail_count": 0, "test_count": 0,
                "summary": f"The fix could not be simulated: {str(e)[:200]}"}
    return {"file": file, "code": code, "status": res.status, "pass_count": res.pass_count,
            "fail_count": res.fail_count, "test_count": res.test_count,
            "summary": describe_result(res, "Server re-simulation of this fix")}


def ask(question: str, tools: Toolbox, history: Optional[List[dict]] = None,
        model: Optional[str] = None, reasoning_effort: Optional[str] = None,
        chat: Optional[Callable[[str, str], str]] = None) -> Iterator[dict]:
    """Run the agent for one question. Yields tool events, then exactly one answer event.

    `chat(system, user) -> str` is injectable for tests; by default it calls the selected model.
    """
    if chat is None:
        if llm_service.uses_offline(model):
            yield rule_based_answer(tools, "No AI model is connected (offline mode).")
            return

        def chat(system: str, user: str) -> str:
            return llm_service.agent_chat(system, user, model=model, reasoning_effort=reasoning_effort)

    base = "\n\n".join(p for p in (
        f"User question: {question}",
        _history_block(history or []),
        "Overview of the run:\n" + overview(tools),
    ) if p)
    steps: List[dict] = []
    format_slips = 0
    nudged = False
    for _ in range(MAX_STEPS):
        try:
            reply = chat(SYSTEM_PROMPT, _transcript(base, steps))
        except Exception as e:
            logger.warning("agent model call failed: %s", str(e)[:300])
            yield rule_based_answer(tools, f"The AI model did not answer ({_reason(e)}).", steps_taken=len(steps))
            return
        obj = _parse_reply(reply)
        if obj is None:
            format_slips += 1
            if format_slips >= 2:
                # Two replies that were not the JSON protocol: show the text as the answer, but say how it was produced.
                yield {"type": "answer", "text": llm_service._strip_think(reply).strip()[:6000] or "(empty reply)",
                       "suspect": "unclear", "confidence": "low", "fix": None, "rule_based": False,
                       "steps": len(steps), "note": "The model did not follow the tool protocol; this text is unchecked."}
                return
            steps.append({"tool": "(format)", "args": {}, "result":
                          "Your reply was not one JSON object. Reply with exactly one JSON object as described."})
            continue
        if "answer" in obj:
            looked = any(st["tool"] in WAVE_TOOLS and not st["result"].startswith("Tool error") for st in steps)
            if not looked and not nudged and tools.db is not None:
                # Grounding rule: an answer about a run must rest on the run. Ask once; a second answer is accepted.
                nudged = True
                steps.append({"tool": "(evidence)", "args": {}, "result":
                              "Before answering, confirm your explanation with at least one waveform query "
                              "(cycle_table, values_at, changes or find_value), then answer."})
                continue
            fix = _verified_fix(tools, obj.get("fix"))
            yield {"type": "answer", "text": obj["answer"].strip()[:8000],
                   "suspect": obj.get("suspect") if obj.get("suspect") in ("design", "testbench", "both", "unclear", "none") else "unclear",
                   "confidence": obj.get("confidence") if obj.get("confidence") in ("high", "medium", "low") else "medium",
                   "fix": fix, "rule_based": False, "steps": len(steps)}
            return
        name, args = obj["tool"], obj.get("args") or {}
        thought = str(obj.get("thought", ""))[:300]
        try:
            result = tools.call(name, args)
            ok = True
        except ToolError as e:
            result, ok = f"Tool error: {e}", False
        except Exception as e:                    # a tool bug must not end the conversation
            logger.exception("agent tool %s crashed", name)
            result, ok = f"Tool error: {type(e).__name__}", False
        result = _clip(result, TOOL_RESULT_CHARS)
        shown_args = {k: (v if k != "code" else f"<{len(v) if isinstance(v, str) else 0} characters>") for k, v in args.items()} \
            if isinstance(args, dict) else {}
        steps.append({"tool": name, "args": shown_args if name == "test_fix" else args, "result": result})
        yield {"type": "tool", "tool": name, "args": shown_args, "thought": thought, "ok": ok,
               "summary": _short(result), "result": result}
    yield rule_based_answer(tools, f"The model used all {MAX_STEPS} steps without giving an answer.", steps_taken=len(steps))


def _reason(e: Exception) -> str:
    low = str(e).lower()
    if "429" in low or "limit" in low or "quota" in low:
        return "its usage limit was reached"
    if "timeout" in low or "timed out" in low:
        return "it timed out"
    if isinstance(e, llm_service.ModelNotAvailable):
        return str(e)[:160]
    return "the provider returned an error"


# ============================================================================ no-AI evidence
def rule_based_answer(tools: Toolbox, why: str, steps_taken: int = 0) -> dict:
    """Evidence collected by fixed rules: the first failing check, the ports at that time, the cycles before it, and
    what drives the port that was wrong. It is labelled as NOT an AI diagnosis."""
    r, db = tools.result, tools.db
    parts: List[str] = [f"**{why} This is evidence collected by fixed rules, not an AI diagnosis.**"]
    fails = [c for c in (r.checks or []) if c.status == "FAIL"]
    if r.status == "PASS":
        parts.append(f"The run passed: {r.pass_count} of {r.test_count} checks.")
    elif r.status in ("ERROR", "TIMEOUT"):
        parts.append(f"The run ended with {r.status}.")
        parts += [f"- {e.message[:200]}" for e in (r.errors or [])[:5]]
    if fails and db is not None:
        c = fails[0]
        t = c.t if c.t is not None else 0
        parts.append(f"First failing check: **{c.name}** @{db.to_ns(t):g}ns, expected `{c.expected}`, got `{c.actual}` "
                     f"({len(fails)} failed check{'s' if len(fails) != 1 else ''} logged).")
        try:
            parts.append("```\n" + tools.values_at(db.to_ns(t)) + "\n```")
        except ToolError:
            pass
        try:
            clk = tools._clock(None)
            e = db.edges(clk, 0, t, "posedge", limit=100000)
            start = e[-5] if len(e) >= 5 else 0
            parts.append("```\n" + tools.cycle_table(None, db.to_ns(start), db.to_ns(t), clk.path) + "\n```")
        except ToolError:
            pass
        outputs = [n for n, d in ports_from_rtl(tools.rtl).items() if d == "output"]
        for n in outputs[:2]:
            hits = find_drivers(n, tools.rtl, "")
            if hits:
                parts.append(f"Lines that assign `{n}`:\n" + "\n".join(f"- line {h['line']}: `{h['code']}`" for h in hits[:4]))
    elif fails:
        c = fails[0]
        parts.append(f"First failing check: **{c.name}**, expected `{c.expected}`, got `{c.actual}`.")
    parts.append("Connect an AI model (Model menu) to get a diagnosis that reads this evidence.")
    return {"type": "answer", "text": "\n\n".join(parts), "suspect": "unclear", "confidence": "low",
            "fix": None, "rule_based": True, "steps": steps_taken}


def new_workspace_id() -> str:
    return "ag" + uuid.uuid4().hex[:24]
