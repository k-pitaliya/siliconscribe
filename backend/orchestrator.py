"""
The agentic pipeline.

    prompt -> parse_intent -> generate_rtl -> generate_testbench -> explain
           -> [lint] -> simulate -> [FAIL/ERROR? fix_design -> lint -> re-simulate] (loop) -> done
           -> coverage + vcd + schematic + synthesis -> done

`pipeline_events` is a generator that yields one event per stage so the API can
stream progress over SSE (this drives the live AI-agent panel). `run_pipeline`
consumes those events and returns a complete RunResponse for the one-shot route.

Systematic fallback: If Zen LLM upstream fails (404/timeout/choices error), the
pipeline falls back to OfflineProvider for the entire run, yielding a
fallback_notice and completing with PASS (offline curated), never 500.

No-progress guard:
  - Content hashing (not exact string equality) detects identical RTL/TB
    regardless of whitespace changes.
  - Oscillation detection: if an RTL hash we have already seen reappears,
    the loop stops immediately to prevent thrashing.

Linter integration (non-blocking):
  - Before each simulation, VerilogLinter is run on the current RTL+TB.
  - If lint finds errors/warnings, a ``stage="lint"`` event is yielded.
  - Lint never blocks the pipeline.
"""

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Iterator, Optional

import llm_service
from cov_metrics import compute_coverage
from mutation import run_strength, weak_strength_note
from timing import missing_requirements as timing_missing, run_timing, timing_message
from schematic import build_schematic
from simulator import IcarusSimulator
from vcd_parser import parse_vcd
from models import (
    RunResponse, IterationRecord, RTLDesignSpec, SecondOpinion,
)

# Optional synthesis — must not break import when yosys not installed
try:
    from synthesis import YosysSynthesizer  # type: ignore
except Exception:  # pragma: no cover
    YosysSynthesizer = None  # type: ignore

# Optional linter — must not break import when tool chain is absent
try:
    from linter import VerilogLinter  # type: ignore
except Exception:  # pragma: no cover
    VerilogLinter = None  # type: ignore

logger = logging.getLogger("siliconscribe.orchestrator")

# Strings and comments must never count as code: `// $error` or a message string
# mentioning fail_count used to satisfy the "TB has checks" guard.
_STRING_OR_COMMENT_RE = re.compile(r'"(?:\\.|[^"\\\n])*"|//[^\n]*|/\*[\s\S]*?\*/')



class MidRunUnavailable(RuntimeError):
    """The model stopped answering after the run had already produced live artifacts."""

    def __init__(self, message: str, reason: str = ""):
        super().__init__(message)
        self.reason = reason

def _strip_comments_and_strings(code: str) -> str:
    return _STRING_OR_COMMENT_RE.sub(" ", code or "")


# A testbench "check" is a place where it can actually fail the DUT. Count those so a
# fix cannot make a failing design pass by deleting its self-checks. Only genuine
# failure bookkeeping counts: an increment of a fail/error counter, $error/$fatal, an
# assertion, or a call of the standard `chk(...)` task. A bare `fail_count = 0`
# initialiser is NOT a check (review finding: it satisfied the old guard).
_TB_CHECK_RE = re.compile(
    r"\b\w*(?:fail|error|err)\w*\s*(?:\+\+|\+=)"                # fail_count++ / += n
    r"|\b(\w*(?:fail|error|err)\w*)\s*(?:<=|=)\s*\1\s*\+"       # fail_count = fail_count + 1
    r"|\$(?:error|fatal)\b"                                       # $error / $fatal
    r"|\bassert\s*\("                                             # immediate assertion
    r"|\bchk\s*\(",                                               # the standard check task
    re.IGNORECASE,
)


def _tb_check_count(tb: str) -> int:
    return len(_TB_CHECK_RE.findall(_strip_comments_and_strings(tb)))


def _instantiates_dut(tb: str, module_name: str) -> bool:
    """True if the testbench really instantiates ``module_name`` (not just mentions it)."""
    pat = (rf"\b{re.escape(module_name)}\s*(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?\w+\s*\(")
    return re.search(pat, _strip_comments_and_strings(tb)) is not None


def _tb_problems(tb: str, module_name: str) -> list[str]:
    """Reasons a testbench cannot be trusted as verification (empty list = acceptable)."""
    problems = []
    if not _has_complete_module(tb, "testbench"):
        problems.append("it is not a complete module named 'testbench'")
    if _tb_check_count(tb) == 0:
        problems.append("it contains no self-checks")
    if not _instantiates_dut(tb, module_name):
        problems.append(f"it does not instantiate the DUT module '{module_name}'")
    return problems


# Mutation-based testbench strength is on by default; set STRENGTH_ENABLED=0 to skip it.
STRENGTH_ENABLED = os.getenv("STRENGTH_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

# Pre-layout timing runs after a PASS when Yosys, OpenSTA and the cell library are present.
TIMING_ENABLED = os.getenv("TIMING_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")

# A PASS is only as good as the checks behind it. Below this many executed checks
# (or fewer than the whole input space for tiny combinational blocks) the app
# says so instead of presenting a bare PASS.
MIN_EXECUTED_CHECKS = 20
_CLK_RST_RE = re.compile(r"(?i)^(clk|clock|rst|reset)\w*$")


def weak_verification_note(spec: RTLDesignSpec, result) -> Optional[str]:
    """Return a warning when a PASS rests on too few executed checks, else None."""
    if result.status != "PASS":
        return None
    bits = sum(p.width for p in spec.ports
               if p.direction == "input" and not _CLK_RST_RE.match(p.name))
    floor = min(MIN_EXECUTED_CHECKS, 2 ** min(bits, 20))
    if result.test_count >= floor:
        return None
    return (f"Weak evidence: the testbench executed only {result.test_count} checks "
            f"(at least {floor} expected), so this PASS says little about correctness.")


def _has_complete_module(code: str, module_name: str) -> bool:
    """True if *code* contains a complete ``module <name> ... endmodule`` unit."""
    # Comments and strings removed first (self-review: "// module counter" next to `module up_counter` passed).
    code = re.sub(r'"(?:\\.|[^"\\\n])*"|/\*.*?\*/|//[^\n]*', " ", code or "", flags=re.S)
    if not re.search(r"\bendmodule\b", code):
        return False
    return re.search(rf"\bmodule\s+{re.escape(module_name)}\b", code) is not None


def _repair_compile_errors(rtl: str, tb: str, log: str) -> tuple[str, str, list[str]]:
    """Apply unambiguous compiler-evidenced repairs (currently wire→reg).

    Icarus reports ``file.sv:LINE: error: X is not a valid l-value here`` when a
    net is driven from a procedural block. That is a mechanical fix, not a design
    decision, so we repair it deterministically instead of asking an LLM to
    guess. Repairs are scoped to the file named in the diagnostic and returned as
    ``["testbench.sv:X", ...]`` so the caller can report the real location.
    """
    if not log:
        return rtl, tb, []

    # Map each l-value diagnostic to the file the compiler blamed. Both files are
    # always written as design.sv / testbench.sv by IcarusSimulator.
    by_file: dict[str, set[str]] = {}
    for file, name in re.findall(
            r"\b(design\.sv|testbench\.sv):\d+:[^\n]*?(\w+)\s+is not a valid l-value",
            log):
        by_file.setdefault(file, set()).add(name)
    if not by_file:
        # Older Icarus versions omit the filename on this diagnostic; fall back
        # to the testbench because that is where generated checking state lives.
        names = set(re.findall(r"(\w+)\s+is not a valid l-value", log))
        if names:
            by_file["testbench.sv"] = names

    def _wire_to_reg(code: str, names: set[str]) -> tuple[str, list[str]]:
        repaired: list[str] = []
        for name in sorted(names):
            # `wire [3:0] name;` -> `reg [3:0] name;` (declaration only)
            pattern = rf"\bwire\b(\s*(?:\[[^\]]*\]\s*)?{re.escape(name)}\s*;)"
            code, n = re.subn(pattern, r"reg\1", code)
            if n:
                repaired.append(name)
        return code, repaired

    repaired: list[str] = []
    if "design.sv" in by_file:
        rtl, names = _wire_to_reg(rtl, by_file["design.sv"])
        repaired.extend(f"design.sv:{n}" for n in names)
    if "testbench.sv" in by_file:
        tb, names = _wire_to_reg(tb, by_file["testbench.sv"])
        repaired.extend(f"testbench.sv:{n}" for n in names)
    return rtl, tb, repaired


def _repair_disable_functions(rtl: str, tb: str, log: str) -> tuple[str, str, list[str]]:
    """Repair Icarus ``Cannot disable functions`` diagnostics.

    Generated testbenches sometimes use ``disable <function>;`` as an early
    return. Icarus -g2012 rejects that but accepts ``return <function>;`` from a
    named function, which preserves the oracle's first-match semantics.
    """
    if "cannot disable functions" not in (log or "").lower():
        return rtl, tb, []
    repaired: list[str] = []

    def _fix(code: str, file: str) -> str:
        def _repl(m):
            body = m.group(0)
            nm = re.search(
                r"\bfunction\b(?:\s+automatic)?(?:\s+\[[^\]]*\])?\s+([A-Za-z_]\w*)",
                body)
            if not nm:
                return body
            name = nm.group(1)
            if not re.search(rf"\bdisable\s+{re.escape(name)}\s*;", body):
                return body
            new_body, n = re.subn(rf"\bdisable\s+{re.escape(name)}\s*;",
                                  f"return {name};", body)
            if n:
                repaired.append(f"{file}:function {name}")
            return new_body
        return re.sub(r"\bfunction\b[\s\S]*?\bendfunction\b", _repl, code)

    rtl = _fix(rtl, "design.sv")
    tb = _fix(tb, "testbench.sv")
    return rtl, tb, repaired


def _compiler_repairs(rtl: str, tb: str, log: str) -> tuple[str, str, list[dict]]:
    """Return deterministic, compiler-evidenced repairs with structured diagnoses."""
    rtl2, tb2, names = _repair_disable_functions(rtl, tb, log)
    if names:
        repairs = []
        for item in names:
            file, func = item.split(":", 1)
            repairs.append({
                "kind": "disable_in_function",
                "file": file,
                "name": func,
                "symptom": f"Icarus cannot disable {func} inside a function.",
                "root_cause": (
                    "The function uses `disable` as an early return, which Icarus "
                    "rejects. A Verilog function must exit normally; using a "
                    "first-match if/else-if chain or a found flag avoids the "
                    "illegal early exit."),
                "summary": (
                    f"Compiler repair: replaced `disable` with `return` in {func} "
                    f"({file}), preserving the first-match oracle."),
            })
        return rtl2, tb2, repairs

    rtl2, tb2, names = _repair_compile_errors(rtl, tb, log)
    repairs = []
    for item in names:
        file, name = item.split(":", 1)
        repairs.append({
            "kind": "wire_to_reg",
            "file": file,
            "name": name,
            "symptom": f"Compilation failed: {name} is not a valid l-value.",
            "root_cause": (
                f"{name} is declared as a wire but assigned inside a procedural "
                "block. A wire is a continuous net and cannot be assigned from "
                "initial/always; it must be a reg."),
            "summary": (
                f"Compiler repair: changed wire to reg for {name} in {file} "
                "(Icarus l-value diagnostic)."),
        })
    return rtl2, tb2, repairs


def _is_upstream_error(e: Exception) -> bool:
    """True only for failures originating at the LLM provider.

    Deliberately narrow: the previous version used bare substring tests
    ("LLM", "API", "choices") combined with `and`/`or` precedence bugs, so any
    exception mentioning e.g. "CAPABILITY" or "choices" was misclassified as an
    upstream outage and silently masked by the offline fallback. Programming
    errors must surface, not be papered over.
    """
    if isinstance(e, llm_service.LLMUpstreamError):
        return True
    s = str(e)
    if "LLM_UPSTREAM" in s:
        return True
    # Words only. Bare status numbers ("500", "504") used to match unrelated text such as
    # "(char 504)" in a JSON error or "reasoning_tokens=2500", which silently swapped a
    # user's design for the offline demo (review finding, reproduced).
    low = s.lower()
    markers = (
        "api connection", "connection error", "timed out", "rate limit",
        "service unavailable", "bad gateway", "no choices", "empty content",
        "apiconnectionerror", "apitimeouterror", "authenticationerror",
    )
    return any(m in low for m in markers)


def _short_reason(e: Exception) -> str:
    """One-line, user-safe reason for a provider failure (shown in the fallback banner)."""
    s = str(e)
    if "err=" in s:
        s = s.split("err=", 1)[1]
    s = re.sub(r"^\s*(?:RuntimeError:\s*)?LLM_UPSTREAM:\w+:\s*", "", s)   # internal prefix (self-review finding)
    s = re.sub(r"\{.*\}", "", s, flags=re.S)                             # provider JSON blobs say nothing to the user
    s = re.sub(r"\s+", " ", s).strip(" :")
    return (s[:140] + "…") if len(s) > 140 else s


def _lint_payload(lint_res: dict) -> dict:
    """Convert VerilogLinter result (with SimError objects) to JSON-serialisable payload."""
    def _dump(e):
        if hasattr(e, "model_dump"):
            return e.model_dump()
        if isinstance(e, dict):
            return e
        return {"message": str(e)}
    return {
        "ok": lint_res.get("ok", True),
        "errors": [_dump(e) for e in lint_res.get("errors", [])],
        "warnings": [_dump(w) for w in lint_res.get("warnings", [])],
        "output": lint_res.get("output", ""),
    }


def pipeline_events(
    prompt: str,
    design_id: str,
    simulator: IcarusSimulator,
    target_frequency_mhz: Optional[int] = None,
    self_correct: bool = True,
    max_iterations: int = 3,
    timeout_seconds: int = 30,
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    testbench_model: Optional[str] = None,
    spec_override: Optional[RTLDesignSpec] = None,
) -> Iterator[dict]:
    """Yield {stage, ...} events as the pipeline runs.

    *testbench_model* names a DIFFERENT model to write the testbench. Then the oracle is independent of the design's
    author: a failing check is reported, never rewritten away by the design model (only a testbench that does not
    compile or hangs may be repaired).
    """
    model_label = model or llm_service.current_model_id() or "default"
    tb_model = testbench_model or model
    # Compare normalised ids: "x-free" and "opencode/x-free" are the same model (self-review finding).
    _norm = llm_service.model_catalog.normalize_opencode_id
    independent_tb = bool(testbench_model) and _norm(testbench_model) != _norm(model or llm_service.current_model_id() or "")
    try:
        # Only a Cloudflare / NIM id needs the routed lookup; everything else is the configured provider.
        provider_name = (llm_service.get_provider(model) if llm_service.model_catalog.is_routed_id(model)
                         else llm_service.get_provider()).name
    except llm_service.ModelNotAvailable:       # Cloudflare / NIM chosen but not set up: the first call reports it
        provider_name = "nvidia-nim" if llm_service.model_catalog.is_nim_id(model) else "cloudflare"
    yield {"stage": "start",
           "message": f"Parsing requirement (provider: {provider_name}, model: {model_label}"
                      + (f"; testbench by {testbench_model}" if independent_tb else "") + ")..."}
    # A model the user deliberately picked is never silently replaced by the scripted offline demo.
    explicit_model = bool(model) and not llm_service.is_default_model(model)

    # Systematic fallback state: local to this pipeline run, never mutates global singleton
    use_offline = False
    offline_provider = None
    fallback_notice = None
    # True once any live call has succeeded. Blocks mid-run switches to the
    # curated offline provider, which would silently swap a user's design.
    live_ok = False

    # OFFLINE_MODE configures an OfflineProvider. Route the entire run through a
    # per-run instance instead of the shared singleton so `_buggy`/`_last_key`
    # cannot leak between concurrent requests.
    # Decide with the provider that serves THIS model: a Cloudflare / NIM model the user picked must not be
    # replaced by the demo just because the default provider (e.g. the OpenCode app) is unavailable (review finding).
    try:
        serving = (llm_service.get_provider(model) if llm_service.model_catalog.is_routed_id(model)
                   else llm_service.get_provider())
        if isinstance(serving, llm_service.OfflineProvider):
            use_offline = True
    except Exception:
        pass

    def _get_offline():
        nonlocal offline_provider
        if offline_provider is None:
            from llm_service import OfflineProvider
            offline_provider = OfflineProvider()
            # Per-run provider instance: the buggy-demo flag must never live on
            # the shared module-level singleton (concurrent requests leaked it).
            try:
                import offline_designs as _od
                offline_provider._buggy = _od.is_buggy_request(prompt)
            except Exception:
                offline_provider._buggy = False
        return offline_provider

    # Optional kwargs that older provider stubs and test doubles may not accept.
    _OPTIONAL_KWARGS = ("reasoning_effort", "spec")

    def _invoke(fn, args, kwargs):
        """Call fn, dropping optional kwargs it does not declare.

        A TypeError is treated as an argument mismatch ONLY when the message
        names one of _OPTIONAL_KWARGS as an unexpected keyword. Any other
        TypeError is a real bug and propagates.
        """
        kwargs = dict(kwargs)
        for _ in range(len(_OPTIONAL_KWARGS) + 1):
            try:
                return fn(*args, **kwargs)
            except TypeError as e:
                msg = str(e)
                dropped = next(
                    (n for n in _OPTIONAL_KWARGS
                     if n in kwargs and f"'{n}'" in msg),
                    None,
                )
                if dropped is None:
                    raise
                kwargs.pop(dropped)
        return fn(*args, **kwargs)

    def _offline_call(fn_name: str, args, kwargs):
        return _invoke(getattr(_get_offline(), fn_name), args, kwargs)

    def _call_llm(fn_name: str, *args, **kwargs):
        nonlocal use_offline, fallback_notice, live_ok
        # If already in offline mode, directly use offline provider
        if use_offline:
            return _offline_call(fn_name, args, kwargs)
        try:
            out = _invoke(getattr(llm_service, fn_name), args, kwargs)
        except Exception as e:
            if not _is_upstream_error(e):
                raise
            if independent_tb and fn_name == "generate_testbench":
                raise RuntimeError(_chosen_model_problem(testbench_model, e, "testbench model")) from e
            if live_ok:
                # A live run has already produced user-specific artifacts (spec,
                # RTL, testbench). Swapping to the curated offline provider here
                # would silently replace the user's design with an unrelated
                # counter/ALU. Fail honestly instead; the UI shows a real error.
                raise MidRunUnavailable(
                    f"LLM became unavailable mid-run at '{fn_name}': {str(e)[:300]}", _short_reason(e)
                ) from e
            if explicit_model:
                raise RuntimeError(_chosen_model_problem(model, e)) from e
            logger.warning("LLM upstream failed at %s, falling back to offline: %s",
                           fn_name, str(e)[:500])
            use_offline = True
            # Set fallback notice for UI
            if fallback_notice is None:
                fallback_notice = (
                    f"LLM provider unavailable ({_short_reason(e)}) — using the built-in offline demo. "
                    "Your request did not match a live-generated design; results "
                    "come from curated examples and are labelled as degraded."
                )
            # Retry with the per-run offline provider.
            return _offline_call(fn_name, args, kwargs)
        live_ok = True
        return out

    try:
        # 1. Intent. A specification the user reviewed and confirmed replaces the model's reading of the prompt. It is
        # user-specific work, so from here on an outage fails honestly instead of swapping in the scripted demo.
        if spec_override is not None:
            spec = spec_override
            live_ok = True
        else:
            try:
                spec: RTLDesignSpec = _call_llm("parse_intent", prompt, model=model, reasoning_effort=reasoning_effort)
            except Exception:
                # If _call_llm already handled fallback, it would have retried; this is non-upstream error
                raise

        # Check for offline fallback disclosure (counter fallback)
        # If we are in offline mode, check _last_exact; if Zen live but prompt unmatched, also check
        provider = offline_provider if use_offline else (
            llm_service.get_provider(model) if llm_service.model_catalog.is_routed_id(model) else llm_service.get_provider())
        if hasattr(provider, "_last_exact") and not provider._last_exact:
            # Only set if not already set by upstream fallback
            if fallback_notice is None:
                fallback_notice = (
                    "Your request did not match a built-in offline design. "
                    "Showing a representative counter design as a demo."
                )

        yield {"stage": "intent", "message": (f"Using the specification you confirmed: module '{spec.module_name}' with {len(spec.ports)} ports."
                                              if spec_override is not None else
                                              f"Identified module '{spec.module_name}' with {len(spec.ports)} ports.") + (" (offline fallback)" if use_offline else ""),
               "rtl_spec": spec.model_dump(), "fallback_notice": fallback_notice}

        # 2. RTL — validate before compiling. A truncated/fenced fragment used to
        # reach the simulator and produce a cryptic "syntax error".
        rtl_code = _call_llm("generate_rtl", spec, target_frequency_mhz, model=model, reasoning_effort=reasoning_effort)
        if not _has_complete_module(rtl_code, spec.module_name):
            logger.warning("RTL generation returned an incomplete module; retrying once")
            rtl_code = _call_llm("generate_rtl", spec, target_frequency_mhz, model=model, reasoning_effort=reasoning_effort)
        if not _has_complete_module(rtl_code, spec.module_name):
            raise RuntimeError(
                f"RTL generation did not return a complete module named "
                f"'{spec.module_name}'. The model response was truncated or malformed."
            )
        yield {"stage": "rtl", "message": "Generated RTL." + (" (offline fallback)" if use_offline else ""), "rtl_code": rtl_code}

        # Lint RTL alone (non-blocking, informational)
        if VerilogLinter is not None:
            try:
                linter = VerilogLinter()
                lint_res = linter.lint(rtl_code)
                if lint_res.get("errors") or lint_res.get("warnings"):
                    payload = _lint_payload(lint_res)
                    yield {
                        "stage": "lint",
                        "target": "rtl",
                        "message": f"Lint RTL: {len(payload['errors'])} error(s), {len(payload['warnings'])} warning(s)",
                        "lint": payload,
                    }
            except Exception:
                pass  # linter must never break the pipeline

        # 3. Testbench — must be a complete, self-checking module that actually
        # instantiates the DUT. A fragment or a check-free TB is not verification.
        def _tb_ok(code: str) -> bool:
            return not _tb_problems(code, spec.module_name)

        tb_code = _call_llm("generate_testbench", rtl_code, spec, model=tb_model, reasoning_effort=reasoning_effort)
        if not _tb_ok(tb_code):
            logger.warning(
                "Generated testbench invalid (complete=%s, checks=%d, instantiates_dut=%s); retrying once",
                _has_complete_module(tb_code, "testbench"),
                _tb_check_count(tb_code),
                _instantiates_dut(tb_code, spec.module_name),
            )
            tb_code = _call_llm("generate_testbench", rtl_code, spec, model=tb_model, reasoning_effort=reasoning_effort)
        if not _has_complete_module(tb_code, "testbench"):
            raise RuntimeError(
                "Testbench generation did not return a complete module named "
                "'testbench'. The model response was truncated or malformed."
            )
        if not _instantiates_dut(tb_code, spec.module_name):
            raise RuntimeError(
                f"Testbench does not instantiate the DUT module '{spec.module_name}'."
            )
        if _tb_check_count(tb_code) == 0:
            raise RuntimeError(
                "Testbench contains no self-checks (no fail_count/$error/assert). "
                "Refusing to report PASS from a testbench that cannot fail."
            )
        yield {"stage": "testbench", "message": "Generated self-checking testbench." + (" (offline fallback)" if use_offline else ""), "testbench_code": tb_code}

        # Lint combined RTL + TB before simulation (non-blocking)
        if VerilogLinter is not None:
            try:
                linter = VerilogLinter()
                lint_res = linter.lint(rtl_code, tb_code)
                if lint_res.get("errors") or lint_res.get("warnings"):
                    payload = _lint_payload(lint_res)
                    yield {
                        "stage": "lint",
                        "target": "tb",
                        "message": f"Lint TB: {len(payload['errors'])} error(s), {len(payload['warnings'])} warning(s)",
                        "lint": payload,
                    }
            except Exception:
                pass

        # 4. Explanation — cosmetic: never let it kill a verified design or
        # trigger a provider-wide fallback.
        try:
            explanation = _call_llm("explain_design", rtl_code, spec,
                                    model=model, reasoning_effort=reasoning_effort)
        except Exception as e:
            logger.warning("explanation failed (non-fatal): %s", str(e)[:300])
            explanation = "Explanation unavailable (LLM error); RTL and testbench are unaffected."
        yield {"stage": "explanation", "message": explanation, "explanation": explanation}

        # 5. Simulate + self-correct
        original_tb = tb_code  # the oracle as first generated, for the end-of-run comparison
        history: list[IterationRecord] = []
        result = simulator.simulate(design_id, rtl_code, tb_code, timeout=timeout_seconds)
        history.append(IterationRecord(iteration=0, status=result.status, fix_summary="initial",
                                       pass_count=result.pass_count, fail_count=result.fail_count,
                                       log_excerpt=result.log_excerpt[-1200:]))
        yield {"stage": "simulate", "iteration": 0, "status": result.status,
               "message": _sim_message(0, result), "result": _light(result)}

        def _norm_hash(code: str) -> str:
            import re as _re
            norm = _re.sub(r"//.*", "", code)
            norm = _re.sub(r"/\*.*?\*/", "", norm, flags=_re.DOTALL)
            norm = _re.sub(r"\s+", "", norm)
            return hashlib.sha256(norm.encode()).hexdigest()

        def _state_hash(rtl: str, tb: str) -> str:
            # Track RTL *and* TB. A fix that repairs only the testbench oracle is
            # a real change and must not be discarded as a no-op.
            return _norm_hash(rtl + "\n//--TESTBENCH--\n" + tb)

        iteration = 0
        repair_stopped_note = None
        tb_rewritten_by_design_model = False     # the separate model's testbench did not compile and was repaired
        seen_states: set[str] = set()
        seen_states.add(_state_hash(rtl_code, tb_code))

        while self_correct and result.status in ("FAIL", "ERROR", "TIMEOUT") and iteration < max_iterations:
            iteration += 1

            # Deterministic compiler-evidenced repairs before asking the model.
            # These are not guessed design changes: Icarus names the illegal
            # declaration/construct, so the repair is mechanical.
            if result.status == "ERROR":
                repaired_rtl, repaired_tb, repairs = _compiler_repairs(
                    rtl_code, tb_code, result.log_excerpt)
                if repairs:
                    # Report the first repair as the diagnosis; note any others.
                    first = repairs[0]
                    extra = ""
                    if len(repairs) > 1:
                        extra = " Also repaired: " + "; ".join(
                            r["summary"] for r in repairs[1:])
                    diagnosis = {
                        "symptom": first["symptom"],
                        "root_cause": first["root_cause"],
                        "fix_location": first["file"],
                        "confidence": "high",
                        "evidence": next(
                            (ln.strip() for ln in (result.log_excerpt or "").splitlines()
                             if "error" in ln.lower()), ""),
                    }
                    fix_summary = first["summary"] + extra
                    rtl_code, tb_code = repaired_rtl, repaired_tb
                    seen_states.add(_state_hash(rtl_code, tb_code))
                    yield {"stage": "fix", "iteration": iteration,
                           "message": fix_summary, "fix_summary": fix_summary,
                           "fix_type": "compiler_repair", "diagnosis": diagnosis,
                           "rtl_code": rtl_code, "testbench_code": tb_code}
                    result = simulator.simulate(design_id, rtl_code, tb_code,
                                                timeout=timeout_seconds)
                    history.append(IterationRecord(
                        iteration=iteration, status=result.status,
                        fix_summary=fix_summary, fix_type="compiler_repair",
                        diagnosis=diagnosis, pass_count=result.pass_count,
                        fail_count=result.fail_count,
                        log_excerpt=result.log_excerpt[-1200:]))
                    yield {"stage": "simulate", "iteration": iteration,
                           "status": result.status,
                           "message": _sim_message(iteration, result),
                           "result": _light(result)}
                    continue

            yield {"stage": "fixing", "iteration": iteration,
                   "message": f"Simulation {result.status}. Diagnosing and patching (attempt {iteration})..."}

            try:
                fix = _call_llm("fix_design", rtl_code, tb_code, result.log_excerpt,
                                model=model, reasoning_effort=reasoning_effort, spec=spec)
            except MidRunUnavailable as e:
                # Review finding: a quota or timeout at the repair call used to throw away the whole run (RTL,
                # testbench, failing result, waveform). Keep the evidence and say why the repair stopped.
                repair_stopped_note = (f"The repair model became unavailable ({e.reason or 'no answer'}), so the loop "
                                       f"stopped after {iteration - 1} repair(s); this is the last simulated result.")
                yield {"stage": "fix", "iteration": iteration, "message": repair_stopped_note,
                       "fix_summary": "model unavailable"}
                break
            diagnosis = fix.get("diagnosis") if isinstance(fix.get("diagnosis"), dict) else None
            new_rtl, new_tb = fix["rtl_code"], fix["testbench_code"]
            guard_note = ""
            # The fixer's output is untrusted too (review finding: a fragment, a renamed
            # module, or a testbench that never instantiates the DUT was simulated and
            # could even turn FAIL into PASS). Same acceptance rules as a first draft.
            if new_rtl != rtl_code and not _has_complete_module(new_rtl, spec.module_name):
                new_rtl = rtl_code
                guard_note += f" RTL change rejected: it is not a complete module named '{spec.module_name}'."
            if new_tb != tb_code:
                tb_issues = _tb_problems(new_tb, spec.module_name)
                if tb_issues:
                    new_tb = tb_code
                    guard_note += " Testbench change rejected: " + "; ".join(tb_issues) + "."
            # Anti-cheat: an LLM "fix" must not make a failing DUT pass by deleting
            # the testbench checks. Only a testbench that did not COMPILE may be rewritten freely;
            # one that ran (even to a runtime ERROR, a $fatal or a TIMEOUT caused by a buggy design)
            # may only keep or strengthen its checks (review: a $fatal oracle was replaced by 1 check).
            compile_failed = result.status == "ERROR" and (result.log_excerpt or "").startswith("Compilation failed")
            # A testbench that ran but printed no readable summary (and no FAIL lines, which would make it a FAIL) has a
            # broken oracle too: it may be repaired, but without losing checks (self-review verification: an independent
            # testbench that printed "passed = N" could no longer be repaired at all).
            no_summary = result.status == "ERROR" and any("No valid summary" in (e.message or "") for e in (result.errors or []))
            oracle_broken = compile_failed or no_summary
            if (not compile_failed and new_tb != tb_code
                    and _tb_check_count(new_tb) < _tb_check_count(tb_code)):
                logger.warning(
                    "Rejecting testbench change at iteration %d: checks dropped %d -> %d",
                    iteration, _tb_check_count(tb_code), _tb_check_count(new_tb))
                new_tb = tb_code
                guard_note += " Testbench change rejected: it removed self-checks."
            if independent_tb and new_tb != tb_code and not oracle_broken:
                new_tb = tb_code
                guard_note += (" Testbench change not applied: a separate model wrote it, so a failing check is reported "
                               "and not rewritten away.")
            elif independent_tb and new_tb != tb_code:
                tb_rewritten_by_design_model = True
            fix_summary = fix["fix_summary"] + guard_note
            new_state = _state_hash(new_rtl, new_tb)
            cur_state = _state_hash(rtl_code, tb_code)

            if new_state == cur_state:
                yield {"stage": "fix", "iteration": iteration,
                       "message": ("The repair reply could not be read, even after one retry; stopping the loop."
                                   if fix.get("parse_failed") else "Model returned no change; stopping the loop.") + guard_note,
                       "fix_summary": "no-op"}
                break

            if new_state in seen_states:
                yield {"stage": "fix", "iteration": iteration,
                       "message": "Oscillation detected (repeated RTL/TB); stopping the loop." + guard_note,
                       "fix_summary": "oscillation"}
                break

            seen_states.add(new_state)
            rtl_code, tb_code = new_rtl, new_tb
            yield {"stage": "fix", "iteration": iteration, "message": fix_summary,
                   "fix_summary": fix_summary, "fix_type": fix.get("fix_type", ""),
                   "diagnosis": diagnosis,
                   "rtl_code": rtl_code, "testbench_code": tb_code}

            if VerilogLinter is not None:
                try:
                    linter = VerilogLinter()
                    lint_res = linter.lint(rtl_code, tb_code)
                    if lint_res.get("errors") or lint_res.get("warnings"):
                        payload = _lint_payload(lint_res)
                        yield {
                            "stage": "lint",
                            "target": "fix",
                            "iteration": iteration,
                            "message": f"Lint fix #{iteration}: {len(payload['errors'])} error(s), {len(payload['warnings'])} warning(s)",
                            "lint": payload,
                        }
                except Exception:
                    pass

            result = simulator.simulate(f"{design_id}", rtl_code, tb_code, timeout=timeout_seconds)
            history.append(IterationRecord(iteration=iteration, status=result.status,
                                           fix_summary=fix_summary,
                                           fix_type=fix.get("fix_type", ""),
                                           diagnosis=diagnosis,
                                           pass_count=result.pass_count, fail_count=result.fail_count,
                                           log_excerpt=result.log_excerpt[-1200:]))
            yield {"stage": "simulate", "iteration": iteration, "status": result.status,
                   "message": _sim_message(iteration, result), "result": _light(result)}

        # 6. Post-processing artifacts
        result.coverage = compute_coverage(result, log=result.log_excerpt or "")
        port_dirs = {p.name: p.direction for p in spec.ports}
        waveform = parse_vcd(result.waveform_file, ports=port_dirs) if result.waveform_file else None
        schematic = build_schematic(spec)

        # 7. Synthesis (yosys) — graceful fallback to port-level schematic
        synthesis: Optional[dict] = None
        if YosysSynthesizer is not None:
            try:
                synth_workdir = Path(simulator.workspace) / design_id / "synth"
                synthesizer = YosysSynthesizer(workspace=str(simulator.workspace))
                synthesis = synthesizer.synthesize(rtl_code, spec.module_name, work_dir=synth_workdir)
                if synthesis.get("available"):
                    if "cell_count" in synthesis:
                        units = synthesis.get("area_units", "relative_proxy")
                        if units == "relative_proxy":
                            area_str = (f"{synthesis.get('area_estimate', '?')} rel. area "
                                        f"(proxy = cells x 5, no liberty — NOT um^2)")
                        else:
                            area_str = f"{synthesis.get('area_estimate', '?')} {units}"
                        msg = f"Synthesis: {synthesis['cell_count']} generic cells, ~{area_str} (yosys, unmapped)"
                    elif synthesis.get("error"):
                        msg = f"Synthesis warning: {str(synthesis['error'])[:120]}"
                    else:
                        msg = "Synthesis completed (yosys available)"
                else:
                    msg = "Synthesis not available (yosys not installed — showing port-level schematic)"
                yield {"stage": "synthesis", "synthesis": synthesis, "message": msg}
            except Exception as e:
                synthesis = {"available": False, "error": str(e)}
                try:
                    yield {"stage": "synthesis", "synthesis": synthesis, "message": "Synthesis fallback (port-level schematic)"}
                except Exception:
                    pass
        else:
            synthesis = {"available": False}
            try:
                yield {"stage": "synthesis", "synthesis": synthesis, "message": "Synthesis not available (yosys not installed — showing port-level schematic)"}
            except Exception:
                pass

        # If the repair loop rewrote the testbench and the run now PASSES, the oracle itself
        # changed. Re-run the ORIGINAL testbench against the final design: if it still
        # fails, say so, because the PASS may come from a relaxed testbench.
        oracle_note = None
        if result.status == "PASS" and tb_code != original_tb:
            try:
                orig = simulator.simulate(design_id[:30] + "_o", rtl_code, original_tb,
                                          timeout=timeout_seconds)
                if orig.status != "PASS":
                    oracle_note = (
                        "The testbench was modified during repair, and the ORIGINAL testbench "
                        f"still reports {orig.status} on the final design "
                        f"({orig.fail_count} failed). Review the testbench change before trusting this PASS.")
            except Exception:  # a failed extra check must not break the run
                logger.exception("original-testbench comparison failed")
        def _second_opinion() -> SecondOpinion:
            """A fresh testbench from the same spec, run against the final design. Never raises: a failed extra check
            must not break a verified run."""
            who = _model_used(tb_model)
            try:
                fresh = _call_llm("generate_testbench", rtl_code, spec, model=tb_model, reasoning_effort=reasoning_effort)
                problems = _tb_problems(fresh, spec.module_name)
                if problems:
                    return SecondOpinion(status="unavailable", model=who, note="the fresh testbench was unusable (" + "; ".join(problems[:2]) + ").")
                r = simulator.simulate(design_id[:30] + "_s", rtl_code, fresh, timeout=timeout_seconds)
                if r.status == "PASS" and r.test_count < MIN_EXECUTED_CHECKS:
                    # A fresh testbench with a handful of checks is not agreement (self-review finding: "Passed: 1" counted).
                    return SecondOpinion(status="unavailable", model=who, pass_count=r.pass_count, test_count=r.test_count,
                                         note=f"the fresh testbench ran only {r.test_count} check(s), too few to count as agreement.")
                if r.status in ("PASS", "FAIL"):
                    return SecondOpinion(status=r.status, pass_count=r.pass_count, fail_count=r.fail_count, test_count=r.test_count, model=who)
                return SecondOpinion(status="unavailable", model=who, note=f"the fresh testbench did not run cleanly ({r.status}).")
            except Exception as e:  # noqa: BLE001
                return SecondOpinion(status="unavailable", model=who, note=_short_reason(e) or "the model did not answer.")

        # Second opinion: a PASS that only came after the testbench was rewritten is the weakest kind of PASS. Ask for a
        # FRESH testbench from the same specification and run the final design against it. Disagreement is the signal.
        second = None
        if result.status == "PASS" and tb_code != original_tb and SECOND_OPINION_ENABLED and not use_offline:
            yield {"stage": "second_opinion", "message": "The testbench changed during repair: asking for a fresh, independent testbench as a second opinion..."}
            second = _second_opinion()
            yield {"stage": "second_opinion", "second_opinion": second.model_dump(), "message": _second_opinion_message(second)}
        # Two separate models disagree: the failure is information about the SPECIFICATION and both readings of it, not
        # necessarily a design bug. Say so, because a bare FAIL does not tell the user which side to doubt.
        disagree_note = None
        if independent_tb and result.status == "FAIL":
            disagree_note = (f"The design (by {_model_used(model)}) and the testbench (by {_model_used(testbench_model)}) were written by different "
                             "models and they disagree. Either the design or the testbench misreads the specification: compare the first failing "
                             "check with the specification before changing either.")
        second_note = None
        if second is not None and second.status == "FAIL":
            second_note = (f"A fresh testbench written from the same specification by {second.model or 'the model'} FAILS on the final design "
                           f"({second.fail_count} of {second.test_count} checks). The first testbench was changed during repair: do not trust this PASS.")
        # Testbench strength: only meaningful for a design whose real run passed. Mutation testing
        # of the design (see mutation.py) asks whether this testbench could have caught a bug.
        strength = None
        if result.status == "PASS" and STRENGTH_ENABLED:
            try:
                strength = run_strength(simulator, design_id, rtl_code, tb_code)
                if strength.status in ("ok", "partial"):
                    yield {"stage": "strength", "strength": strength.model_dump(),
                           "message": (f"Testbench strength: caught {strength.killed} of "
                                       f"{strength.total} injected bugs.")}
            except Exception:  # a failed extra check must not break the run
                logger.exception("strength check failed")
                strength = None
        # Timing: only for a design that passed, and only when the tools exist (otherwise the
        # result simply has no timing section; nothing is estimated or invented).
        timing = None
        if result.status == "PASS" and TIMING_ENABLED and not timing_missing():
            try:
                timing = run_timing(rtl_code, spec.module_name,
                                    simulator.workspace / (design_id[:26] + "_ti"), target_frequency_mhz,
                                    testbench_code=tb_code)
                yield {"stage": "timing", "timing": timing.model_dump(), "message": timing_message(timing)}
            except Exception:  # a failed extra check must not break the run
                logger.exception("timing check failed")
                timing = None
        independent_note = None
        if independent_tb and tb_rewritten_by_design_model:
            independent_note = ("The separate model's testbench did not compile and was repaired by the design model, so the "
                                "final testbench is no longer independent of the design.")
        wide_note = None
        if any((p.width or 1) > 256 for p in spec.ports):
            wide_note = ("A port is wider than 256 bits: the standard check task compares only the lower 256 bits, so "
                         "errors in the upper bits are not caught.")
        warning_text = " ".join(
            n for n in (repair_stopped_note, wide_note, weak_verification_note(spec, result), weak_strength_note(strength), oracle_note,
                        second_note, disagree_note, independent_note) if n
        ) or None
        # A PASS that the run's own evidence contradicts is reported as disputed, not as a plain PASS (review finding:
        # the headline said PASS while the original testbench and a fresh one both failed the final design).
        pass_disputed = None
        if result.status == "PASS" and (oracle_note or second_note):
            pass_disputed = ("A fresh testbench fails the final design." if second_note else
                             "The original testbench still fails the final design.")

        response = RunResponse(
            design_id=design_id,
            rtl_spec=spec,
            rtl_code=rtl_code,
            testbench_code=tb_code,
            explanation=explanation,
            status=result.status,
            result=result,
            iterations=iteration,
            iteration_history=history,
            waveform=waveform,
            schematic=schematic,
            synthesis=synthesis,
            fallback_notice=fallback_notice,
            verification_warning=warning_text,
            strength=strength,
            timing=timing,
            model=("offline demo" if use_offline else _model_used(model)),
            testbench_model=(_model_used(testbench_model) if independent_tb and not use_offline else None),
            independent_testbench=bool(independent_tb and not use_offline and not tb_rewritten_by_design_model),
            pass_disputed=pass_disputed,
            second_opinion=second,
        )
        yield {"stage": "done", "status": result.status,
               "message": _final_message(result, iteration, pass_disputed),
               "fallback_notice": fallback_notice,
               "response": response.model_dump()}
    except Exception as e:
        logger.exception("pipeline failed")
        # Surface the actionable reason (e.g. mid-run LLM outage) instead of a
        # generic 500. Truncate so logs/stack details never leak to the client.
        yield {"stage": "error", "message": _user_facing_error(e)}


_QUOTA_HINTS = ("free usage limit", "free-limit", "freeusagelimit", "rate limit", "ratelimit", "quota", "too many requests",
                "daily free allocation")
_TIMEOUT_HINTS = ("timeout", "timed out")
# Word-boundary patterns: plain substrings misfired on "max_tokens" ("token" -> credentials), on an account id containing
# "404", and missed HTTP 429 / 410 entirely (self-review finding, all reproduced).
_QUOTA_RE = re.compile(r"\b429\b|" + "|".join(re.escape(h) for h in _QUOTA_HINTS))
_REASON_PATTERNS = (
    (_QUOTA_RE, "its usage limit has been reached"),
    (re.compile(r"timeout|timed out"), "it did not answer in time"),
    (re.compile(r"emptycontent|finish_reason=length|no answer text|reasoning only"),
     "it spent its whole answer budget on reasoning and returned no answer"),
    (re.compile(r"opencodenotinstalled|'opencode' command was not found"), "the OpenCode app is not installed on the server"),
    (re.compile(r"\b410\b|\bretired\b|\bdeprecated\b|no longer (?:available|supported)"), "the provider has retired this model"),
    # Seen live on 24 Nov: OpenCode answers HTTP 400 "Model is unavailable" for a retired free model, and
    # "unavailable for free" / "subscription is required" for models listed with a free-looking name.
    (re.compile(r"subscription is required|unavailable for free|paid version|requires? (?:a )?paid"),
     "it needs a paid plan or subscription with its provider"),
    (re.compile(r"model is unavailable|model unavailable"), "the provider is not serving this model right now"),
    (re.compile(r"\b40[13]\b|unauthori[sz]ed|forbidden|permissiondenied|authentication|invalid api key|api key"),
     "the provider did not accept the credentials or the model is not available to this account (for example it "
     "needs a paid plan)"),
    (re.compile(r"\b404\b|not found|unknown model|does not exist"), "the provider does not know this model"),
)


def _reason(low: str) -> str:
    return next((why for rx, why in _REASON_PATTERNS if rx.search(low)), "the provider returned an error")


def _model_used(model: Optional[str]) -> Optional[str]:
    """The model that wrote the design, spelled the way the model menu spells it."""
    if model and not llm_service.is_default_model(model):
        return model
    return llm_service.current_model_id()


SECOND_OPINION_ENABLED = os.getenv("SECOND_OPINION_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off")


def _second_opinion_message(s: SecondOpinion) -> str:
    if s.status == "PASS":
        return f"Second opinion: a fresh testbench agrees ({s.pass_count}/{s.test_count} checks pass)."
    if s.status == "FAIL":
        return f"Second opinion: a fresh testbench DISAGREES ({s.fail_count} of {s.test_count} checks fail)."
    return f"Second opinion unavailable: {s.note}"


def _chosen_model_problem(model: Optional[str], e: Exception, role: str = "model") -> str:
    """Why the model the user picked did not work, and what to do. Short, plain, no provider internals."""
    why = _reason(str(e).lower())
    return f"The {role} you chose ({model}) could not be used: {why}. Pick another model from the Model menu."


def _user_facing_error(e: Exception) -> str:
    """A short, actionable message for the error event.

    The raw text of an upstream failure can be long (a JSON blob from the provider) and was
    replaced by a bare "Internal server error" whenever it exceeded 300 characters, which hid the
    one thing the user needs to know: the free quota is used up, or the model was too slow.
    """
    raw = str(e).strip()
    low = raw.lower()
    if _is_upstream_error(e) or "llm became unavailable" in low:
        if _QUOTA_RE.search(low):
            return ("The AI provider's free usage limit has been reached. It resets daily: try again after "
                    "the reset, or switch to the offline demo.")
        if any(h in low for h in _TIMEOUT_HINTS):
            return ("The AI model did not answer in time. Free models can take minutes per step: try again, "
                    "pick another model from the Model menu, or raise LLM_TIMEOUT_SECONDS.")
        return "The AI provider became unavailable mid-run. Please try again in a moment."
    if isinstance(e, OSError):
        # e.g. "[Errno 28] No space left on device: '/Users/.../workspace/abc/design.sv'" (self-review finding): say what
        # happened without the server's file paths.
        return f"The server could not read or write its working files ({e.strerror or 'storage error'})."
    if not raw or len(raw) > 300:
        return "Internal server error"   # never leak stack text or long internal detail to the client
    # No absolute server paths in short messages either, but a model id such as nim/poolside/x or @cf/openai/y is kept:
    # a path starts at the beginning, after a space or after a quote, never inside a word.
    return re.sub(r"(?<![\w@.:-])(?:/[^\s'\"():,]+){2,}", "<path>", raw)


def run_pipeline(prompt: str, design_id: str, simulator: IcarusSimulator, **kwargs) -> RunResponse:
    """Consume the event stream and return the final RunResponse."""
    final = None
    for event in pipeline_events(prompt, design_id, simulator, **kwargs):
        if event["stage"] == "done":
            final = event["response"]
        elif event["stage"] == "error":
            raise RuntimeError(event.get("message", "Internal server error"))
    if final is None:
        raise RuntimeError("Pipeline did not produce a final response")
    return RunResponse(**final)


def _light(result) -> dict:
    """Result for streamed progress events: counters and groups, but not the check rows.

    Up to ~1000 check rows per simulation would be re-sent on every iteration; the full
    rows travel once, in the final ``done`` event.
    """
    d = result.model_dump()
    d["checks"] = []
    return d


def _sim_message(iteration: int, result) -> str:
    if result.status == "PASS":
        return f"Simulation passed: {result.pass_count}/{result.test_count} tests."
    if result.status == "FAIL":
        return f"Simulation failed: {result.fail_count} of {result.test_count} tests failed."
    ran = sum(g.total for g in (result.check_groups or []))   # checks printed before a stop are progress, not a verdict
    after = f" after {ran} checks (stopped before the testbench finished)" if ran else ""
    if result.status == "TIMEOUT":
        return f"Simulation timed out{after}."
    return f"Simulation error (compile or runtime){after}."


def _final_message(result, iterations: int, disputed: str | None = None) -> str:
    if result.status == "PASS" and disputed:
        return f"PASS, but disputed: {disputed} Do not trust this PASS without reviewing the testbench change."
    if result.status == "PASS":
        if iterations:
            return f"Design passes after {iterations} self-correction iteration(s)."
        return "Design passes on the first attempt."
    return f"Could not reach a passing state after {iterations} iteration(s) ({result.status})."
