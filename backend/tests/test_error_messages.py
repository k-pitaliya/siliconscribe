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
