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
              mini: bool = False, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        chosen = model or (self.mini_model if mini else self.model)
        # Handle thinking level as model:variant suffix for opencode zen (e.g., opencode/claude-fable-5:high)
        # If reasoning_effort is provided and model has variants, append :variant to model name
        if reasoning_effort and ":" not in chosen and chosen.startswith("opencode/"):
            # Check if this model actually has that variant - we trust caller, zen will 404 if invalid and fallback will handle
            chosen = f"{chosen}:{reasoning_effort}"
        # For templated tests that pass reasoning_effort but model is offline, ignore
        create_kwargs = {
            "model": chosen,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 8192,
            "timeout": 20,
        }
        # Pass reasoning_effort as extra_body for providers that support it (e.g., opencode, openai o1)
        # For opencode, the variant suffix already encodes effort, but also pass as param for compatibility
        extra = {}
        if reasoning_effort:
            # For opencode models with variants, the suffix is primary; also try reasoning_effort param
            # Some gateways expect `reasoning_effort` top-level, others `reasoning: {effort: ...}`
            # We send both via extra_body to maximize compatibility
            extra["reasoning_effort"] = reasoning_effort
            extra["reasoning"] = {"effort": reasoning_effort}
        if extra:
            # OpenAI SDK supports extra_body for pass-through
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
                    raise RuntimeError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e2)[:300]}") from e2
            else:
                err_type = type(e).__name__
                base = getattr(self.client, "base_url", "") or getattr(self, "base_url", "")
                raise RuntimeError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e)[:300]}") from e
        except Exception as e:
            # Map upstream 404/401/timeout to a typed error the orchestrator can fallback on
            err_type = type(e).__name__
            base = getattr(self.client, "base_url", "") or getattr(self, "base_url", "")
            raise RuntimeError(f"LLM_UPSTREAM:{err_type}: base={base} model={chosen} err={str(e)[:300]}") from e
        # Defensive: some gateways return plain string or empty choices
        if isinstance(resp, str):
            raise RuntimeError(f"LLM_UPSTREAM:InvalidResponse: provider returned str (check base_url) resp={resp[:300]}")
        choices = getattr(resp, "choices", None)
        if not choices:
            raise RuntimeError(f"LLM_UPSTREAM:EmptyChoices: base={getattr(self.client, 'base_url', '')} model={chosen} resp={str(resp)[:500]}")
        msg = choices[0].message if hasattr(choices[0], "message") else choices[0].get("message") if isinstance(choices[0], dict) else None
        if msg is None:
            raise RuntimeError(f"LLM_UPSTREAM:NoMessage: model={chosen} choice={str(choices[0])[:500]}")
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        if not content:
            content = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
            if isinstance(msg, dict):
                content = msg.get("reasoning_content") or msg.get("reasoning")
        if not content or not str(content).strip():
            raise RuntimeError(
                f"Model '{chosen}' returned empty content. This is usually a "
                f"'reasoning' model that exhausted its token budget while thinking. "
                f"Pick a non-reasoning model (e.g. meta/llama-3.3-70b-instruct or "
                f"qwen/qwen3-coder-480b-a35b-instruct)."
            )
        return str(content)

    def parse_intent(self, prompt: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> RTLDesignSpec:
        content = self._chat(INTENT_PARSER_PROMPT, prompt, 0.3, model=model, reasoning_effort=reasoning_effort)
        return RTLDesignSpec(**_extract_json(content))

    def generate_rtl(self, spec: RTLDesignSpec, freq_hint: Optional[int],
                     model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        freq = f"\nTarget clock frequency: {freq_hint} MHz." if freq_hint else ""
        user = (
            f"Generate Verilog for:\nModule: {spec.module_name}\n"
            f"Parameters: {json.dumps([p.model_dump() for p in spec.parameters])}\n"
            f"Ports: {json.dumps([p.model_dump() for p in spec.ports])}\n"
            f"Behavior: {spec.behavior}\nConstraints: {spec.constraints}{freq}"
        )
        return _strip_code_fence(self._chat(RTL_GENERATOR_PROMPT, user, 0.2, model=model, reasoning_effort=reasoning_effort))

    def generate_testbench(self, rtl_code: str, spec: RTLDesignSpec,
                           model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        user = (
            f"Write a Verilog-2001 testbench (top module named 'testbench') for:\n"
            f"```verilog\n{rtl_code}\n```\n"
            f"Module: {spec.module_name}\nPorts: {json.dumps([p.model_dump() for p in spec.ports])}"
        )
        return _strip_code_fence(self._chat(TB_GENERATOR_PROMPT, user, 0.3, model=model, reasoning_effort=reasoning_effort))

    def explain_design(self, rtl_code: str, spec: RTLDesignSpec,
                       model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
        user = (
            f"Explain this Verilog module in 2-3 sentences for a hardware designer "
            f"(what it does, key design decisions). Be concise, no bullet points.\n\n"
            f"Module: {spec.module_name}\n```verilog\n{rtl_code}\n```"
        )
        # If the user picked a model, use it; otherwise the cheaper mini model.
        return self._chat(None, user, 0.5, mini=(model is None), model=model, reasoning_effort=reasoning_effort).strip()

    def fix_design(self, rtl_code: str, tb_code: str, log: str,
                   model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> dict:
        user = (
            f"RTL:\n```verilog\n{rtl_code}\n```\n\n"
            f"Testbench:\n```verilog\n{tb_code}\n```\n\n"
            f"Simulator log:\n```\n{log[-2000:]}\n```"
        )
        data = _extract_json(self._chat(FIX_PROMPT, user, 0.2, model=model, reasoning_effort=reasoning_effort))
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
                   model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> dict:
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
        # Model: ZEN_MODEL > LLM_MODEL > default Spark model.
        _zen_model = os.getenv("ZEN_MODEL", "").strip()
        _llm_model = os.getenv("LLM_MODEL", "").strip()
        zen_model = _zen_model or _llm_model or "opencode/muse-spark-1.2-contributor-free"
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
# Singleton offline instance for dynamic OFFLINE_MODE forcing without re-creating
_offline_provider = _provider if isinstance(_provider, OfflineProvider) else OfflineProvider()


def get_provider():
    # Dynamic check: OFFLINE_MODE=1 must always force offline even if _provider was cached as zen
    if _is_offline_env():
        return _offline_provider
    return _provider


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
    {"id": "opencode/muse-spark-1.2-contributor-free", "label": "Muse Spark 1.2 (Zen Free)",
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


def list_models() -> dict:
    """Models the user can choose for generation."""
    if is_offline():
        return {"offline": True, "current": "offline", "models": [
            {"id": "offline", "label": "Offline Demo", "note": "Scripted designs, no LLM", "tag": "fast"},
        ]}
    return {"offline": False, "current": current_model(), "models": CURATED_MODELS}


# --------------------------------------------------------------------------- #
# Public functions (used by the orchestrator and routes). `model` and
# `reasoning_effort` overrides the default for a single request (UI passes through).
# reasoning_effort is actual (low/medium/high/xhigh) for models with variants, not fake.
# --------------------------------------------------------------------------- #
def parse_intent(prompt: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> RTLDesignSpec:
    prov = get_provider()
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
    prov = get_provider()
    try:
        return prov.generate_rtl(spec, freq_hint, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.generate_rtl(spec, freq_hint, model=model)
        raise


def generate_testbench(rtl_code: str, spec: RTLDesignSpec, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
    prov = get_provider()
    try:
        return prov.generate_testbench(rtl_code, spec, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.generate_testbench(rtl_code, spec, model=model)
        raise


def explain_design(rtl_code: str, spec: RTLDesignSpec, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> str:
    prov = get_provider()
    try:
        return prov.explain_design(rtl_code, spec, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.explain_design(rtl_code, spec, model=model)
        raise


def fix_design(rtl_code: str, tb_code: str, log: str, model: Optional[str] = None, reasoning_effort: Optional[str] = None) -> dict:
    prov = get_provider()
    try:
        return prov.fix_design(rtl_code, tb_code, log, model=model, reasoning_effort=reasoning_effort)
    except TypeError as e:
        if "reasoning_effort" in str(e):
            return prov.fix_design(rtl_code, tb_code, log, model=model)
        raise
