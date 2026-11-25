"""When the testbench model cannot write a testbench, the run asks the fallback model instead of ending (25 Nov finding:
free models write RTL reliably but time out, cut off or return unusable testbenches). Never silent, never a model
replacing itself, and an honest error when the fallback fails too."""
import shutil
from types import SimpleNamespace

import pytest

import llm_service
import offline_designs as od
import orchestrator
from simulator import IcarusSimulator

pytestmark = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")

GOOD_TB = od.get_design("counter")["tb"]
GOOD_RTL = od.get_design("counter")["rtl"]
FALLBACK = "opencode/reliable-tb"
EMPTY_TB = "module testbench;\nendmodule\n"             # a module, but it checks nothing


@pytest.fixture()
def live(monkeypatch):
    """A scripted live model: `tb` maps a model id to what generate_testbench does for it (an exception to raise, or
    the testbench text to return). Every call is recorded."""
    off = llm_service.OfflineProvider()
    s = SimpleNamespace(calls=[], tb={})

    def parse_intent(prompt, model=None, **k):
        return off.parse_intent(prompt)

    def generate_testbench(rtl, spec, model=None, **k):
        s.calls.append(model)
        out = s.tb.get(model, GOOD_TB)
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(llm_service, "parse_intent", parse_intent)
    monkeypatch.setattr(llm_service, "generate_rtl", lambda spec, freq=None, model=None, **k: GOOD_RTL)
    monkeypatch.setattr(llm_service, "generate_testbench", generate_testbench)
    monkeypatch.setattr(llm_service, "explain_design", lambda rtl, spec, model=None, **k: "x")
    monkeypatch.setattr(llm_service, "get_provider", lambda model=None: SimpleNamespace(name="standin"))
    monkeypatch.setattr(llm_service, "current_model_id", lambda: "opencode/default-m")
    monkeypatch.setattr(llm_service, "is_default_model", lambda m: not m or m == "opencode/default-m")
    monkeypatch.setenv("TESTBENCH_FALLBACK_MODEL", FALLBACK)
    return s


def run(tmp_path, **kw):
    return list(orchestrator.pipeline_events("Design a 4-bit counter", "fb1", IcarusSimulator(workspace=str(tmp_path)), **kw))


def final(events):
    return events[-1]


TIMEOUT = llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: opencode model=opencode/slow after 600s")
CUT_OFF = RuntimeError("Model 'x' output was truncated (finish_reason=length, max_tokens=8192, reasoning_tokens=None).")


@pytest.mark.parametrize("failure,reason", [
    (TIMEOUT, "it did not answer in time"),
    (CUT_OFF, "answer budget"),
    (EMPTY_TB, "it returned an unusable testbench twice"),
])
def test_a_failed_testbench_model_is_replaced_by_the_fallback_and_the_run_says_so(live, tmp_path, failure, reason):
    live.tb["opencode/slow"] = failure
    events = run(tmp_path, model="opencode/slow")
    r = final(events)
    assert r["stage"] == "done" and r["response"]["result"]["status"] == "PASS"
    note = next(e["message"] for e in events if e["stage"] == "testbench" and "instead" in e.get("message", ""))
    assert "opencode/slow" in note and FALLBACK in note and reason in note
    assert live.calls[-1] == FALLBACK and "opencode/slow" in live.calls
    # recorded as an independent testbench by the fallback model, not as the design model's own
    assert r["response"]["testbench_model"] == FALLBACK and r["response"]["independent_testbench"] is True
    assert r["response"]["testbench_code"] == GOOD_TB


def test_the_fallback_is_not_used_when_the_testbench_model_works(live, tmp_path):
    r = final(run(tmp_path, model="opencode/fine"))
    assert r["stage"] == "done" and live.calls == ["opencode/fine"]
    assert r["response"]["independent_testbench"] is False


def test_a_separate_testbench_model_that_fails_also_falls_back(live, tmp_path):
    live.tb["nim/tb-writer"] = TIMEOUT
    events = run(tmp_path, model="opencode/fine", testbench_model="nim/tb-writer")
    r = final(events)
    assert r["stage"] == "done" and live.calls == ["nim/tb-writer", FALLBACK]
    assert r["response"]["testbench_model"] == FALLBACK
    note = next(e["message"] for e in events if e["stage"] == "testbench" and "instead" in e.get("message", ""))
    assert "nim/tb-writer" in note and "it did not answer in time" in note      # the real reason, not a generic one


def test_the_fallback_never_replaces_a_model_with_itself(live, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTBENCH_FALLBACK_MODEL", "opencode/slow")          # the failing model IS the fallback
    live.tb["opencode/slow"] = TIMEOUT
    r = final(run(tmp_path, model="opencode/slow"))
    assert r["stage"] == "error" and live.calls == ["opencode/slow"]         # the same honest error as before
    monkeypatch.setenv("TESTBENCH_FALLBACK_MODEL", "slow")                   # the same model, spelled without the prefix
    live.calls.clear()
    assert final(run(tmp_path, model="opencode/slow"))["stage"] == "error" and live.calls == ["opencode/slow"]


def test_with_the_fallback_switched_off_a_failure_ends_the_run_as_before(live, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTBENCH_FALLBACK_MODEL", "")
    live.tb["opencode/slow"] = TIMEOUT
    r = final(run(tmp_path, model="opencode/slow"))
    assert r["stage"] == "error" and "did not answer in time" in r["message"] and live.calls == ["opencode/slow"]


def test_when_the_fallback_fails_too_the_run_ends_with_an_honest_error(live, tmp_path):
    live.tb["opencode/slow"] = TIMEOUT
    live.tb[FALLBACK] = TIMEOUT
    events = run(tmp_path, model="opencode/slow")
    assert final(events)["stage"] == "error" and live.calls == ["opencode/slow", FALLBACK]
    assert not any(e["stage"] == "done" for e in events)
    msg = final(events)["message"]                      # both models and both reasons, and no "you chose" for the fallback
    assert "opencode/slow" in msg and FALLBACK in msg and "failed too" in msg and "you chose" not in msg


def test_an_unusable_fallback_testbench_is_refused_not_passed(live, tmp_path):
    live.tb["opencode/slow"] = TIMEOUT
    live.tb[FALLBACK] = EMPTY_TB
    events = run(tmp_path, model="opencode/slow")
    assert final(events)["stage"] == "error" and "Testbench" in final(events)["message"]
    assert not any(e["stage"] == "done" for e in events)          # an empty testbench can never become a PASS


def test_the_fallback_is_never_the_scripted_offline_demo_under_a_models_name(live, tmp_path, monkeypatch):
    """Review finding: with an offline default provider the 'fallback' would be a scripted testbench labelled as a model."""
    monkeypatch.setattr(llm_service, "uses_offline", lambda m=None: m == FALLBACK)
    live.tb["nim/slow"] = TIMEOUT
    events = run(tmp_path, model="nim/slow")
    assert final(events)["stage"] == "error" and live.calls == ["nim/slow"]
    assert not any("instead" in e.get("message", "") for e in events)


def test_a_testbench_model_that_is_not_set_up_still_ends_the_run_with_its_own_message(live, tmp_path):
    live.tb["nim/tb-writer"] = llm_service.ModelNotAvailable("NVIDIA NIM is not set up. Start the backend with NVIDIA_NIM_API_KEY set.")
    events = run(tmp_path, model="opencode/fine", testbench_model="nim/tb-writer")
    assert final(events)["stage"] == "error" and "NVIDIA NIM is not set up" in final(events)["message"]
    assert live.calls == ["nim/tb-writer"]


def test_a_fallback_that_is_the_design_model_is_not_called_independent(live, tmp_path, monkeypatch):
    monkeypatch.setenv("TESTBENCH_FALLBACK_MODEL", "opencode/fine")
    live.tb["nim/tb-writer"] = TIMEOUT
    r = final(run(tmp_path, model="opencode/fine", testbench_model="nim/tb-writer"))
    assert r["stage"] == "done" and live.calls == ["nim/tb-writer", "opencode/fine"]
    assert r["response"]["independent_testbench"] is False and r["response"]["testbench_model"] is None
