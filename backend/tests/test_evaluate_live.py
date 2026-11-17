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
           rec("c5", warning="Weak testbench", survivors=["`+` to `-`"]))
    text = ev.summarise()
    assert "Prompts run: **5** (1 fell back to the offline demo and are not counted)" in text
    assert "PASS on the first attempt: **2** of 4" in text
    assert "PASS after self-repair: **1** of 4" in text
    assert "Not PASS: **1** of 4" in text
    assert "offline fallback" in text and "weak-evidence warning" in text and "1 bug(s) missed" in text


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
