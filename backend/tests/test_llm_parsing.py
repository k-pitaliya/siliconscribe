"""Tests for code extraction and the reasoning-token failure mode.

Regression context (live run, 2026-11-04): a reasoning model spent all 8192
tokens on hidden reasoning, returned empty `content`, and the old fallback
handed its `reasoning` scratchpad to the simulator as a "testbench". The
pipeline then compiled a bare function and reported a syntax error.
"""

from types import SimpleNamespace

import pytest

import llm_service
from llm_service import OpenAIProvider, _strip_code_fence
from orchestrator import _has_complete_module, _tb_check_count


def test_strip_prefers_full_module_over_snippet():
    text = (
        "Here is the testbench:\n"
        "```verilog\nmodule testbench;\n  initial $finish;\nendmodule\n```\n"
        "And a helper fragment:\n"
        "```verilog\nfunction [1:0] f; input a; f = a; endfunction\n```\n"
    )
    out = _strip_code_fence(text)
    assert "module testbench" in out
    assert out.rstrip().endswith("endmodule")
    assert "function [1:0]" not in out


def test_strip_extracts_unfenced_complete_module():
    text = (
        "Sure, here is the code:\n"
        "module testbench;\ninitial $finish;\nendmodule\n"
        "```verilog\nfunction f; endfunction\n```"
    )
    out = _strip_code_fence(text)
    assert out.startswith("module testbench")
    assert out.rstrip().endswith("endmodule")


def test_complete_module_detection_and_check_count():
    good = "module dut(input a); assign b = a; endmodule"
    assert _has_complete_module(good, "dut")
    assert not _has_complete_module(good, "other")
    assert not _has_complete_module("function f; endfunction", "dut")
    assert _tb_check_count("if (a !== b) fail_count++;") == 1


def test_parse_fix_response_sections():
    from llm_service import _parse_fix_response

    text = """<diagnosis>
symptom: 99 of 110 randomized checks failed.
root_cause: expected_valid is a 32-bit integer concatenated with a 3-bit code, so the comparison is 35 bits wide and can never equal the 4-bit DUT output.
fix_location: testbench.sv:118, expected_valid
confidence: high
</diagnosis>
<rtl>
module top;
  assign y = a;
endmodule
</rtl>
<testbench>
module testbench;
  initial $finish;
endmodule
</testbench>
<summary>Narrow expected_valid to one bit.</summary>"""

    parsed = _parse_fix_response(text, "old rtl", "old tb")
    assert parsed["rtl_code"].startswith("module top")
    assert parsed["rtl_code"].rstrip().endswith("endmodule")
    assert parsed["testbench_code"].startswith("module testbench")
    assert parsed["diagnosis"]["confidence"] == "high"
    assert "35 bits" in parsed["diagnosis"]["root_cause"]
    assert parsed["fix_summary"] == "Narrow expected_valid to one bit."


def test_parse_fix_response_salvages_unquoted_verilog_json():
    """Unescaped quotes/newlines in code fields must not kill the fixer."""
    from llm_service import _parse_fix_response

    text = (
        '{"diagnosis": {"symptom": "fail", "root_cause": "width bug", '
        '"fix_location": "testbench.sv", "confidence": "high"}, '
        '"rtl_code": "module top;\n  initial $display("hi");\nendmodule", '
        '"testbench_code": "module testbench;\nendmodule", '
        '"fix_summary": "Fix the width."}'
    )
    parsed = _parse_fix_response(text, "old rtl", "old tb")
    assert "module top" in parsed["rtl_code"]
    assert "$display" in parsed["rtl_code"]
    assert parsed["testbench_code"].startswith("module testbench")
    assert parsed["diagnosis"]["root_cause"] == "width bug"
    assert parsed["fix_summary"] == "Fix the width."


def test_extract_json_accepts_literal_newlines_in_strings():
    from llm_service import _extract_json

    assert _extract_json('{"a": "line1\nline2"}')["a"] == "line1\nline2"


def test_list_models_exposes_only_configured_custom_model(monkeypatch):
    """A custom gateway must not offer curated Zen/NVIDIA IDs the UI can select."""

    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    monkeypatch.setattr(
        llm_service, "current_model",
        lambda: "nvidia/nemotron-3-ultra-550b-a55b:free")
    out = llm_service.list_models()
    assert out["current"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert [m["id"] for m in out["models"]] == [
        "nvidia/nemotron-3-ultra-550b-a55b:free"]


def test_list_models_puts_configured_curated_model_first(monkeypatch):

    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    monkeypatch.setattr(llm_service, "current_model",
                        lambda: "meta/llama-3.3-70b-instruct")
    out = llm_service.list_models()
    assert out["models"][0]["id"] == "meta/llama-3.3-70b-instruct"


def test_reasoning_text_is_never_returned_as_content():
    """Empty content + finish_reason=length must raise, not return reasoning."""
    message = SimpleNamespace(content=None, reasoning_content="function fragment")
    choice = SimpleNamespace(message=message, finish_reason="length")
    response = SimpleNamespace(choices=[choice], usage=None)

    class _Completions:
        def create(self, **kwargs):
            return response

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = _Client()
    provider.model = "reasoning-test"
    provider.mini_model = "reasoning-test"
    provider.name = "test"
    provider.timeout = 10
    provider.max_tokens = 8192

    with pytest.raises(RuntimeError, match="truncated"):
        provider._chat(None, "write a testbench", 0.2)


def _provider_returning(response):
    class _Completions:
        def create(self, **kwargs):
            return response

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = _Client()
    provider.model = "wrapped-test"
    provider.mini_model = "wrapped-test"
    provider.name = "test"
    provider.timeout = 10
    provider.max_tokens = 8192
    return provider


def _wrapped(content, finish="stop"):
    """The Cline API wraps the standard body as {"data": {...}, "success": true}."""
    body = {"choices": [{"message": {"content": content, "reasoning": "thinking"},
                         "finish_reason": finish}],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 7}}}
    return SimpleNamespace(choices=None, usage=None, model_extra={"data": body, "success": True})


def test_wrapped_data_response_is_unwrapped():
    """Gateways that nest the body under "data" must work, not look like an outage."""
    provider = _provider_returning(_wrapped("module m; endmodule"))
    assert provider._chat(None, "hi", 0.2) == "module m; endmodule"


def test_wrapped_response_still_rejects_truncated_output():
    provider = _provider_returning(_wrapped("module m;", finish="length"))
    with pytest.raises(RuntimeError, match="truncated"):
        provider._chat(None, "hi", 0.2)


def test_response_with_no_choices_anywhere_is_still_an_upstream_error():
    provider = _provider_returning(SimpleNamespace(choices=None, usage=None, model_extra={}))
    with pytest.raises(RuntimeError, match="EmptyChoices"):
        provider._chat(None, "hi", 0.2)


_GOOD_SPEC = ('{"module_name": "m", "ports": [{"name": "a", "direction": "input", "width": 1}], '
              '"behavior": "wire a through"}')


def _provider_with_replies(replies):
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.model = provider.mini_model = "t"
    it = iter(replies)
    provider._chat = lambda *a, **k: next(it)
    return provider


def test_parse_intent_retries_once_after_a_non_json_reply():
    prov = _provider_with_replies(["Sure! Here is the design...", _GOOD_SPEC])
    assert prov.parse_intent("make a wire").module_name == "m"


def test_parse_intent_gives_a_clear_error_after_two_bad_replies():
    prov = _provider_with_replies(["", "still not json"])
    with pytest.raises(RuntimeError, match="valid JSON specification after 2 attempts"):
        prov.parse_intent("make a wire")


def test_parse_intent_does_not_retry_when_the_first_reply_is_good():
    prov = _provider_with_replies([_GOOD_SPEC])  # a second call would raise StopIteration
    assert prov.parse_intent("make a wire").module_name == "m"
