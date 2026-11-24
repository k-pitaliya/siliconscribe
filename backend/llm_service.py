"""
LLM service: natural language -> RTL spec -> Verilog -> testbench -> explanation,
plus the debugger entry point (fix_design) used by the self-correction loop.

Providers behind one interface (priority order):
  0. Opencode Zen (remote, zero-budget) — OpenAI-compatible, free tier at
     https://api.opencode.ai/v1  (env: OPENCODE_API_KEY / ZEN_API_KEY,
     OPENCODE_BASE_URL / ZEN_BASE_URL, ZEN_MODEL / LLM_MODEL)
  1. NVIDIA NIM (OpenAI-compatible, free credits at build.nvidia.com)
  2. OpenAI / any OpenAI-compatible endpoint
  3. OfflineProvider: deterministic canned designs (no key / no internet / OFFLINE_MODE=1)

The module auto-selects: if OFFLINE_MODE=1 it always falls back to offline so the
app never hard-fails in a demo. Otherwise it tries Zen first, then NVIDIA, then
OpenAI, then offline.
"""

import logging
import os
import json
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Optional

from dotenv import load_dotenv

from models import RTLDesignSpec
import offline_designs as od
import model_catalog

logger = logging.getLogger("siliconscribe.llm")

# override=True so the project's .env wins over any stale shell env vars
# (e.g. a NVIDIA_API_KEY exported in ~/.zshrc) — otherwise the app can silently
# authenticate with the wrong key.
load_dotenv(override=True)


class ModelNotAvailable(RuntimeError):
    """The model the user picked cannot be used here (not set up, malformed). The message is shown to the user as is."""


class LLMUpstreamError(RuntimeError):
    """A failure at the LLM provider (connection, timeout, rate limit, 5xx, bad reply).

    The orchestrator treats ONLY this type (plus the legacy 'LLM_UPSTREAM' message
    prefix) as a provider outage that may trigger the labelled offline fallback.
    Matching digits in arbitrary error text caused real misclassifications.
    """


# --------------------------------------------------------------------------- #
# Prompts (OpenAI path)
# --------------------------------------------------------------------------- #
INTENT_PARSER_PROMPT = """You are an expert RTL design specification parser. Convert a natural language hardware description into a structured JSON specification.

Extract: module name (snake_case), port list (name/direction/width/description), parameters, behavioral description, and constraints (combinational/sequential, reset style).

IMPORTANT — the specification is the single source of truth. It will be used to
generate the RTL and the testbench INDEPENDENTLY, so it must pin down every
observable behaviour unambiguously. In "behavior" and "constraints" state
explicitly, when applicable:
- reset polarity and synchronicity (e.g. "asynchronous active-low reset rst_n")
- clock edge and enable semantics ("increments on posedge clk when enable=1")
- exact output values for each opcode/select encoding (give the truth table)
- overflow/carry/zero flag semantics
- what happens on reset, on disable, and for undefined opcodes
Do not leave behaviour implicit or say "as appropriate".

Output ONLY valid JSON matching this schema, no prose:
{
  "module_name": "string",
  "parameters": [{"name": "string", "type": "string", "default": 0}],
  "ports": [{"name": "string", "direction": "input|output|inout", "width": 1, "description": "string"}],
  "behavior": "string",
  "constraints": ["string"]
}"""

RTL_GENERATOR_PROMPT = """You are an expert Verilog RTL designer. Generate clean, synthesizable code.

TARGET: Icarus Verilog with -g2012. Prefer plain Verilog-2001 style (the most portable):
- "reg"/"wire" not "logic"; "always @(posedge clk)" not "always_ff"; "always @(*)" not "always_comb"
- "integer" loop vars, not "int"; no SystemVerilog interfaces/classes/structs
- ANSI ports and parameters are fine: input wire [WIDTH-1:0] data, parameter WIDTH = 8
- Follow the specification's reset polarity and style EXACTLY (synchronous or asynchronous, active-high or
  active-low); only if it is silent use an asynchronous active-low reset named rst_n.
- Ports exactly as specified (names, directions, widths). No unintended latches; 4-space indent; header comment.
- Synthesizable RTL only: no # delays, no $display/$finish/$stop or any other system task, no initial blocks.
- Reset every register explicitly; never give a reg a declaration value (no `reg q = 0;`): hardware does not keep it.
- Non-blocking (<=) in clocked always blocks, blocking (=) in combinational always @(*) blocks.
- For priority encoders, multiplexers, decoders, and FSMs, prefer an explicit
  `casez`/`case` or `if/else if` priority chain over hand-minimized Boolean
  equations. Correctness and readability beat gate-count golf.

FORMATTING (critical): write real, properly formatted multi-line Verilog with a
newline after every statement, port, and `begin`/`end`. NEVER collapse the module
onto one line — single-line code with `//` comments breaks compilation.

Output ONLY the Verilog code, no markdown fences or prose."""

TB_GENERATOR_PROMPT = """You are an expert Verilog verification engineer. Generate a self-checking testbench.

TARGET: Icarus Verilog (-g2012), plain Verilog-2001 style (reg/wire, integer loop variables).

CRITICAL — INDEPENDENT VERIFICATION:
You are given ONLY the specification, never the RTL implementation. Derive every
expected value from the specification's truth table / behavioural rules. Do NOT
infer expected values from a candidate implementation, and do NOT weaken a check
to make a design pass. The testbench must be able to FAIL a wrong design.

REQUIRED:
1. The top module MUST be named "testbench".
2. Instantiate the DUT with explicit named port connections.
3. Sequential DUT: generate a clock and start with an explicit RESET SEQUENCE (reset asserted from time 0,
   released later). Check the DUT's reset state BEFORE other stimulus: outputs must be defined (not X).
4. Stimulus must include: (a) directed corner cases: all zeros, all ones, each single bit, boundary values,
   wrap/overflow, and undefined or reserved encodings; (b) EXHAUSTIVE enumeration when the input space is
   at most 4096 vectors, otherwise >=100 randomized vectors ($random) in addition to the corners;
   (c) single-input-change vectors, where only ONE input changes between consecutive vectors, so a stale
   combinational output is caught; (d) for sequential DUTs, hold/enable behaviour checked in more than one
   state, and reset applied while other inputs are active.
5. Sampling discipline: for sequential DUTs change inputs and sample outputs on the FALLING clock edge
   (@(negedge clk)); for combinational DUTs wait #5 after changing inputs before comparing. Never compare
   in the same time step in which an input changed. For a latch or any feedback loop with a forbidden input
   combination (e.g. an SR latch with both inputs asserted), never release both inputs in the same time step:
   a zero-delay simulator then oscillates forever within one time step, so even the watchdog cannot fire.
   Leave the forbidden state one input at a time.
6. EVERY comparison goes through the check task below. Copy it verbatim into the module. It counts the
   result and prints ONE machine-readable line per check. Call it as
   chk("category", "descriptive_name", expected_value, actual_value);
   Build per-vector names with $sformat(label, "...", ...) into `reg [8*64-1:0] label;` (a Verilog string reg silently keeps only its RIGHTMOST characters, so size it for the longest name).
   Categories: directed, corner, random, reset, hold, exhaustive, toggle, protocol, undefined.
@@CHK_TASK@@
   The task uses === so X/Z never pass. Do NOT use == or != to check outputs anywhere.
7. Declare integer pass_count = 0; integer fail_count = 0; at module scope (the task updates them).
8. At the end print EXACTLY these, each on its own line (never print lines starting with Passed:/Failed:
   anywhere else):
   $display("Passed: %0d", pass_count);
   $display("Failed: %0d", fail_count);
   and if fail_count==0 also: $display("ALL TESTS PASSED");
9. Include the waveform dump: $dumpfile("design.vcd"); $dumpvars(0, testbench);
10. Always end with $finish, and add a watchdog so a hung design cannot hang the run: an initial block that
    waits about ten times the expected run time, prints "FAIL: watchdog timeout" and calls $finish.

SYSTEM TASKS: only these are allowed: $display, $write, $sformat, $time, $random, $urandom, $finish, $stop,
$dumpfile, $dumpvars, $isunknown, $clog2, $signed, $unsigned. Any other system task (file I/O, $system,
$readmemh, ...) is rejected by the sandbox and the run fails.

ICARUS / VERILOG-2001 COMPATIBILITY (critical):
- Declare every integer, reg, and wire at MODULE scope. Never declare variables
  inside an initial/always block.
- Do NOT use break, continue, or disable-a-function. Icarus rejects them. Use an
  if/else-if chain or a `found` flag instead.
- When computing an expected priority/encoded value in a loop, the FIRST match
  must win. Do not let a later loop iteration overwrite it: use if/else-if or
  `if (!found && condition)` and set `found` once.
- Keep every comparison width-correct. If concatenating a code with a valid bit,
  make the expected valid bit a 1-bit reg, not a 32-bit integer. Make every wire connected to a DUT
  port exactly as wide as that port.

FORMATTING (critical): write real, properly formatted multi-line Verilog with a
newline after every statement and `begin`/`end`. NEVER collapse code onto one line.

Output ONLY the Verilog testbench code, no markdown fences or prose.""".replace("@@CHK_TASK@@", od.CHK_TASK)

FIX_PROMPT = """You are an expert hardware debugger. A Verilog design failed simulation under Icarus Verilog.

You are given the RTL, the testbench, and the simulator log (compile errors and/or test failures).
The testbench was derived from the design SPECIFICATION, not from the RTL.

DIAGNOSE FIRST, THEN FIX. Work through the evidence in this order:
1. Read the simulator log and identify the FIRST concrete failure (file:line, or the
   first failing vector: inputs, expected value, actual value).
2. Check the testbench ORACLE against the specification. A generated testbench can
   itself be wrong (e.g. it scans bits in the wrong direction, truncates a
   comparison, or encodes an opcode differently). If the RTL matches the spec but
   the expected-value logic does not, the bug is in the testbench, not the RTL.
3. State the root cause in terms of the hardware/logic (e.g. "reset is active-high
   in the RTL but the spec says active-low rst_n", "counter increments by 2 because
   of 2'd2", "the oracle's loop overwrites the high-bit result with the low bit").
4. Only then produce the smallest code change that fixes that root cause.

HARD RULES:
- Do not weaken, skip, or delete a testbench check to make a design pass. Never edit
  expected values so they match buggy RTL. A testbench change is allowed ONLY for a
  compile error or a demonstrable mismatch with the specification, and you must say
  which specification clause justifies it.
- Prefer a minimal RTL patch over rewriting the whole module, EXCEPT when the
  diagnosis shows a priority/mux/decoder/FSM block is structurally wrong. In that
  case replace that block with a clear `casez`/`case` or `if/else if` chain
  instead of patching individual bits.
- Preserve module/port names so the testbench still binds.
- Keep Verilog-2001 / Icarus -g2012 compatibility (reg/wire, integer, no SV classes).
  Icarus rejects `break`, `continue` and `disable <function>`; use an if/else-if chain or a `found`
  flag instead (`return` inside a function is accepted). Keep comparison widths equal.
- The app REJECTS a testbench change that removes checks, stops instantiating the DUT, or renames the
  module, and an RTL change that is not a complete module with the same name. Keep the chk(...) task and
  its calls unless a check itself contradicts the specification.
- Never claim the tests pass; the simulator decides. If a fix failed on a previous
  attempt, change the approach rather than resubmitting equivalent logic.

Respond using EXACTLY this section format (do not wrap the answer in JSON or markdown):

<diagnosis>
symptom: <what the log shows, with the first failing vector if available>
root_cause: <the hardware reason, not a restatement of the symptom>
fix_location: <file or module/line and signal affected>
confidence: high|medium|low
</diagnosis>
<rtl>
<full corrected RTL, starting with module and ending with endmodule>
</rtl>
<testbench>
<full testbench, unchanged unless justified above>
</testbench>
<summary>
<one concise sentence describing the fix>
</summary>

Never emit unescaped prose between sections. The code sections must contain the
complete files, not fragments."""


def _strip_code_fence(text: str) -> str:
    """Extract the actual Verilog answer from a model response.

    Models sometimes put the main module in an unfenced block and a short
    illustrative snippet in a fenced one, so "first fence" is not reliable.
    Prefer the longest complete ``module ... endmodule`` unit found anywhere;
    otherwise fall back to the longest fenced block.
    """
    text = _strip_think(text)
    fenced = re.findall(r"```(?:verilog|systemverilog|json)?\s*([\s\S]*?)```", text)
    candidates = fenced + [text]
    complete = []
    for candidate in candidates:
        # Keep EVERY complete module, not just the first one: a design made of helper
        # modules plus a top (or a testbench with helpers) was cut down to its first
        # module and then rejected as "malformed" (review finding, reproduced).
        units = [u.strip() for u in re.findall(
            r"(?:^|\n)[ \t]*(?:`timescale[^\n]*\n[ \t]*)?module\b[\s\S]*?\bendmodule\b", candidate)]
        if units:
            joined = "\n\n".join(_last_definition_of_each(units))
            if candidate is text:
                # The whole reply sees every fence in order, so "last definition wins" picks a corrected copy over its
                # draft; a single fence cannot (self-review finding: equal-length draft and fix chose the draft).
                return joined
            complete.append(joined)
            continue
        m = re.search(
            r"(?:^|\n)\s*(?:`timescale[^\n]*\n\s*)?"
            r"(?:module|function)\b[\s\S]*?\bendmodule\b",
            candidate,
        )
        if m:
            complete.append(m.group(0).strip())
    if complete:
        return max(complete, key=len)
    if fenced:
        return max(fenced, key=len).strip()
    return text.strip()


_THINK_BLOCK_RE = re.compile(r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>", re.IGNORECASE)
_MODULE_NAME_RE = re.compile(r"\bmodule\s+(\\?\S+?)[\s#(;]")


def _strip_think(text: str) -> str:
    """Drop reasoning before parsing (self-review finding: a <think> draft added a duplicate module, or its mention of
    the reply format was taken as the answer). R1-style output may carry only a closing </think>."""
    text = _THINK_BLOCK_RE.sub("", text or "")
    if re.search(r"</think(?:ing)?>", text, re.IGNORECASE):
        text = re.split(r"</think(?:ing)?>", text, flags=re.IGNORECASE)[-1]
    return text


def _last_definition_of_each(units: list) -> list:
    """Keep one definition per module name: the LAST one (a draft followed by a corrected copy declared the module twice,
    so Icarus failed with "already declared"). Order follows each module's last appearance."""
    by_name: dict = {}
    for u in units:
        m = _MODULE_NAME_RE.search(u)
        name = m.group(1) if m else u
        by_name.pop(name, None)
        by_name[name] = u
    return list(by_name.values())


def _extract_json(text: str) -> dict:
    """The LAST JSON object in the reply that parses (self-review finding: prose with braces before the JSON, a think
    block, or a draft followed by the final object all broke the old first-brace-to-last-brace slice)."""
    text = _strip_think(text)
    fenced = re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    for raw in reversed(fenced + [text]):
        found = None
        for strict in (True, False):           # strict=False accepts literal newlines inside strings (pasted Verilog)
            dec = json.JSONDecoder(strict=strict)
            pos = 0
            while (i := raw.find("{", pos)) != -1:          # top-level objects only: skip past each decoded one
                try:
                    obj, end = dec.raw_decode(raw, i)
                except json.JSONDecodeError:
                    pos = i + 1
                    continue
                if isinstance(obj, dict):
                    found = obj                # keep scanning: the last complete object wins
                pos = end
            if found is not None:
                return found
    raise json.JSONDecodeError("no JSON object found", text, 0)


def model_module_name(v: str) -> str:
    """Turn a module name WRITTEN BY THE MODEL into a plain Verilog identifier (self-review: "Up/Down Counter" or
    "testbench" reached later stages, which each had to re-check it). A name the user typed is validated, not rewritten."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", (v or "").strip()).strip("_") or "dut"
    if name[0].isdigit():
        name = "m_" + name
    if name.lower() in ("testbench", "module", "input", "output", "wire", "reg", "begin", "end"):
        name = name + "_dut"
    return name[:64]


def _spec_from_model(content: str) -> RTLDesignSpec:
    data = _extract_json(content)
    if isinstance(data, dict) and isinstance(data.get("module_name"), str):
        data["module_name"] = model_module_name(data["module_name"])
    return RTLDesignSpec(**data)


def _section(text: str, tag: str) -> Optional[str]:
    """The LAST <tag>...</tag> section outside any reasoning block (a model restating the format first gave the wrong one)."""
    found = re.findall(rf"<{tag}>\s*([\s\S]*?)\s*</{tag}>", _strip_think(text), re.IGNORECASE)
    return found[-1].strip() if found else None


def _parse_diagnosis(block: Optional[str]) -> Optional[dict]:
    if not block:
        return None
    out = {}
    for line in block.splitlines():
        m = re.match(
            r"\s*[-*]?\s*(symptom|root_cause|fix_location|confidence)\s*:\s*(.*)",
            line, re.IGNORECASE,
        )
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    return out or None


def _salvage_fix_json(text: str) -> dict:
    """Best-effort extraction when a model emits invalid JSON around Verilog.

    The section format above avoids the problem for compliant models. Older or
    smaller models still answer with JSON and often fail to escape quotes or
    newlines in the code fields, so recover each top-level field by locating the
    next known key rather than trusting the JSON tokenizer.
    """
    keys = ["rtl_code", "testbench_code", "fix_summary"]
    out: dict = {}
    for key in keys:
        m = re.search(rf'"{re.escape(key)}"\s*:\s*"', text)
        if not m:
            continue
        start = m.end()
        end = len(text)
        for other in keys:
            if other == key:
                continue
            mm = re.search(rf'"\s*,\s*"{re.escape(other)}"\s*:', text[start:])
            if mm:
                end = min(end, start + mm.start())
        value = text[start:end].rstrip()
        # Drop the closing quote/comma/brace that belongs to the JSON envelope,
        # not to the Verilog (which ends in endmodule).
        value = re.sub(r'["\s,}\]]+$', "", value)
        value = (value.replace("\\n", "\n").replace("\\t", "\t")
                      .replace('\\"', '"').replace("\\\\", "\\"))
        out[key] = value.strip()

    diag = {}
    for field in ("symptom", "root_cause", "fix_location", "confidence"):
        m = re.search(rf'"{field}"\s*:\s*"([\s\S]*?)"\s*(?:,|\}})', text)
        if m:
            diag[field] = m.group(1).strip()
    if diag:
        out["diagnosis"] = diag
    return out


def _parse_fix_response(text: str, rtl_fallback: str, tb_fallback: str) -> dict:
    """Parse the fixer response into rtl/tb/diagnosis/summary.

    Primary format is explicit <diagnosis>/<rtl>/<testbench>/<summary> sections;
    malformed-JSON fallback keeps older models usable without sacrificing the
    structured diagnosis.
    """
    rtl_sec = _section(text, "rtl")
    tb_sec = _section(text, "testbench")
    if rtl_sec is not None or tb_sec is not None:
        diagnosis = _parse_diagnosis(_section(text, "diagnosis"))
        summary = _section(text, "summary")
        return {
            "rtl_code": _strip_code_fence(rtl_sec) if rtl_sec else rtl_fallback,
            "testbench_code": _strip_code_fence(tb_sec) if tb_sec else tb_fallback,
            "fix_summary": (summary or
                            (diagnosis or {}).get("root_cause") or
                            "Applied a fix."),
            "diagnosis": diagnosis,
        }

    try:
        data = _extract_json(text)
    except json.JSONDecodeError:
        data = {}
    if not any(k in data for k in ("rtl_code", "testbench_code")):
        data = _salvage_fix_json(text)         # invalid JSON around Verilog (unescaped quotes/newlines)
    if not any(k in data for k in ("rtl_code", "testbench_code")):
        # Nothing usable (a refusal, a reply cut off inside <rtl>, untagged fences): say so instead of "no change".
        return {"rtl_code": rtl_fallback, "testbench_code": tb_fallback, "diagnosis": None, "parse_failed": True,
                "fix_summary": "The model's repair reply could not be read (no <rtl> or <testbench> section)."}
    return {
        "rtl_code": _strip_code_fence(data.get("rtl_code", rtl_fallback)),
        "testbench_code": _strip_code_fence(data.get("testbench_code", tb_fallback)),
        "fix_summary": data.get("fix_summary", "Applied a fix."),
        "diagnosis": data.get("diagnosis") if isinstance(data.get("diagnosis"), dict) else None,
    }


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
class OpenAIProvider:
    """Works with OpenAI and any OpenAI-compatible endpoint (NVIDIA NIM, Groq,
    Together, OpenRouter, local Ollama, ...) by configuring base_url + model."""

    def __init__(self, api_key: str, base_url: Optional[str] = None,
                 model: str = "gpt-4o", mini_model: Optional[str] = None,
                 name: str = "openai"):
        from openai import OpenAI
        # A reasoning model routinely needs 30-120 s to emit 8k tokens of RTL.
        # The old hardcoded 20 s timeout guaranteed a fallback on any such model,
        # which made the live path look permanently "unavailable".
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
        # Transient provider errors (HTTP 429/5xx such as "high demand", and
        # timeouts) are retried by the OpenAI client with exponential backoff and
        # jitter before the orchestrator treats the provider as down.
        # Two retries, not three: the client also retries TIMEOUTS, so 3 retries x 120 s made one call wait up to 8 minutes
        # and spent quota on each resend (self-review finding). Not one either: a single transient 503 then ended live
        # runs (the earlier live-testing finding this retry count was raised for).
        self.max_retries = max(0, int(os.getenv("LLM_MAX_RETRIES", "2")))
        # Reasoning tokens are deducted from this budget. 8192 is enough for a
        # normal RTL/TB answer, but a reasoning model can spend all of it before
        # emitting a single answer token. Callers can raise it via env.
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8192"))
        self.client = (
            OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout, max_retries=self.max_retries)
            if base_url else
            OpenAI(api_key=api_key, timeout=self.timeout, max_retries=self.max_retries)
        )
        self.model = model
        self.mini_model = mini_model or model
        self.name = name
        # Optional per-stage model routing (LLM_MODEL_INTENT / _RTL / _TESTBENCH /
        # _EXPLAIN / _FIX). Lets a deployment put its strongest model on the
        # verification-critical stages and a cheap one on cosmetic ones.
        self.stage_models = {
            s: os.getenv(f"LLM_MODEL_{s.upper()}", "").strip()
            for s in ("intent", "rtl", "testbench", "explain", "fix")
        }

    def _extra_body(self, reasoning_effort: Optional[str], chosen: str) -> dict:
        """Extra request fields. For opencode models with variants the `:variant` suffix is primary; both
        common gateway spellings are sent to maximise compatibility. Providers whose API rejects unknown
        fields (Cloudflare) override this."""
        if reasoning_effort:
            return {"reasoning_effort": reasoning_effort, "reasoning": {"effort": reasoning_effort}}
        return {"reasoning": {"enabled": False}}

    def _chat(self, system: Optional[str], user: str, temperature: float,
              mini: bool = False, model: Optional[str] = None, reasoning_effort: Optional[str] = None,
              stage: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        # Precedence: a model explicitly different from the provider default (a real
        # per-request choice) > the stage-specific model > the default / mini model.
        override = model if (model and model != self.model) else None
        chosen = override or getattr(self, "stage_models", {}).get(stage or "") or (self.mini_model if mini else self.model)
        # Handle thinking level as model:variant suffix for opencode zen (e.g., opencode/claude-fable-5:high)
        # If reasoning_effort is provided and model has variants, append :variant to model name
        if reasoning_effort and ":" not in chosen and chosen.startswith("opencode/"):
            # Check if this model actually has that variant - we trust caller, zen will 404 if invalid and fallback will handle
            chosen = f"{chosen}:{reasoning_effort}"
        # Which model handled which stage (so an independent testbench model is verifiable in the logs).
        logger.info("llm stage=%s model=%s", stage or "-", chosen)
        # For templated tests that pass reasoning_effort but model is offline, ignore
        create_kwargs = {
            "model": chosen,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
        # Reasoning effort is opt-in. When it is not requested we explicitly
        # disable hidden reasoning: reasoning tokens count against max_tokens, so
        # a long RTL/testbench can burn the whole budget and return no content.
        # (Observed: 8192/8192 tokens were reasoning, finish_reason="length".)
        extra = self._extra_body(reasoning_effort, chosen)
        if extra:
            create_kwargs["extra_body"] = extra
        try:
            resp = self.client.chat.completions.create(**create_kwargs)
        except TypeError as e:
            # Fallback if extra_body not supported (older openai version) - retry without it
            if "extra_body" in str(e) or "reasoning" in str(e):
                create_kwargs.pop("extra_body", None)
                try:
                    resp = self.client.chat.completions.create(**{k: v for k, v in create_kwargs.items() if k != "extra_body"})
                except Exception as e2:
                    err_type = type(e2).__name__
                    base = getattr(self.client, "base_url", "") or getattr(self, "base_url", "")
                    raise LLMUpstreamError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e2)[:300]}") from e2
            else:
                err_type = type(e).__name__
                base = getattr(self.client, "base_url", "") or getattr(self, "base_url", "")
                raise LLMUpstreamError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e)[:300]}") from e
        except Exception as e:
            # Some gateways reject unknown `reasoning` fields with a 400/422.
            # Retry once without extra_body before declaring the provider down.
            low = str(e).lower()
            if create_kwargs.get("extra_body") and any(
                k in low for k in ("reasoning", "extra_body", "unknown parameter",
                                   "unrecognized", "unsupported", "invalid request")
            ):
                create_kwargs.pop("extra_body", None)
                try:
                    resp = self.client.chat.completions.create(**create_kwargs)
                except Exception as e2:
                    err_type = type(e2).__name__
                    base = getattr(self.client, "base_url", "") or getattr(self, "base_url", "")
                    raise LLMUpstreamError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e2)[:300]}") from e2
            else:
                # Map upstream 404/401/timeout to a typed error the orchestrator can fallback on
                err_type = type(e).__name__
                base = getattr(self.client, "base_url", "") or getattr(self, "base_url", "")
                raise LLMUpstreamError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e)[:300]}") from e
        # Defensive: some gateways return plain string or empty choices
        if isinstance(resp, str):
            raise LLMUpstreamError(f"LLM_UPSTREAM:InvalidResponse: provider returned str (check base_url) resp={resp[:300]}")
        choices = getattr(resp, "choices", None)
        usage = getattr(resp, "usage", None)
        if not choices:
            # Some gateways (e.g. the Cline API) wrap the standard body as
            # {"data": {"choices": [...], "usage": {...}}, "success": true}. The
            # OpenAI client keeps the unknown "data" key in model_extra.
            wrapped = (getattr(resp, "model_extra", None) or {}).get("data")
            if isinstance(wrapped, dict) and wrapped.get("choices"):
                choices, usage = wrapped["choices"], wrapped.get("usage")
        if not choices:
            raise LLMUpstreamError(f"LLM_UPSTREAM:EmptyChoices: base={getattr(self.client, 'base_url', '')} model={chosen} resp={str(resp)[:500]}")
        msg = choices[0].message if hasattr(choices[0], "message") else choices[0].get("message") if isinstance(choices[0], dict) else None
        if msg is None:
            raise LLMUpstreamError(f"LLM_UPSTREAM:NoMessage: model={chosen} choice={str(choices[0])[:500]}")
        finish = (choices[0].get("finish_reason") if isinstance(choices[0], dict)
                  else getattr(choices[0], "finish_reason", None))
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        details = (usage.get("completion_tokens_details") if isinstance(usage, dict)
                   else getattr(usage, "completion_tokens_details", None))
        reasoning_tokens = (details.get("reasoning_tokens") if isinstance(details, dict)
                            else getattr(details, "reasoning_tokens", None))
        if finish == "length":
            raise RuntimeError(
                f"Model '{chosen}' output was truncated (finish_reason=length, "
                f"max_tokens={self.max_tokens}, reasoning_tokens={reasoning_tokens}). "
                f"Increase LLM_MAX_TOKENS or use a non-reasoning model."
            )
        if not content or not str(content).strip():
            # NEVER fall back to msg.reasoning / reasoning_content here: those are
            # the model's scratchpad, not its answer. The previous fallback took a
            # half-written function out of the reasoning trace and shipped it as a
            # testbench (observed live: 8192/8192 reasoning tokens, empty content).
            raise LLMUpstreamError(
                f"LLM_UPSTREAM:EmptyContent: model '{chosen}' returned empty content (finish_reason={finish}, "
                f"reasoning_tokens={reasoning_tokens}, max_tokens={self.max_tokens}). "
                f"Reasoning counts against the output budget; increase "
                f"LLM_MAX_TOKENS or disable reasoning."
            )
        return str(content)

    def parse_intent(self, prompt: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> RTLDesignSpec:
        # Models occasionally answer the specification step with prose or an empty
        # reply instead of the required JSON (seen live with mimo-v2.6-flash-free).
        # That is a one-off format slip, not a design failure, so retry once before
        # giving up with a clear message.
        last: Optional[Exception] = None
        for _attempt in range(2):
            content = self._chat(INTENT_PARSER_PROMPT, prompt, 0.3, model=model, reasoning_effort=reasoning_effort, stage="intent")
            try:
                return _spec_from_model(content)
            except (ValueError, TypeError) as e:  # bad JSON, wrong shape or failed validation
                last = e
        raise RuntimeError(
            "The model did not return a valid JSON specification after 2 attempts "
            f"({str(last)[:120]}). Try again or choose another model."
        ) from last

    def generate_rtl(self, spec: RTLDesignSpec, freq_hint: Optional[int],
                     model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        freq = f"\nTarget clock frequency: {freq_hint} MHz." if freq_hint else ""
        user = (
            f"Generate Verilog for:\nModule: {spec.module_name}\n"
            f"Parameters: {json.dumps([p.model_dump() for p in spec.parameters])}\n"
            f"Ports: {json.dumps([p.model_dump() for p in spec.ports])}\n"
            f"Behavior: {spec.behavior}\nConstraints: {spec.constraints}{freq}"
        )
        return _strip_code_fence(self._chat(RTL_GENERATOR_PROMPT, user, 0.2, model=model, reasoning_effort=reasoning_effort, stage="rtl"))

    def generate_testbench(self, rtl_code: str, spec: RTLDesignSpec,
                           model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        # Deliberately withhold the RTL body: the testbench must be derived from
        # the SPECIFICATION so that a design which is consistently wrong together
        # with its own testbench cannot still report 100% PASS.
        # `rtl_code` is kept in the signature for API compatibility.
        user = (
            f"Write an independent, self-checking Verilog-2001 testbench "
            f"(top module named 'testbench').\n"
            f"The RTL implementation is intentionally NOT shown: derive every "
            f"expected value from the specification below.\n\n"
            f"Module: {spec.module_name}\n"
            f"Parameters: {json.dumps([p.model_dump() for p in spec.parameters])}\n"
            f"Ports: {json.dumps([p.model_dump() for p in spec.ports])}\n"
            f"Behavior: {spec.behavior}\n"
            f"Constraints: {json.dumps(spec.constraints)}"
        )
        return _strip_code_fence(self._chat(TB_GENERATOR_PROMPT, user, 0.3, model=model, reasoning_effort=reasoning_effort, stage="testbench"))

    def explain_design(self, rtl_code: str, spec: RTLDesignSpec,
                       model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        user = (
            f"Explain this Verilog module in 2-3 sentences for a hardware designer "
            f"(what it does, key design decisions). Be concise, no bullet points.\n\n"
            f"Module: {spec.module_name}\n```verilog\n{rtl_code}\n```"
        )
        # If the user picked a model, use it; otherwise the cheaper mini model.
        return self._chat(None, user, 0.5, mini=(model is None), model=model, reasoning_effort=reasoning_effort, stage="explain").strip()

    def fix_design(self, rtl_code: str, tb_code: str, log: str,
                   model: Optional[str] = None, reasoning_effort: Optional[str] = None,
                   spec: Optional[RTLDesignSpec] = None) -> dict:
        spec_block = ""
        if spec is not None:
            spec_block = (
                f"Specification (source of truth):\n"
                f"Module: {spec.module_name}\n"
                f"Ports: {json.dumps([p.model_dump() for p in spec.ports])}\n"
                f"Behavior: {spec.behavior}\n"
                f"Constraints: {json.dumps(spec.constraints)}\n\n"
            )
        user = (
            f"{spec_block}"
            f"RTL:\n```verilog\n{rtl_code}\n```\n\n"
            f"Testbench:\n```verilog\n{tb_code}\n```\n\n"
            f"Simulator log:\n```\n{log[-4000:]}\n```"
        )
        raw = self._chat(FIX_PROMPT, user, 0.2, model=model,
                         reasoning_effort=reasoning_effort, stage="fix")
        parsed = _parse_fix_response(raw, rtl_code, tb_code)
        if parsed.get("parse_failed"):        # one retry with the format spelled out, then report it as unreadable
            raw = self._chat(FIX_PROMPT, user + "\n\nYour previous reply could not be read. Answer ONLY with the "
                             "<diagnosis>, <rtl>, <testbench> and <summary> sections.", 0.2, model=model,
                             reasoning_effort=reasoning_effort, stage="fix")
            parsed = _parse_fix_response(raw, rtl_code, tb_code)
        return {
            "parse_failed": bool(parsed.get("parse_failed")),
            "rtl_code": parsed["rtl_code"],
            "testbench_code": parsed["testbench_code"],
            "fix_summary": parsed["fix_summary"],
            "diagnosis": parsed["diagnosis"],
            "fix_type": "llm_diagnosis",
        }


class OpenCodeAppProvider(OpenAIProvider):
    """Drive the user's own installed OpenCode app (``opencode run``) as the model.

    OpenCode's free models are meant to be used from the OpenCode app, which signs
    in with the user's own account; calling them with a plain API key hits a much
    smaller shared quota. This provider therefore uses the genuine, supported
    scripting interface of the app instead of imitating it. Select it with
    ``LLM_PROVIDER=opencode-app`` and ``LLM_MODEL=<model>`` (for example
    ``mimo-v2.6-flash-free``).

    Safety: every call runs in a fresh empty temp directory with the read-only
    ``plan`` agent (override with ``OPENCODE_AGENT``). This is a local, single-user
    convenience; do not expose it on a public server.
    """

    def __init__(self, model: str, name: str = "opencode-app"):
        # No HTTP client is needed: only _chat differs from OpenAIProvider.
        self.timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8192"))
        self.max_retries = 0
        self.model = model
        self.mini_model = model
        self.name = name
        self.agent = os.getenv("OPENCODE_AGENT", "plan").strip() or "plan"
        self.stage_models = {
            s: os.getenv(f"LLM_MODEL_{s.upper()}", "").strip()
            for s in ("intent", "rtl", "testbench", "explain", "fix")
        }

    def _chat(self, system: Optional[str], user: str, temperature: float,
              mini: bool = False, model: Optional[str] = None, reasoning_effort: Optional[str] = None,
              stage: Optional[str] = None) -> str:
        # `deepseek-v4.1-flash-free` (LLM_MODEL) and `opencode/deepseek-v4.1-flash-free` (the menu) are one model.
        override = model if (model and model_catalog.normalize_opencode_id(model) != model_catalog.normalize_opencode_id(self.model)) else None
        chosen = override or self.stage_models.get(stage or "") or self.model
        chosen = model_catalog.normalize_opencode_id(chosen)
        if not model_catalog.is_valid_model_id(chosen):    # becomes an argument of `opencode run -m`: never a flag
            raise ModelNotAvailable("That model name is not valid.")
        logger.info("llm stage=%s model=%s", stage or "-", chosen)
        message = f"{system}\n\n{user}" if system else user
        cmd = ["opencode", "run", "-m", chosen, "--agent", self.agent,
               "--archived", "--format", "json", message]
        with tempfile.TemporaryDirectory(prefix="siliconscribe_oc_") as cwd:
            try:
                proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                      timeout=self.timeout, env=model_catalog.child_env())   # allowlisted env: no other secrets
            except subprocess.TimeoutExpired as e:
                raise LLMUpstreamError(f"LLM_UPSTREAM:Timeout: opencode model={chosen} after {self.timeout:.0f}s") from e
            except FileNotFoundError as e:
                raise RuntimeError("LLM_UPSTREAM:OpenCodeNotInstalled: the 'opencode' command was not found") from e
        texts: list[str] = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "error":
                detail = json.dumps(ev.get("error") or ev)[:300]
                raise LLMUpstreamError(f"LLM_UPSTREAM:OpenCodeError: model={chosen} {detail}")
            if ev.get("type") == "text":
                txt = (ev.get("part") or {}).get("text")
                if txt:
                    texts.append(txt)
        content = "".join(texts).strip()
        if proc.returncode != 0 and not content:
            tail = (proc.stderr or proc.stdout or "").strip()[-300:]
            raise LLMUpstreamError(f"LLM_UPSTREAM:OpenCodeExit{proc.returncode}: model={chosen} {tail}")
        if not content:
            raise LLMUpstreamError(f"LLM_UPSTREAM:EmptyContent: opencode model={chosen} returned no text")
        return content


class CloudflareProvider(OpenAIProvider):
    """Cloudflare Workers AI through its OpenAI-compatible endpoint (/accounts/{id}/ai/v1/chat/completions).

    Same chat code as every other OpenAI-compatible provider; the differences are the account-scoped base
    URL, the Bearer API token, no `reasoning` request field (Workers AI is strict about unknown fields), and
    no per-stage model routing (LLM_MODEL_<STAGE> names OpenCode models, which Cloudflare does not know).
    """

    def __init__(self, account_id: str, token: str, model: str = model_catalog.DEFAULT_CLOUDFLARE_MODEL):
        super().__init__(api_key=token, base_url=model_catalog.cloudflare_base_url(account_id), model=model, name="cloudflare")
        self.stage_models = {}

    def _extra_body(self, reasoning_effort: Optional[str], chosen: str) -> dict:
        # Only the gpt-oss models document a reasoning effort; every other model gets a plain request.
        return {"reasoning_effort": reasoning_effort} if reasoning_effort and "gpt-oss" in chosen else {}


class NimProvider(OpenAIProvider):
    """NVIDIA NIM hosted API (integrate.api.nvidia.com, OpenAI-compatible).

    Menu ids carry a `nim/` prefix (`nim/poolside/laguna-xs-2.1`) so they cannot be confused with OpenCode's own
    `nvidia/...` ids; the prefix is removed before the request. Like Cloudflare it gets no `reasoning` request
    field and no per-stage routing (LLM_MODEL_<STAGE> names OpenCode models, which NIM does not know).
    """

    def __init__(self, api_key: str, base_url: str = model_catalog.DEFAULT_NIM_BASE, model: str = model_catalog.DEFAULT_NIM_MODEL):
        super().__init__(api_key=api_key, base_url=base_url, model=model, name="nvidia-nim")
        self.stage_models = {}

    def _extra_body(self, reasoning_effort: Optional[str], chosen: str) -> dict:
        return {}

    def _chat(self, system: Optional[str], user: str, temperature: float,
              mini: bool = False, model: Optional[str] = None, reasoning_effort: Optional[str] = None,
              stage: Optional[str] = None) -> str:
        if model and model_catalog.is_nim_id(model):
            model = model[len(model_catalog.NIM_PREFIX):]
        return super()._chat(system, user, temperature, mini=mini, model=model, reasoning_effort=reasoning_effort, stage=stage)


class OfflineProvider:
    name = "offline"

    def __init__(self):
        self._last_key: Optional[str] = None
        self._last_exact: bool = False

    def parse_intent(self, prompt: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> RTLDesignSpec:
        self._last_key = od.match_design(prompt)
        self._last_exact = od.is_exact_match(prompt)
        return RTLDesignSpec(**od.get_design(self._last_key)["spec"])

    def generate_rtl(self, spec: RTLDesignSpec, freq_hint: Optional[int],
                     model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        key = self._last_key or "counter"
        design = od.get_design(key)
        if self._buggy and "rtl_buggy" in design:
            return design["rtl_buggy"]
        return design["rtl"]

    def generate_testbench(self, rtl_code: str, spec: RTLDesignSpec,
                           model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        key = od.design_key_from_rtl(rtl_code) or self._last_key or "counter"
        return od.get_design(key)["tb"]

    def explain_design(self, rtl_code: str, spec: RTLDesignSpec,
                       model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        key = od.design_key_from_rtl(rtl_code) or self._last_key or "counter"
        base = od.get_design(key)["explanation"]
        if not self._last_exact:
            base = (
                f"[Offline demo] Your request was not an exact match for a built-in "
                f"design. Showing a representative counter design instead. {base}"
            )
        return base

    def fix_design(self, rtl_code: str, tb_code: str, log: str,
                   model: Optional[str] = None, reasoning_effort: Optional[str] = None,
                   spec: Optional[RTLDesignSpec] = None) -> dict:
        key = od.design_key_from_rtl(rtl_code) or self._last_key or "counter"
        golden = od.get_design(key)["rtl"]
        return {
            "rtl_code": golden,
            "testbench_code": tb_code,
            "fix_summary": "Offline scripted fix: replaced with known-correct implementation.",
            # Explicitly NOT a diagnosis. The offline path performs a golden swap,
            # so any "root cause" text here would be fabricated. Consumers must
            # render fix_type="offline_scripted" as a scripted regression path.
            "diagnosis": None,
            "fix_type": "offline_scripted",
        }

    # set by select_provider wrapper per-request
    _buggy = False


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def _placeholder(v: str) -> bool:
    return not v or v.strip().lower().startswith("your_")


def _is_offline_env() -> bool:
    return os.getenv("OFFLINE_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def _make_provider():
    """Pick a provider from env. Priority: OFFLINE_MODE -> Opencode Zen -> NVIDIA NIM -> OpenAI -> offline.

    Opencode Zen (remote, zero-budget, primary) — OpenAI-compatible free tier:
        OPENCODE_API_KEY=sk-...  (or ZEN_API_KEY alias)
        OPENCODE_BASE_URL=https://api.opencode.ai/v1  (or ZEN_BASE_URL; defaults to
            https://api.opencode.ai/v1, also accepts https://opencode.ai/api/v1)
        ZEN_MODEL / LLM_MODEL=opencode/muse-spark-1.2-contributor-free  # optional
    NVIDIA NIM (OpenAI-compatible, free credits at build.nvidia.com):
        NVIDIA_API_KEY=nvapi-...
        LLM_MODEL=qwen/qwen2.5-coder-32b-instruct   # optional, this is the default
    OpenAI:
        OPENAI_API_KEY=sk-...
    Any other OpenAI-compatible endpoint:
        OPENAI_API_KEY=... + OPENAI_BASE_URL=https://...
    OFFLINE_MODE=1 always forces OfflineProvider, even if keys are set.
    """
    if _is_offline_env():
        return OfflineProvider()

    # Explicit opt-in: drive the user's installed OpenCode app (see OpenCodeAppProvider).
    if os.getenv("LLM_PROVIDER", "").strip().lower() in ("opencode-app", "opencode-cli"):
        if shutil.which("opencode"):
            return OpenCodeAppProvider(model=os.getenv("LLM_MODEL", "").strip() or "mimo-v2.6-flash-free")
        return OfflineProvider()

    # 0) Opencode Zen — primary zero-budget remote provider (must be before NVIDIA/OpenAI)
    # Support both OPENCODE_* and ZEN_* env var aliases.
    _opencode_key = os.getenv("OPENCODE_API_KEY", "").strip()
    _zen_key = os.getenv("ZEN_API_KEY", "").strip()
    zen_key = ""
    if not _placeholder(_opencode_key):
        zen_key = _opencode_key
    elif not _placeholder(_zen_key):
        zen_key = _zen_key
    if zen_key:
        # Model: ZEN_MODEL > LLM_MODEL > default free model that actually works (tested 2026-09-05: nemotron-3.5-lightning-free success, muse-spark 500)
        _zen_model = os.getenv("ZEN_MODEL", "").strip()
        _llm_model = os.getenv("LLM_MODEL", "").strip()
        zen_model = _zen_model or _llm_model or "nemotron-3.5-lightning-free"
        # Base URL: OPENCODE_BASE_URL > ZEN_BASE_URL > default remote Zen endpoint.
        # Correct Zen gateway is https://opencode.ai/zen/v1 (verified via opencode --verbose)
        _base_raw = os.getenv("OPENCODE_BASE_URL", "").strip() or os.getenv("ZEN_BASE_URL", "").strip()
        zen_base = (_base_raw.rstrip("/") if _base_raw else "https://opencode.ai/zen/v1")
        # Normalize common user mistakes: ensure single /v1 or /zen/v1 suffix, no double slash
        if zen_base.endswith("/v1/v1"):
            zen_base = zen_base[:-3]
        if zen_base == "https://api.opencode.ai/v1":
            # Common wrong default from old docs - auto-correct to actual zen gateway
            zen_base = "https://opencode.ai/zen/v1"
        # Log effective base for debugging (key redacted)
        try:
            import logging
            logging.getLogger("siliconscribe").info("Zen provider base=%s model=%s", zen_base, zen_model)
        except Exception:
            pass
        try:
            return OpenAIProvider(api_key=zen_key, base_url=zen_base, model=zen_model, name="zen")
        except Exception:
            return OfflineProvider()

    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not _placeholder(nvidia_key):
        base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip()
        # qwen3-coder-480b was retired by NVIDIA on 2026-06-11 (HTTP 410). Use a
        # model that is actually in the catalogue; override with LLM_MODEL.
        model = os.getenv("LLM_MODEL", "mistralai/codestral-22b-instruct-v0.1").strip()
        try:
            return OpenAIProvider(api_key=nvidia_key, base_url=base, model=model, name="nvidia-nim")
        except Exception:
            return OfflineProvider()

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not _placeholder(openai_key):
        base = os.getenv("OPENAI_BASE_URL", "").strip() or None
        model = os.getenv("LLM_MODEL", "gpt-4o").strip()
        # A custom OpenAI-compatible gateway (OpenRouter, Groq, Ollama, ...) does
        # not necessarily serve gpt-4o-mini. Default the "mini" calls to the same
        # model there; only vanilla OpenAI gets gpt-4o-mini.
        _mini_env = os.getenv("LLM_MINI_MODEL", "").strip()
        mini = _mini_env or (model if base else "gpt-4o-mini")
        name = "openai-compatible" if base else "openai"
        try:
            return OpenAIProvider(api_key=openai_key, base_url=base, model=model, mini_model=mini, name=name)
        except Exception:
            return OfflineProvider()

    return OfflineProvider()


_provider = _make_provider()
# Singleton offline instance for dynamic OFFLINE_MODE forcing without re-creating
_offline_provider = _provider if isinstance(_provider, OfflineProvider) else OfflineProvider()


_cloudflare_cache: dict = {}
_nim_cache: dict = {}
_provider_lock = threading.Lock()


def _nim_provider() -> "NimProvider":
    cfg = model_catalog.nim_config()
    if cfg is None:
        raise ModelNotAvailable("NVIDIA NIM is not set up. Start the backend with NVIDIA_NIM_API_KEY set, "
                                "or pick another model.")
    with _provider_lock:                                          # rebuilt only if the key or address changes
        if _nim_cache.get("key") != cfg or "provider" not in _nim_cache:
            # Build first, then publish under the lock: two first requests at once used to read the key before the
            # provider existed (KeyError: 'provider'; found by a concurrent benchmark, 24 Nov).
            _nim_cache["provider"] = NimProvider(*cfg)
            _nim_cache["key"] = cfg
        return _nim_cache["provider"]


def _cloudflare_provider() -> "CloudflareProvider":
    cfg = model_catalog.cloudflare_config()
    if cfg is None:
        raise ModelNotAvailable("Cloudflare is not set up. Start the backend with CLOUDFLARE_ACCOUNT_ID and "
                                "CLOUDFLARE_API_TOKEN set, or pick an OpenCode model.")
    with _provider_lock:                                          # rebuilt only if the credentials change
        if _cloudflare_cache.get("key") != cfg or "provider" not in _cloudflare_cache:
            _cloudflare_cache["provider"] = CloudflareProvider(*cfg)
            _cloudflare_cache["key"] = cfg
        return _cloudflare_cache["provider"]


def get_provider(model: Optional[str] = None):
    """The provider that serves *model*: Cloudflare for `@cf/...` ids, NVIDIA NIM for `nim/...` ids, otherwise the configured one."""
    # Dynamic check: OFFLINE_MODE=1 must always force offline even if _provider was cached as zen
    if _is_offline_env():
        return _offline_provider
    if model and model_catalog.is_cloudflare_id(model):
        return _cloudflare_provider()
    if model and model_catalog.is_nim_id(model):
        return _nim_provider()
    return _provider


def current_model_id() -> Optional[str]:
    """The configured model as the model menu spells it (`opencode/<name>` for the OpenCode app)."""
    current = current_model()
    if current and isinstance(_provider, OpenCodeAppProvider):
        return model_catalog.normalize_opencode_id(current)
    return current


def is_default_model(model: Optional[str]) -> bool:
    """True when *model* is absent or is the configured model (spelled with or without the `opencode/` prefix)."""
    if not model:
        return True
    current = current_model()
    if not current:
        return False
    return model_catalog.normalize_opencode_id(model) == model_catalog.normalize_opencode_id(current) \
        if isinstance(_provider, OpenCodeAppProvider) else model == current


def is_offline() -> bool:
    if _is_offline_env():
        return True
    return getattr(_provider, "name", "") == "offline"


# --------------------------------------------------------------------------- #
# Model catalog — curated set verified to work with this app (return real,
# non-empty content). Reasoning models that emit only hidden "thinking" tokens
# are deliberately excluded because they return empty content.
# Priority: Zen (free, remote) first, then NVIDIA/OpenAI curated models.
# thinking_levels: actual variants from `opencode models --verbose` (not fake).
# For opencode models, variants are low/medium/high/xhigh etc. and are sent as
# `model:variant` suffix (e.g., opencode/gpt-5.3-codex-spark:high) and also as
# reasoning_effort extra_body. For models with no variants, thinking_levels is [].
# --------------------------------------------------------------------------- #
CURATED_MODELS = [
    {"id": "nemotron-3.5-lightning-free", "label": "Nemotron 3.5 Lightning (Zen Free)",
     "note": "Opencode Zen · free · quality code · actually works (tested)", "tag": "balanced",
     "thinking_levels": [], "reasoning": True},
    {"id": "muse-spark-1.2-contributor-free", "label": "Muse Spark 1.2 (Zen Free)",
     "note": "Opencode Zen · free · quality code", "tag": "balanced",
     "thinking_levels": [], "reasoning": True},
    {"id": "opencode/gpt-5.3-codex-spark", "label": "GPT-5.3 Codex Spark",
     "note": "Fast code · zen", "tag": "fast",
     "thinking_levels": ["low", "medium", "high", "xhigh"], "reasoning": True},
    {"id": "qwen/qwen3-coder-480b-a35b-instruct", "label": "Qwen3 Coder 480B",
     "note": "Code-specialized · most accurate · slow", "tag": "accurate",
     "thinking_levels": [], "reasoning": False},
    {"id": "qwen/qwen3.5-397b-a17b", "label": "Qwen3.5 397B",
     "note": "General flagship · accurate · slow", "tag": "accurate",
     "thinking_levels": [], "reasoning": False},
    {"id": "mistralai/mistral-large-3-675b-instruct-2512", "label": "Mistral Large 3",
     "note": "Large general · accurate", "tag": "accurate",
     "thinking_levels": [], "reasoning": False},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "label": "Nemotron 3 Super 120B",
     "note": "NVIDIA · balanced", "tag": "balanced",
     "thinking_levels": [], "reasoning": False},
    {"id": "meta/llama-3.3-70b-instruct", "label": "Llama 3.3 70B",
     "note": "Fast · less reliable for complex RTL", "tag": "fast",
     "thinking_levels": [], "reasoning": False},
]


def current_model() -> Optional[str]:
    prov = get_provider()
    return getattr(prov, "model", None) if not is_offline() else None


def list_models(include_paid: bool = False, refresh: bool = False) -> dict:
    """Models the user can choose for generation, grouped by where they run.

    * The OpenCode app (LLM_PROVIDER=opencode-app): every model `opencode models` reports. Models whose name
      says free come first; the rest are listed only with include_paid (they may use credits on the account;
      their price is not known from here, so they are never called "paid" for certain).
    * Any other configured provider: the curated list, or only the configured model (an unusable name sent
      by the UI used to trigger a silent degraded fallback).
    * Cloudflare Workers AI: its models when CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are set.
    * NVIDIA NIM: its chat models (ids prefixed `nim/`) when NVIDIA_NIM_API_KEY is set.
    The reply keeps the older keys (offline, current, models, stage_models) and adds `providers`, `paid_hidden` and
    `failed_hidden` (models hidden because they failed the last check, see model_catalog.hidden_models).
    """
    if is_offline():
        return {"offline": True, "current": "offline", "providers": [], "paid_hidden": 0, "models": [
            {"id": "offline", "label": "Offline Demo", "note": "Scripted designs, no LLM", "tag": "fast"},
        ]}
    current = current_model()
    prov = get_provider()
    hidden = 0
    if isinstance(prov, OpenCodeAppProvider):
        current_id = model_catalog.normalize_opencode_id(current) if current else None
        catalog = model_catalog.opencode_models(refresh)
        models = [m for m in catalog if m["free"] or include_paid or m["id"] == current_id]
        hidden = len(catalog) - len(models)
        if current_id and not any(m["id"] == current_id for m in models):       # configured but not in the app's list
            models.insert(0, {"id": current_id, "label": current_id.split("/", 1)[-1], "provider": "opencode", "group": "OpenCode",
                              "free": None, "note": "Configured model", "tag": "balanced", "thinking_levels": [], "reasoning": False})
        models.sort(key=lambda m: 0 if m["id"] == current_id else 1)             # stable: the configured model first
        current = current_id
    else:
        curated_ids = {m["id"] for m in CURATED_MODELS}
        if current and current not in curated_ids:
            models = [{"id": current, "label": current.split("/")[-1], "note": "Configured provider model", "tag": "balanced",
                       "thinking_levels": [], "reasoning": False}]
        else:
            models = [dict(m) for m in CURATED_MODELS]
            if current:
                models.sort(key=lambda m: 0 if m["id"] == current else 1)
        for m in models:
            m.setdefault("provider", "opencode")
            m.setdefault("group", "Models")
            m.setdefault("free", None)
    # Models that failed the last check (model_hidden.json) are not offered; the configured model always is.
    failed = model_catalog.hidden_models()
    keep = lambda ms: [m for m in ms if m["id"] not in failed or m["id"] == current]  # noqa: E731
    before = len(models)
    models = keep(models)
    failed_hidden = before - len(models)
    providers = [{"id": "opencode", "label": "OpenCode", "available": bool(models), "count": len(models),
                  "hint": None if models else "No models were found. Is the OpenCode app installed and signed in?"}]
    cf = model_catalog.cloudflare_status(refresh)
    cf_models = keep(cf["models"])
    providers.append({"id": "cloudflare", "label": "Cloudflare", "available": cf["available"], "count": len(cf_models), "hint": cf["hint"]})
    nim = model_catalog.nim_status(refresh)
    nim_models = keep(nim["models"])
    providers.append({"id": "nim", "label": "NVIDIA NIM", "available": nim["available"], "count": len(nim_models), "hint": nim["hint"]})
    failed_hidden += len(cf["models"]) - len(cf_models) + len(nim["models"]) - len(nim_models)
    models = models + cf_models + nim_models
    # Per-stage overrides (LLM_MODEL_TESTBENCH etc.) that differ from the default model. A request that
    # explicitly picks another model in the UI overrides them, so say where they apply.
    stage = {s: m for s, m in (getattr(prov, "stage_models", None) or {}).items() if m and m != current}
    if stage.get("testbench"):
        for m in models:
            if m["id"] == current:
                m["note"] = f"{m['note']} · testbench written by {stage['testbench']}"
    return {"offline": False, "current": current, "models": models, "stage_models": stage,
            "providers": providers, "paid_hidden": hidden, "failed_hidden": failed_hidden}


# --------------------------------------------------------------------------- #
# Public functions (used by the orchestrator and routes). `model` and
# `reasoning_effort` overrides the default for a single request (UI passes through).
# reasoning_effort is actual (low/medium/high/xhigh) for models with variants, not fake.
# --------------------------------------------------------------------------- #
def parse_intent(prompt: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> RTLDesignSpec:
    prov = get_provider(model)
    if isinstance(prov, OfflineProvider):
        prov._buggy = od.is_buggy_request(prompt)
    try:
        return prov.parse_intent(prompt, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.parse_intent(prompt, model=model)
        raise


def generate_rtl(spec: RTLDesignSpec, freq_hint: Optional[int] = None,
                 model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
    prov = get_provider(model)
    try:
        return prov.generate_rtl(spec, freq_hint, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.generate_rtl(spec, freq_hint, model=model)
        raise


def generate_testbench(rtl_code: str, spec: RTLDesignSpec, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
    prov = get_provider(model)
    try:
        return prov.generate_testbench(rtl_code, spec, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.generate_testbench(rtl_code, spec, model=model)
        raise


def explain_design(rtl_code: str, spec: RTLDesignSpec, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
    prov = get_provider(model)
    try:
        return prov.explain_design(rtl_code, spec, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.explain_design(rtl_code, spec, model=model)
        raise


def uses_offline(model: Optional[str] = None) -> bool:
    """True when *model* would be served by the offline demo provider (no AI connected)."""
    return isinstance(get_provider(model), OfflineProvider)


def agent_chat(system: str, user: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
    """One turn of the debugging agent (agent.py): plain text in, plain text out, on the chosen model."""
    prov = get_provider(model)
    if isinstance(prov, OfflineProvider):
        raise ModelNotAvailable("No AI model is connected (offline mode).")
    return prov._chat(system, user, temperature=0.1, model=model, reasoning_effort=reasoning_effort, stage="agent")


def fix_design(rtl_code: str, tb_code: str, log: str, model: Optional[str] = None,
               reasoning_effort: Optional[str] = None,
               spec: Optional[RTLDesignSpec] = None) -> dict:
    prov = get_provider(model)
    try:
        return prov.fix_design(rtl_code, tb_code, log, model=model,
                               reasoning_effort=reasoning_effort, spec=spec)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            try:
                return prov.fix_design(rtl_code, tb_code, log, model=model, spec=spec)
            except TypeError as e2:
                if "spec" in str(e2):
                    return prov.fix_design(rtl_code, tb_code, log, model=model)
                raise
        if "spec" in str(e):
            return prov.fix_design(rtl_code, tb_code, log, model=model,
                                   reasoning_effort=reasoning_effort)
        raise
