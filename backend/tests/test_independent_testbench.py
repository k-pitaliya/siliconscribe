"""A separate model for the testbench, and a second opinion when a repair rewrote the first one. A scripted stand-in
plays the live model so every scenario is deterministic."""
from types import SimpleNamespace

import pytest

import llm_service
import offline_designs as od
import orchestrator
from simulator import IcarusSimulator

DEFAULT = "opencode/default-m"
GOOD_TB = od.get_design("counter")["tb"]
BAD_RTL = od.get_design("counter")["rtl_buggy"]
GOOD_RTL = od.get_design("counter")["rtl"]
ONE_VALUE = 'chk("reset", "released_count_still_zero", 0, count)'
assert ONE_VALUE in GOOD_TB
DISAGREEING_TB = GOOD_TB.replace(ONE_VALUE, 'chk("reset", "released_count_still_zero", 7, count)')


@pytest.fixture()
def script(monkeypatch):
    """Records which model each call was given. Testbenches come from `tbs` in order; the repair returns the good RTL and
    a testbench with only a comment added (a rewrite that changes nothing that matters)."""
    off = llm_service.OfflineProvider()
    s = SimpleNamespace(calls=[], tbs=[GOOD_TB, GOOD_TB], tb_error=None)

    def parse_intent(prompt, model=None, **k):
        s.calls.append(("parse_intent", model))
        return off.parse_intent(prompt)

    def generate_rtl(spec, freq=None, model=None, **k):
        s.calls.append(("generate_rtl", model))
        return BAD_RTL

    def generate_testbench(rtl, spec, model=None, **k):
        s.calls.append(("generate_testbench", model))
        if s.tb_error and len([c for c in s.calls if c[0] == "generate_testbench"]) > 1:
            raise s.tb_error
        return s.tbs.pop(0) if s.tbs else GOOD_TB

    def explain_design(rtl, spec, model=None, **k):
        s.calls.append(("explain_design", model))
        return "x"

    def fix_design(rtl, tb, log, model=None, **k):
        s.calls.append(("fix_design", model))
        return {"rtl_code": GOOD_RTL, "testbench_code": tb + "\n// reviewed\n", "fix_summary": "fixed the increment", "fix_type": "rtl_logic", "diagnosis": None}

    for name, fn in (("parse_intent", parse_intent), ("generate_rtl", generate_rtl), ("generate_testbench", generate_testbench),
                     ("explain_design", explain_design), ("fix_design", fix_design)):
        monkeypatch.setattr(llm_service, name, fn)
    monkeypatch.setattr(llm_service, "get_provider", lambda model=None: SimpleNamespace(name="standin"))
    monkeypatch.setattr(llm_service, "current_model_id", lambda: DEFAULT)
    monkeypatch.setattr(llm_service, "is_default_model", lambda m: not m or m == DEFAULT)
    return s


def run(tmp_path, **kw):
    return list(orchestrator.pipeline_events("Design a buggy 4-bit counter", "ind1", IcarusSimulator(workspace=str(tmp_path)), **kw))


def done(events):
    return next(e for e in events if e["stage"] == "done")["response"]


def test_a_separate_model_writes_only_the_testbench_and_the_result_says_so(script, tmp_path):
    events = run(tmp_path, model="m-design", testbench_model="m-tb")
    by = {}
    for fn, m in script.calls:
        by.setdefault(fn, set()).add(m)
    assert by["generate_testbench"] == {"m-tb"} and by["generate_rtl"] == {"m-design"} and by["fix_design"] == {"m-design"}
    r = done(events)
    assert (r["independent_testbench"], r["testbench_model"], r["model"]) == (True, "m-tb", "m-design")
    assert "testbench by m-tb" in events[0]["message"]


def test_the_same_model_twice_is_not_independence(script, tmp_path):
    r = done(run(tmp_path, model="m-design", testbench_model="m-design"))
    assert r["independent_testbench"] is False and r["testbench_model"] is None
    r = done(run(tmp_path / "b", testbench_model=DEFAULT))                       # naming the default explicitly is the same model too
    assert r["independent_testbench"] is False


def test_with_an_independent_testbench_a_failing_check_is_never_rewritten_away(script, tmp_path):
    events = run(tmp_path, model="m-design", testbench_model="m-tb")
    fix = next(e for e in events if e["stage"] == "fix")
    assert "Testbench change not applied" in fix["message"]
    r = done(events)
    assert r["status"] == "PASS" and r["testbench_code"] == GOOD_TB              # the design was repaired, the oracle was not touched
    assert r["second_opinion"] is None                                           # nothing was rewritten, so nothing to double-check
    assert [c for c in script.calls if c[0] == "generate_testbench"] == [("generate_testbench", "m-tb")]


def test_when_a_repair_rewrote_the_testbench_a_fresh_one_is_asked_for_and_agreement_is_recorded(script, tmp_path):
    events = run(tmp_path)                                                       # one model for everything
    r = done(events)
    so = r["second_opinion"]
    assert r["status"] == "PASS" and so["status"] == "PASS" and so["test_count"] > 0 and so["fail_count"] == 0
    assert [c[0] for c in script.calls].count("generate_testbench") == 2
    assert any(e["stage"] == "second_opinion" and "agrees" in e["message"] for e in events)
    assert "FAILS" not in (r["verification_warning"] or "")


def test_a_fresh_testbench_that_disagrees_puts_a_warning_on_the_pass(script, tmp_path):
    script.tbs = [GOOD_TB, DISAGREEING_TB]
    events = run(tmp_path)
    r = done(events)
    assert r["status"] == "PASS" and r["second_opinion"]["status"] == "FAIL" and r["second_opinion"]["fail_count"] >= 1
    assert "FAILS on the final design" in r["verification_warning"] and "do not trust this PASS" in r["verification_warning"]
    assert any(e["stage"] == "second_opinion" and "DISAGREES" in e["message"] for e in events)


def test_a_second_opinion_that_cannot_be_obtained_is_reported_not_fatal(script, tmp_path):
    script.tb_error = llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: x after 360s")
    r = done(run(tmp_path))
    assert r["status"] == "PASS" and r["second_opinion"]["status"] == "unavailable" and r["second_opinion"]["note"]
    assert "FAILS" not in (r["verification_warning"] or "")                      # no opinion is not a bad opinion


def test_the_second_opinion_can_be_switched_off(script, tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "SECOND_OPINION_ENABLED", False)
    r = done(run(tmp_path))
    assert r["second_opinion"] is None and [c[0] for c in script.calls].count("generate_testbench") == 1


def test_a_failing_testbench_model_is_named_in_plain_words(script, tmp_path, monkeypatch):
    def failing(rtl, spec, model=None, **k):
        raise llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: nim after 360s")
    monkeypatch.setattr(llm_service, "generate_testbench", failing)
    events = run(tmp_path, model="m-design", testbench_model="nim/poolside/laguna-xs-2.1")
    assert events[-1]["stage"] == "error"
    assert "The testbench model you chose (nim/poolside/laguna-xs-2.1) could not be used: it did not answer in time" in events[-1]["message"]


def test_the_request_accepts_a_testbench_model_and_refuses_a_malformed_one():
    from models import RunRequest
    assert RunRequest(prompt="x", testbench_model="nim/poolside/laguna-xs-2.1").testbench_model == "nim/poolside/laguna-xs-2.1"
    with pytest.raises(Exception):
        RunRequest(prompt="x", testbench_model="--help")


def test_when_two_separate_models_disagree_the_failure_says_so(script, tmp_path, monkeypatch):
    # the repair cannot fix the design (it returns the same buggy RTL), so the run ends FAIL against the independent testbench
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": rtl, "testbench_code": tb, "fix_summary": "no change", "fix_type": "rtl_logic", "diagnosis": None})
    r = done(run(tmp_path, model="m-design", testbench_model="m-tb"))
    assert r["status"] == "FAIL" and r["independent_testbench"] is True
    assert "written by different models and they disagree" in r["verification_warning"]
    assert "m-design" in r["verification_warning"] and "m-tb" in r["verification_warning"]


def test_a_failure_with_one_model_for_both_gets_no_disagreement_note(script, tmp_path, monkeypatch):
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": rtl, "testbench_code": tb, "fix_summary": "no change", "fix_type": "rtl_logic", "diagnosis": None})
    r = done(run(tmp_path))
    assert r["status"] == "FAIL" and "disagree" not in (r["verification_warning"] or "")


def test_an_independent_pass_carries_no_disagreement_note(script, tmp_path):
    r = done(run(tmp_path, model="m-design", testbench_model="m-tb"))
    assert r["status"] == "PASS" and "disagree" not in (r["verification_warning"] or "")


def test_a_separate_testbench_that_does_not_even_compile_may_still_be_repaired(script, tmp_path, monkeypatch):
    broken = GOOD_TB.replace(ONE_VALUE, 'chk("reset", "released_count_still_zero", 0, no_such_signal)')
    assert broken != GOOD_TB
    script.tbs = [broken, GOOD_TB]                    # the separate model's first testbench cannot compile
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {   # the repair really fixes the testbench
        "rtl_code": GOOD_RTL, "testbench_code": GOOD_TB, "fix_summary": "fixed the testbench", "fix_type": "testbench_logic", "diagnosis": None})
    events = run(tmp_path, model="m-design", testbench_model="m-tb")
    r = done(events)
    fix = next(e for e in events if e["stage"] == "fix")
    assert "Testbench change not applied" not in fix["message"]                          # a broken oracle is not a disagreement
    assert r["status"] == "PASS" and r["testbench_code"] != broken
    assert r["independent_testbench"] is True and r["second_opinion"] is not None         # it WAS rewritten, so a fresh one is asked for

