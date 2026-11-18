"""The live-evaluation harness: resumable, outage-safe, honest about fallbacks. No model is called."""
import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("evaluate_live", Path(__file__).resolve().parents[1] / "tools" / "evaluate_live.py")
ev = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ev)


def rec(pid, status="PASS", repairs=0, fallback=False, killed=8, total=10, warning=None, survivors=()):
    return {"id": pid, "category": "combinational", "prompt": "p", "status": status, "repairs": repairs, "seconds": 100.0,
            "module": "m", "checks_passed": 50, "checks_total": 50, "checks_source": "structured", "test_types": [],
            "strength_killed": killed, "strength_total": total, "strength_survivors": list(survivors), "warning": warning,
            "fallback": fallback, "provider": "opencode-app", "model": "deepseek", "testbench_model": None,
            "finished_at": "2026-11-18 10:00:00"}


@pytest.fixture()
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "OUT_DIR", tmp_path)
    monkeypatch.setattr(ev, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(ev, "SUMMARY", tmp_path / "summary.md")
    monkeypatch.setattr(ev, "ARTIFACTS", tmp_path / "artifacts")
    return tmp_path


def _write(out, *recs):
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_prompt_set_is_well_formed():
    ids = [p[0] for p in ev.PROMPTS]
    assert len(ids) == len(set(ids)) and 10 <= len(ids) <= 20
    assert {p[1] for p in ev.PROMPTS} == {"combinational", "sequential", "fsm"}
    assert all(len(p[2]) < 2000 for p in ev.PROMPTS)                     # within the API's prompt limit


def test_summary_separates_first_attempt_repaired_failed_and_excludes_fallbacks(out):
    _write(out, rec("c1"), rec("c2", repairs=2), rec("c3", status="FAIL", repairs=4), rec("c4", fallback=True),
           rec("c5", warning="Weak testbench: it caught only 2 of 10", survivors=["`+` to `-`"]))
    text = ev.summarise()
    assert "Prompts run: **5** (1 fell back to the offline demo and are not counted)" in text
    assert "PASS on the first attempt: **2** of 4" in text
    assert "PASS after self-repair: **1** of 4" in text
    assert "Not PASS: **1** of 4" in text
    assert "offline fallback" in text and "weak testbench" in text and "1 bug(s) missed" in text


def test_summary_with_no_results_is_explicit(out):
    assert ev.summarise() == "No results yet.\n"


def test_last_record_for_an_id_wins_so_a_redo_replaces_the_old_result(out):
    _write(out, rec("c1", status="FAIL"), rec("c1", status="PASS"))
    assert ev.load_done()["c1"]["status"] == "PASS"


def test_main_resumes_skips_finished_prompts_and_stops_cleanly_on_an_outage(out, monkeypatch, capsys):
    import llm_service
    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    _write(out, rec("c1"), rec("c2"))
    calls = []

    def fake_run(pid, category, prompt):
        calls.append(pid)
        if pid == "c5":
            raise RuntimeError("LLM_UPSTREAM:FreeUsageLimitError quota exhausted")
        return rec(pid)

    monkeypatch.setattr(ev, "run_one", fake_run)
    monkeypatch.setattr("sys.argv", ["evaluate_live.py"])
    assert ev.main() == 0
    assert calls[:3] == ["c3", "c4", "c5"] and "c6" not in calls         # c1/c2 skipped; stopped at the outage
    saved = ev.load_done()
    assert {"c1", "c2", "c3", "c4"} <= set(saved) and "c5" not in saved  # the outage is NOT recorded as a failure
    assert "STOP" in capsys.readouterr().out
    assert "Prompts run: **4**" in (out / "summary.md").read_text()


def test_refuses_to_measure_the_offline_demo(out, monkeypatch, capsys):
    import llm_service
    monkeypatch.setattr(llm_service, "is_offline", lambda: True)
    monkeypatch.setattr("sys.argv", ["evaluate_live.py"])
    assert ev.main() == 2
    assert "offline" in capsys.readouterr().out and not (out / "results.jsonl").exists()


def test_only_and_redo_select_the_right_prompts(out, monkeypatch):
    import llm_service
    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    _write(out, rec("c1"))
    calls = []
    monkeypatch.setattr(ev, "run_one", lambda pid, c, p: (calls.append(pid), rec(pid))[1])
    monkeypatch.setattr("sys.argv", ["evaluate_live.py", "--only", "c1,s1", "--redo"])
    ev.main()
    assert calls == ["c1", "s1"]


def test_the_three_warning_kinds_get_distinct_honest_labels(out):
    _write(out,
           rec("c1", repairs=1, warning="The testbench was modified during repair, and the ORIGINAL testbench still reports FAIL"),
           rec("c2", warning="Weak evidence: the testbench executed only 3 checks"),
           rec("c3", warning="Weak testbench: it caught only 2 of 10 injected bugs"))
    text = ev.summarise()
    assert "testbench changed during repair" in text and "few executed checks" in text and "weak testbench" in text
    assert "weak-evidence warning" not in text


def test_backfill_only_updates_records_whose_saved_verdict_reproduces(out, monkeypatch):
    """Older records get toggle/timing from their saved files, but never if the re-run disagrees."""
    import shutil as _sh
    if _sh.which("iverilog") is None:
        pytest.skip("iverilog not installed")
    import offline_designs as od
    d = od.get_design("adder")
    (out / "artifacts").mkdir()
    for pid in ("c1", "c2"):
        (out / "artifacts" / f"{pid}_design.sv").write_text(d["rtl"])
        (out / "artifacts" / f"{pid}_testbench.sv").write_text(d["tb"])
    good = rec("c1")
    good.update(checks_passed=8, checks_total=8, module="full_adder")
    wrong = rec("c2")
    wrong.update(checks_passed=99, checks_total=99)      # does not match what the files produce
    _write(out, good, wrong)
    assert ev.backfill() == 1
    saved = ev.load_done()
    assert saved["c1"]["toggle_percent"] == 80.0 and saved["c1"]["backfilled"] is True
    assert "toggle_percent" not in saved["c2"]
    assert ev.backfill() == 0                                                # idempotent


def test_retime_refreshes_saved_numbers_with_the_current_timing_code_and_hands_over_the_testbench(out, monkeypatch):
    import timing
    from models import TimingReport
    (out / "artifacts").mkdir()
    for pid in ("c1", "c2", "c3"):
        (out / "artifacts" / f"{pid}_design.sv").write_text(f"// design {pid}")
        (out / "artifacts" / f"{pid}_testbench.sv").write_text(f"// tb {pid}")
    seen = []
    def fake(rtl, module, work_dir, target_mhz=None, testbench_code=None):
        seen.append((rtl, testbench_code))
        if "c2" in rtl:      # a design the estimate now refuses
            return TimingReport(available=True, error="The design contains latches; timing of latch-based logic is not estimated.")
        return TimingReport(available=True, slack_ns=9.0, met=True, fmax_mhz=1000.0, area_um2=50.0)
    monkeypatch.setattr(timing, "run_timing", fake)
    old = rec("c1")
    old.update(timing_met=True, timing_fmax_mhz=990.0, area_um2=49.0)     # numbers from the older timing code
    _write(out, old, rec("c2"), rec("c3", status="FAIL"))
    assert ev.retime() == 2
    saved = ev.load_done()
    assert (saved["c1"]["timing_fmax_mhz"], saved["c1"]["area_um2"], saved["c1"]["timing_error"]) == (1000.0, 50.0, None)
    assert saved["c2"]["timing_error"].startswith("The design contains latches") and saved["c2"]["area_um2"] is None
    assert "timing_met" not in saved["c3"]                                  # a design that did not pass is never timed
    assert ("// design c1", "// tb c1") in seen                             # the testbench goes along (parameter overrides)
    assert ev.retime() == 0                                                  # idempotent

