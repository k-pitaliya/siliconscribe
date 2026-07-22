"""
LLM service: natural language -> RTL spec -> Verilog -> testbench -> explanation,
plus the debugger entry point (fix_design) used by the self-correction loop.

Two providers behind one interface:
  - OpenAIProvider: GPT-4o (default when OPENAI_API_KEY is set and OFFLINE_MODE != 1)
  - OfflineProvider: deterministic canned designs (no key / no internet)

The module auto-selects: if OFFLINE_MODE=1, or no usable OPENAI_API_KEY, it falls
back to offline so the app never hard-fails in a demo.
"""

import os
import json
import re
from typing import Optional

from dotenv import load_dotenv

from models import RTLDesignSpec
import offline_designs as od

# override=True so the project's .env wins over any stale shell env vars
# (e.g. a NVIDIA_API_KEY exported in ~/.zshrc) — otherwise the app can silently
# authenticate with the wrong key.
load_dotenv(override=True)


# --------------------------------------------------------------------------- #
# Prompts (OpenAI path)
# --------------------------------------------------------------------------- #
INTENT_PARSER_PROMPT = """You are an expert RTL design specification parser. Convert a natural language hardware description into a structured JSON specification.

Extract: module name (snake_case), port list (name/direction/width/description), parameters, behavioral description, and constraints (combinational/sequential, reset style).

Output ONLY valid JSON matching this schema, no prose:
{
  "module_name": "string",
  "parameters": [{"name": "string", "type": "string", "default": 0}],
  "ports": [{"name": "string", "direction": "input|output|inout", "width": 1, "description": "string"}],
  "behavior": "string",
  "constraints": ["string"]
}"""

RTL_GENERATOR_PROMPT = """You are an expert Verilog RTL designer. Generate clean, synthesizable code.

TARGET: Icarus Verilog with -g2012. Use Verilog-2001 syntax:
- "reg"/"wire" not "logic"; "always @(posedge clk)" not "always_ff"; "always @(*)" not "always_comb"
- "integer" loop vars, not "int"; no SystemVerilog interfaces/classes/structs
- ANSI ports and parameters are fine: input wire [WIDTH-1:0] data, parameter WIDTH = 8
- Active-low reset preferred; no unintended latches; 4-space indent; header comment

FORMATTING (critical): write real, properly formatted multi-line Verilog with a
newline after every statement, port, and `begin`/`end`. NEVER collapse the module
onto one line — single-line code with `//` comments breaks compilation.

Output ONLY the Verilog code, no markdown fences or prose."""

TB_GENERATOR_PROMPT = """You are an expert Verilog verification engineer. Generate a self-checking testbench.

TARGET: Icarus Verilog with -g2012, Verilog-2001 syntax only (reg/wire, integer loop vars, no SV classes/interfaces).

REQUIRED:
1. The top module MUST be named "testbench".
2. Clock/reset generation if the DUT is sequential.
3. DUT instantiation with explicit named port connections.
4. Directed corner-case tests AND >=100 iterations of randomized stimulus (integer loop var, $random).
5. Self-checking: compute expected, compare with ===, count results in integer pass_count/fail_count.
6. Print EXACTLY these summary lines at the end:
   $display("Passed: %0d", pass_count);
   $display("Failed: %0d", fail_count);
   and if fail_count==0 also: $display("ALL TESTS PASSED");
7. Include waveform dump: $dumpfile("design.vcd"); $dumpvars(0, testbench);
8. End with $finish.

FORMATTING (critical): write real, properly formatted multi-line Verilog with a
newline after every statement and `begin`/`end`. NEVER collapse code onto one line.

Output ONLY the Verilog testbench code, no markdown fences or prose."""

FIX_PROMPT = """You are an expert hardware debugger. A Verilog design failed simulation under Icarus Verilog.

You are given the RTL, the testbench, and the simulator log (compile errors and/or test failures).
Treat the testbench's intent as the specification. Diagnose the root cause and fix it:
- Prefer fixing the RTL. Only change the testbench if the failure is a testbench bug (syntax, wrong expected value, bad stimulus).
- Keep Verilog-2001 / Icarus -g2012 compatibility (reg/wire, integer, no SV classes).
- Preserve module/port names so the testbench still binds.

Output ONLY valid JSON, no prose, no markdown fences:
{
  "rtl_code": "<full corrected RTL>",
  "testbench_code": "<full testbench, unchanged unless you fixed it>",
  "fix_summary": "<one concise sentence describing the fix>"
}"""


def _strip_code_fence(text: str) -> str:
    m = re.search(r'```(?:verilog|systemverilog|json)?\s*([\s\S]*?)\s*```', text)
    return m.group(1).strip() if m else text.strip()


def _extract_json(text: str) -> dict:
    fenced = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    raw = fenced.group(1) if fenced else text
    # Grab the outermost {...} if there is surrounding prose.
    brace = re.search(r'\{[\s\S]*\}', raw)
    return json.loads(brace.group(0) if brace else raw)


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
        self.client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self.model = model
        self.mini_model = mini_model or model
        self.name = name

    def _chat(self, system: Optional[str], user: str, temperature: float,
              mini: bool = False, model: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        chosen = model or (self.mini_model if mini else self.model)
        resp = self.client.chat.completions.create(
            model=chosen,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,  # generous headroom so long testbenches aren't truncated
        )
        msg = resp.choices[0].message
        content = msg.content or getattr(msg, "reasoning_content", None)
        if not content:
            raise RuntimeError(
                f"Model '{chosen}' returned empty content. This is usually a "
                f"'reasoning' model that exhausted its token budget while thinking. "
                f"Pick a non-reasoning model (e.g. meta/llama-3.3-70b-instruct or "
                f"qwen/qwen3-coder-480b-a35b-instruct)."
            )
        return content

    def parse_intent(self, prompt: str, model: Optional[str] = None) -> RTLDesignSpec:
        content = self._chat(INTENT_PARSER_PROMPT, prompt, 0.3, model=model)
        return RTLDesignSpec(**_extract_json(content))

    def generate_rtl(self, spec: RTLDesignSpec, freq_hint: Optional[int],
                     model: Optional[str] = None) -> str:
        freq = f"\nTarget clock frequency: {freq_hint} MHz." if freq_hint else ""
        user = (
            f"Generate Verilog for:\nModule: {spec.module_name}\n"
            f"Parameters: {json.dumps([p.model_dump() for p in spec.parameters])}\n"
            f"Ports: {json.dumps([p.model_dump() for p in spec.ports])}\n"
            f"Behavior: {spec.behavior}\nConstraints: {spec.constraints}{freq}"
        )
        return _strip_code_fence(self._chat(RTL_GENERATOR_PROMPT, user, 0.2, model=model))

    def generate_testbench(self, rtl_code: str, spec: RTLDesignSpec,
                           model: Optional[str] = None) -> str:
        user = (
            f"Write a Verilog-2001 testbench (top module named 'testbench') for:\n"
            f"```verilog\n{rtl_code}\n```\n"
            f"Module: {spec.module_name}\nPorts: {json.dumps([p.model_dump() for p in spec.ports])}"
        )
        return _strip_code_fence(self._chat(TB_GENERATOR_PROMPT, user, 0.3, model=model))

    def explain_design(self, rtl_code: str, spec: RTLDesignSpec,
                       model: Optional[str] = None) -> str:
        user = (
            f"Explain this Verilog module in 2-3 sentences for a hardware designer "
            f"(what it does, key design decisions). Be concise, no bullet points.\n\n"
            f"Module: {spec.module_name}\n```verilog\n{rtl_code}\n```"
        )
        # If the user picked a model, use it; otherwise the cheaper mini model.
        return self._chat(None, user, 0.5, mini=(model is None), model=model).strip()

    def fix_design(self, rtl_code: str, tb_code: str, log: str,
                   model: Optional[str] = None) -> dict:
        user = (
            f"RTL:\n```verilog\n{rtl_code}\n```\n\n"
            f"Testbench:\n```verilog\n{tb_code}\n```\n\n"
            f"Simulator log:\n```\n{log[-2000:]}\n```"
        )
        data = _extract_json(self._chat(FIX_PROMPT, user, 0.2, model=model))
        return {
            "rtl_code": _strip_code_fence(data.get("rtl_code", rtl_code)),
            "testbench_code": _strip_code_fence(data.get("testbench_code", tb_code)),
            "fix_summary": data.get("fix_summary", "Applied a fix."),
            "fix_type": "llm_diagnosis",
        }


class OfflineProvider:
    name = "offline"

    def __init__(self):
        self._last_key: Optional[str] = None
        self._last_exact: bool = False

    def parse_intent(self, prompt: str, model: Optional[str] = None) -> RTLDesignSpec:
        self._last_key = od.match_design(prompt)
        self._last_exact = od.is_exact_match(prompt)
        return RTLDesignSpec(**od.get_design(self._last_key)["spec"])

    def generate_rtl(self, spec: RTLDesignSpec, freq_hint: Optional[int],
                     model: Optional[str] = None) -> str:
        key = self._last_key or "counter"
        design = od.get_design(key)
        # If the user asked for a buggy design (demo of the self-correction loop)
        # and a buggy variant exists, return it so the loop has something to fix.
        if self._buggy and "rtl_buggy" in design:
            return design["rtl_buggy"]
        return design["rtl"]

    def generate_testbench(self, rtl_code: str, spec: RTLDesignSpec,
                           model: Optional[str] = None) -> str:
        key = od.design_key_from_rtl(rtl_code) or self._last_key or "counter"
        return od.get_design(key)["tb"]

    def explain_design(self, rtl_code: str, spec: RTLDesignSpec,
                       model: Optional[str] = None) -> str:
        key = od.design_key_from_rtl(rtl_code) or self._last_key or "counter"
        base = od.get_design(key)["explanation"]
        if not self._last_exact:
            base = (
                f"[Offline demo] Your request was not an exact match for a built-in "
                f"design. Showing a representative counter design instead. {base}"
            )
        return base

    def fix_design(self, rtl_code: str, tb_code: str, log: str,
                   model: Optional[str] = None) -> dict:
        key = od.design_key_from_rtl(rtl_code) or self._last_key or "counter"
        golden = od.get_design(key)["rtl"]
        return {
            "rtl_code": golden,
            "testbench_code": tb_code,
            "fix_summary": "Offline scripted fix: replaced with known-correct implementation.",
            "fix_type": "offline_scripted",
        }

    # set by select_provider wrapper per-request
    _buggy = False


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #
def _placeholder(v: str) -> bool:
    return not v or v.startswith("your_")


def _make_provider():
    """Pick a provider from env. Priority: OFFLINE_MODE -> NVIDIA NIM -> OpenAI -> offline.

    NVIDIA NIM (OpenAI-compatible, free credits at build.nvidia.com):
        NVIDIA_API_KEY=nvapi-...
        LLM_MODEL=qwen/qwen2.5-coder-32b-instruct   # optional, this is the default
    OpenAI:
        OPENAI_API_KEY=sk-...
    Any other OpenAI-compatible endpoint:
        OPENAI_API_KEY=... + OPENAI_BASE_URL=https://...
    """
    if os.getenv("OFFLINE_MODE", "").strip() in ("1", "true", "True"):
        return OfflineProvider()

    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not _placeholder(nvidia_key):
        base = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").strip()
        model = os.getenv("LLM_MODEL", "qwen/qwen3-coder-480b-a35b-instruct").strip()
        try:
            return OpenAIProvider(api_key=nvidia_key, base_url=base, model=model, name="nvidia-nim")
        except Exception:
            return OfflineProvider()

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not _placeholder(openai_key):
        base = os.getenv("OPENAI_BASE_URL", "").strip() or None
        model = os.getenv("LLM_MODEL", "gpt-4o").strip()
        mini = os.getenv("LLM_MINI_MODEL", "gpt-4o-mini").strip()
        name = "openai-compatible" if base else "openai"
        try:
            return OpenAIProvider(api_key=openai_key, base_url=base, model=model, mini_model=mini, name=name)
        except Exception:
            return OfflineProvider()

    return OfflineProvider()


_provider = _make_provider()


def get_provider():
    return _provider


def is_offline() -> bool:
    return _provider.name == "offline"


# --------------------------------------------------------------------------- #
# Model catalog — curated set verified to work with this app (return real,
# non-empty content). Reasoning models that emit only hidden "thinking" tokens
# are deliberately excluded because they return empty content.
# --------------------------------------------------------------------------- #
CURATED_MODELS = [
    {"id": "qwen/qwen3-coder-480b-a35b-instruct", "label": "Qwen3 Coder 480B",
     "note": "Code-specialized · most accurate · slow", "tag": "accurate"},
    {"id": "qwen/qwen3.5-397b-a17b", "label": "Qwen3.5 397B",
     "note": "General flagship · accurate · slow", "tag": "accurate"},
    {"id": "mistralai/mistral-large-3-675b-instruct-2512", "label": "Mistral Large 3",
     "note": "Large general · accurate", "tag": "accurate"},
    {"id": "nvidia/nemotron-3-super-120b-a12b", "label": "Nemotron 3 Super 120B",
     "note": "NVIDIA · balanced", "tag": "balanced"},
    {"id": "meta/llama-3.3-70b-instruct", "label": "Llama 3.3 70B",
     "note": "Fast · less reliable for complex RTL", "tag": "fast"},
]


def current_model() -> Optional[str]:
    return getattr(_provider, "model", None) if not is_offline() else None


def list_models() -> dict:
    """Models the user can choose for generation. Empty in offline mode."""
    if is_offline():
        return {"offline": True, "current": None, "models": []}
    return {"offline": False, "current": current_model(), "models": CURATED_MODELS}


# --------------------------------------------------------------------------- #
# Public functions (used by the orchestrator and routes). `model` overrides the
# default for a single request (the UI model picker passes it through).
# --------------------------------------------------------------------------- #
def parse_intent(prompt: str, model: Optional[str] = None) -> RTLDesignSpec:
    if isinstance(_provider, OfflineProvider):
        _provider._buggy = od.is_buggy_request(prompt)
    return _provider.parse_intent(prompt, model=model)


def generate_rtl(spec: RTLDesignSpec, freq_hint: Optional[int] = None,
                 model: Optional[str] = None) -> str:
    return _provider.generate_rtl(spec, freq_hint, model=model)


def generate_testbench(rtl_code: str, spec: RTLDesignSpec, model: Optional[str] = None) -> str:
    return _provider.generate_testbench(rtl_code, spec, model=model)


def explain_design(rtl_code: str, spec: RTLDesignSpec, model: Optional[str] = None) -> str:
    return _provider.explain_design(rtl_code, spec, model=model)


def fix_design(rtl_code: str, tb_code: str, log: str, model: Optional[str] = None) -> dict:
    return _provider.fix_design(rtl_code, tb_code, log, model=model)
