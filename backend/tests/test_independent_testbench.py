"""A separate model for the testbench, and a second opinion when a repair rewrote the first one. A scripted stand-in
plays the live model so every scenario is deterministic."""
import shutil
from types import SimpleNamespace

import pytest

import llm_service
import offline_designs as od
import orchestrator
from simulator import IcarusSimulator

# Every scenario here runs the real simulator (self-review QA: these failed instead of skipping without Icarus).
pytestmark = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")

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
    assert r["second_opinion"] is not None                                               # it WAS rewritten, so a fresh one is asked for
    assert r["independent_testbench"] is False                                           # the design model repaired it: no longer independent
    assert "no longer independent" in (r["verification_warning"] or "")



# ------------------------------------------------------------------ self-review findings (19 Nov 2026)
FATAL_TB = GOOD_TB.replace("fail_count = fail_count + 1;", 'fail_count = fail_count + 1; $fatal(1, "mismatch");', 1)
assert FATAL_TB != GOOD_TB
TRIVIAL_TB = ("`timescale 1ns/1ps\nmodule testbench;\n  integer pass_count = 0, fail_count = 0;\n  reg clk = 0, rst_n = 0, enable = 0;\n"
              "  wire [3:0] count;\n  counter dut(.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));\n" + od.CHK_TASK +
              '  initial begin #1; chk("directed", "t1", 1, 1);\n'
              '    $display("Passed: %0d", pass_count); $display("Failed: %0d", fail_count); $finish; end\nendmodule\n')


def test_a_testbench_that_stops_on_its_first_failure_cannot_be_rewritten_away(script, monkeypatch, tmp_path):
    """Review: an independent testbench whose check calls $fatal gave ERROR, which unlocked an oracle rewrite; the design
    model swapped in a 1-check testbench, kept the bug, and the result was PASS labelled independent."""
    script.tbs = [FATAL_TB]
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": BAD_RTL, "testbench_code": TRIVIAL_TB, "fix_summary": "simplified the testbench", "fix_type": "testbench_logic",
        "diagnosis": None})
    r = done(run(tmp_path, model="m-design", testbench_model="m-tb", max_iterations=2))
    assert r["status"] == "FAIL" and r["testbench_code"] == FATAL_TB


def test_the_same_model_cannot_replace_a_failing_oracle_with_fewer_checks_after_a_runtime_stop(script, monkeypatch, tmp_path):
    script.tbs = [FATAL_TB]
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": BAD_RTL, "testbench_code": TRIVIAL_TB, "fix_summary": "simplified", "fix_type": "testbench_logic", "diagnosis": None})
    r = done(run(tmp_path, model="m-design", max_iterations=2))
    assert r["status"] != "PASS"


def test_a_quota_error_during_repair_keeps_the_run_and_says_why(script, monkeypatch, tmp_path):
    """Review: the repair call hitting a quota threw away the RTL, testbench, failing result and waveform."""
    def quota(*a, **k):
        raise llm_service.LLMUpstreamError("LLM_UPSTREAM:FreeUsageLimitError: daily free allocation used")
    monkeypatch.setattr(llm_service, "fix_design", quota)
    events = run(tmp_path, model="m-design")
    r = done(events)
    assert r["status"] == "FAIL" and r["rtl_code"] == BAD_RTL and r["result"]["fail_count"] > 0
    assert "repair model became unavailable" in (r["verification_warning"] or "")
    assert not any(e["stage"] == "error" for e in events)


def test_a_chosen_cloudflare_model_is_not_replaced_by_the_demo_when_the_default_provider_is_offline(script, monkeypatch, tmp_path):
    """Review: with the OpenCode app missing, a Cloudflare model the user picked was silently served by the offline demo."""
    monkeypatch.setattr(llm_service, "get_provider", lambda model=None: SimpleNamespace(name="cloudflare") if model
                        else llm_service.OfflineProvider())
    r = done(run(tmp_path, model="@cf/openai/gpt-oss-120b"))
    assert r["model"] != "offline demo" and r["fallback_notice"] is None
    assert ("generate_rtl", "@cf/openai/gpt-oss-120b") in script.calls


def test_a_pass_that_a_fresh_testbench_contradicts_is_reported_as_disputed(script, tmp_path):
    script.tbs = [GOOD_TB, DISAGREEING_TB]
    events = run(tmp_path, model="m-design")
    r = done(events)
    assert r["status"] == "PASS" and r["second_opinion"]["status"] == "FAIL"
    assert r["pass_disputed"] and "fresh testbench" in r["pass_disputed"]
    assert "disputed" in next(e for e in events if e["stage"] == "done")["message"]


def test_an_uncontested_pass_is_not_disputed(script, tmp_path):
    assert done(run(tmp_path, model="m-design"))["pass_disputed"] is None


HANG_TB = GOOD_TB.replace("fail_count = fail_count + 1;", "fail_count = fail_count + 1; forever #1;", 1)   # hangs on a mismatch


def test_a_testbench_that_hangs_on_a_mismatch_cannot_be_replaced_by_a_weaker_one(script, monkeypatch, tmp_path):
    """Only a testbench that did not COMPILE may be rewritten freely. A buggy design that makes the testbench hang (TIMEOUT)
    must not unlock replacing the oracle with a 1-check testbench."""
    script.tbs = [HANG_TB]
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": BAD_RTL, "testbench_code": TRIVIAL_TB, "fix_summary": "simplified", "fix_type": "testbench_logic", "diagnosis": None})
    r = done(run(tmp_path, model="m-design", max_iterations=1, timeout_seconds=2))
    assert r["status"] != "PASS" and r["testbench_code"] == HANG_TB


def test_the_same_model_spelled_with_and_without_its_provider_is_not_independence(script, tmp_path):
    r = done(run(tmp_path, model="opencode/m-design", testbench_model="m-design"))
    assert r["independent_testbench"] is False


NO_SUMMARY_TB = GOOD_TB.replace('"Passed: %0d"', '"passed = %0d"').replace('"Failed: %0d"', '"failed = %0d"')


def test_an_independent_testbench_with_a_summary_typo_can_still_be_repaired_without_losing_checks(script, monkeypatch, tmp_path):
    """Verification finding B5: after the oracle guard was tightened, a separate testbench that printed 'passed = N' (no
    valid summary, no FAIL lines) could not be repaired at all. It may be repaired, and is then no longer independent."""
    assert NO_SUMMARY_TB != GOOD_TB
    script.tbs = [NO_SUMMARY_TB]
    monkeypatch.setattr(llm_service, "generate_rtl", lambda spec, freq=None, model=None, **k: GOOD_RTL)
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": rtl, "testbench_code": GOOD_TB, "fix_summary": "fixed the summary lines", "fix_type": "testbench_logic",
        "diagnosis": None})
    r = done(run(tmp_path, model="m-design", testbench_model="m-tb", max_iterations=2))
    assert r["status"] == "PASS" and r["independent_testbench"] is False


def test_a_summary_typo_does_not_let_a_repair_drop_checks(script, monkeypatch, tmp_path):
    """A correct design + a testbench with no valid summary (ERROR, no failure lines): the repair may fix the summary,
    but replacing the testbench with a 1-check one must be refused."""
    script.tbs = [NO_SUMMARY_TB]
    monkeypatch.setattr(llm_service, "generate_rtl", lambda spec, freq=None, model=None, **k: GOOD_RTL)
    monkeypatch.setattr(llm_service, "fix_design", lambda rtl, tb, log, model=None, **k: {
        "rtl_code": rtl, "testbench_code": TRIVIAL_TB, "fix_summary": "simplified", "fix_type": "testbench_logic", "diagnosis": None})
    events = run(tmp_path, model="m-design", max_iterations=1)
    assert any("removed self-checks" in e.get("message", "") for e in events if e["stage"] == "fix")
    assert done(events)["status"] != "PASS"



def test_a_fresh_testbench_with_too_few_checks_is_not_agreement(script, tmp_path):
    """Verification finding: a second opinion backed by a single check counted as agreement."""
    one_check = TRIVIAL_TB
    script.tbs = [GOOD_TB, one_check]
    r = done(run(tmp_path, model="m-design"))
    assert r["second_opinion"]["status"] == "unavailable" and "too few" in r["second_opinion"]["note"]
