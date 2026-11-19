"""When the AI provider fails, the user sees the reason (quota, slowness), not 'Internal server error'."""
import pytest

import llm_service
from orchestrator import _user_facing_error, pipeline_events

QUOTA_JSON = ('LLM became unavailable mid-run at \'generate_testbench\': LLM_UPSTREAM:OpenCodeError: '
              'model=opencode/deepseek-v4.1-flash-free {"type": "provider.free-limit", "message": "Free usage limit '
              'reached. Connect a provider or subscribe to OpenCode Go to keep going"} ' + "x" * 300)


def test_a_long_quota_error_is_explained_not_hidden():
    assert len(QUOTA_JSON) > 300                                   # the old code replaced anything this long
    msg = _user_facing_error(RuntimeError(QUOTA_JSON))
    assert "free usage limit" in msg and "reset" in msg
    assert "provider.free-limit" not in msg and "OpenCodeError" not in msg    # no raw provider text to the client


@pytest.mark.parametrize("raw,needle", [
    ("LLM_UPSTREAM:Timeout: opencode model=opencode/x after 240s", "did not answer in time"),
    ("LLM became unavailable mid-run at 'fix_design': Timeout", "did not answer in time"),
    ("LLM_UPSTREAM:APIConnectionError: boom", "became unavailable"),
])
def test_other_provider_failures_get_short_actionable_messages(raw, needle):
    assert needle in _user_facing_error(llm_service.LLMUpstreamError(raw))


def test_ordinary_errors_keep_their_message_and_internal_detail_stays_hidden():
    assert _user_facing_error(ValueError("module name is invalid")) == "module name is invalid"
    assert _user_facing_error(ValueError("x" * 400)) == "Internal server error"
    assert _user_facing_error(ValueError("")) == "Internal server error"


def test_a_programming_error_mentioning_quota_is_not_mistaken_for_a_provider_outage():
    # only genuine upstream failures get the provider wording
    assert _user_facing_error(KeyError("quota")) == "'quota'"


def test_the_pipeline_emits_the_friendly_message_as_its_error_event(monkeypatch, tmp_path):
    """A live run whose first stages succeed and whose testbench call then hits the quota limit."""
    from simulator import IcarusSimulator
    offline = llm_service._offline_provider
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    # the pipeline treats an OfflineProvider as "scripted demo"; present a live-looking provider instead
    from types import SimpleNamespace
    monkeypatch.setattr(llm_service, "get_provider", lambda: SimpleNamespace(name="live", model="m"))
    monkeypatch.setattr(llm_service, "parse_intent", lambda prompt, model=None, reasoning_effort=None: offline.parse_intent(prompt))
    monkeypatch.setattr(llm_service, "generate_rtl", lambda spec, *a, **k: offline.generate_rtl(spec, None))

    def quota(*_a, **_k):
        raise llm_service.LLMUpstreamError(
            'LLM_UPSTREAM:OpenCodeError: model=x {"type": "provider.free-limit", "message": "Free usage limit reached ' + "x" * 300 + '"}')

    monkeypatch.setattr(llm_service, "generate_testbench", quota)
    events = list(pipeline_events("Design a 4-bit synchronous up-counter", "errtest", IcarusSimulator(workspace=str(tmp_path))))
    assert events[-1]["stage"] == "error"
    assert "free usage limit" in events[-1]["message"] and "Internal server error" not in events[-1]["message"]


# ------------------------------------------------------------------ self-review findings (19 Nov 2026)
import pytest  # noqa: E402

from orchestrator import _chosen_model_problem  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("LLM_UPSTREAM:EmptyContent: model=x max_tokens=8192 reasoning only", "spent its whole answer budget on reasoning"),
    ("Error code: 429 - Too Many Requests", "usage limit"),
    ("daily free allocation exceeded for @cf/meta/llama", "usage limit"),
    ("Error code: 410 - model retired", "retired this model"),
    ("Error code: 500 at https://api.cloudflare.com/client/v4/accounts/ab404cd/ai", "returned an error"),
    ("RuntimeError: LLM_UPSTREAM:OpenCodeNotInstalled: the 'opencode' command was not found", "not installed"),
    ("Error code: 401 - invalid api key", "did not accept the credentials"),
    ("Error code: 404 - unknown model", "does not know this model"),
])
def test_the_reason_given_for_a_failed_chosen_model_is_the_real_one(raw, expected):
    assert expected in _chosen_model_problem("m", RuntimeError(raw))


def test_a_storage_error_does_not_show_server_paths():
    from orchestrator import _user_facing_error
    e = OSError(28, "No space left on device", "/Users/someone/proj/backend/workspace/abc/design.sv")
    msg = _user_facing_error(e)
    assert "No space left on device" in msg and "/Users" not in msg and "workspace" not in msg
    assert "/Users" not in _user_facing_error(RuntimeError("failed to open /Users/x/backend/workspace/y.sv"))


def test_model_ids_that_look_like_paths_are_kept_in_messages():
    from orchestrator import _user_facing_error
    for mid in ("@cf/openai/gpt-oss-120b", "nim/poolside/laguna-xs-2.1", "opencode/deepseek-v4.1-flash-free"):
        assert mid in _user_facing_error(RuntimeError(f"The model you chose ({mid}) could not be used"))


def test_the_fallback_reason_has_no_internal_prefix_or_json():
    from orchestrator import _short_reason
    r = _short_reason(RuntimeError('LLM_UPSTREAM:OpenCodeError: model=x {"name":"APIError","data":{"m":1}} daily limit'))
    assert "LLM_UPSTREAM" not in r and "{" not in r and "daily limit" in r
