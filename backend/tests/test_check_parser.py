"""Per-check rows: what the UI shows about WHICH test cases ran and which passed.

Rows are display data only. The verdict comes from the validated summary
(test_verdict_integrity.py); these tests also prove the rows cannot change it.
"""

import shutil
import sys
from pathlib import Path

import pytest

import offline_designs as od
from checks import MAX_FAIL_ROWS, MAX_ROWS, parse_checks
from simulator import IcarusSimulator, _decide_verdict, _excerpt

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")


def _chk(status, cat="directed", name="n", t=1000, exp="4", act="4", detail=""):
    return f"CHK|{status}|{cat}|{name}|{t}|{exp}|{act}|{detail}\n"


def test_structured_rows_and_exact_group_counters():
    log = (_chk("PASS", "reset", "a") + _chk("PASS", "directed", "b") + _chk("FAIL", "directed", "c", exp="4", act="8")
           + "Passed: 2\nFailed: 1\n")
    r = parse_checks(log, 2, 1)
    assert r["checks_source"] == "structured" and r["checks_consistent"] is True
    assert [c.status for c in r["checks"]] == ["PASS", "PASS", "FAIL"]
    groups = {g.category: (g.passed, g.failed) for g in r["check_groups"]}
    assert groups == {"reset": (1, 0), "directed": (1, 1)}
    fail = r["checks"][2]
    assert (fail.expected, fail.actual, fail.t, fail.idx) == ("4", "8", 1000, 3)


def test_x_and_z_digits_are_kept_verbatim():
    r = parse_checks(_chk("FAIL", exp="4", act="1X0") + "Passed: 0\nFailed: 1\n", 0, 1)
    assert r["checks"][0].actual == "1X0"


def test_malformed_and_forged_lines_are_ignored_not_trusted():
    log = ("CHK|MAYBE|x|y|1|1|1|\n"          # unknown status
           "CHK|PASS|x\n"                     # too few fields
           "not a check line CHK|PASS|x|y|1|1|1|\n"
           + _chk("PASS") + "Passed: 1\nFailed: 0\n")
    r = parse_checks(log, 1, 0)
    assert len(r["checks"]) == 1


def test_inconsistent_counts_are_flagged_not_hidden():
    r = parse_checks(_chk("PASS") * 5 + "Passed: 3\nFailed: 0\n", 3, 0)
    assert r["checks_consistent"] is False and r["checks_total_logged"] == 5


def test_rows_are_capped_but_every_failure_is_kept_and_counters_stay_exact():
    fails = 50
    log = "".join(_chk("PASS", "random", f"p{i}") for i in range(3000))
    log += "".join(_chk("FAIL", "random", f"f{i}") for i in range(fails))
    r = parse_checks(log, 3000, fails)
    assert len(r["checks"]) == MAX_ROWS and r["checks_truncated"] is True
    assert sum(c.status == "FAIL" for c in r["checks"]) == fails
    g = r["check_groups"][0]
    assert (g.total, g.passed, g.failed) == (3050, 3000, 50)
    only_fails = parse_checks("".join(_chk("FAIL") for _ in range(500)), 0, 500)
    assert sum(c.status == "FAIL" for c in only_fails["checks"]) == MAX_FAIL_ROWS


def test_category_names_are_normalised_and_limited():
    log = _chk("PASS", "Rand") + _chk("PASS", "Edge Case!") + _chk("PASS", "enable")
    cats = [c.category for c in parse_checks(log, 3, 0)["checks"]]
    assert cats == ["random", "edge_case", "hold"]
    many = "".join(_chk("PASS", f"cat{i}") for i in range(30))
    assert len({c.category for c in parse_checks(many, 30, 0)["checks"]}) <= 13  # 12 + "other"


def test_legacy_testbench_without_chk_lines_still_shows_failures():
    log = "FAIL: op=3 a=1 b=2 result=3 exp=4\nPassed: 9\nFailed: 1\n"
    r = parse_checks(log, 9, 1)
    assert r["checks_source"] == "legacy"
    row = r["checks"][0]
    assert (row.status, row.category, row.expected, row.actual) == ("FAIL", "unclassified", "4", "3")
    assert r["check_groups"][0].total == 10


def test_no_information_at_all():
    assert parse_checks("hello\n", 0, 0) == {"checks_source": "none"}


def test_chk_lines_can_never_change_the_verdict():
    """A testbench (or a forged line) cannot turn a failing run into a pass via CHK lines."""
    log = _chk("PASS") * 100 + "Passed: 3\nFailed: 2\n"
    assert _decide_verdict(log)[0] == "FAIL"
    assert _decide_verdict(_chk("FAIL") + "Passed: 4\nFailed: 0\n")[0] == "PASS"  # rows are display data


def test_excerpt_drops_passing_check_lines_but_keeps_failures():
    log = _chk("PASS", name="ok") * 400 + _chk("FAIL", name="the_bad_one") + "FAIL: the_bad_one expected=4 got=8\n"
    out = _excerpt(log)
    assert "the_bad_one" in out and "CHK|PASS" not in out


@needs_iverilog
@pytest.mark.parametrize("key", ["counter", "alu", "alu8", "adder", "mux"])
def test_every_curated_testbench_logs_every_check_consistently(key, tmp_path):
    d = od.get_design(key)
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("k" + key, d["rtl"], d["tb"], timeout=60)
    assert res.status == "PASS"
    assert res.checks_source == "structured" and res.checks_consistent
    assert sum(g.total for g in res.check_groups) == res.test_count == res.checks_total_logged
    assert all(g.failed == 0 for g in res.check_groups)
    assert len(res.checks) == min(res.test_count, MAX_ROWS)


@needs_iverilog
@pytest.mark.parametrize("key", ["counter", "alu", "alu8", "adder", "mux"])
def test_reported_categories_and_names_appear_verbatim_in_the_testbench_source(key, tmp_path):
    """Guards the silent left-truncation of over-long strings held in narrow regs."""
    import re
    d = od.get_design(key)
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("v" + key, d["rtl"], d["tb"], timeout=60)
    declared = set(re.findall(r'(?:chk|run_vec)\s*\(\s*"([^"]+)"', d["tb"]))
    assert declared, "testbench declares no categories"
    assert {g.category for g in res.check_groups} <= declared, (
        {g.category for g in res.check_groups} - declared)


@needs_iverilog
def test_failing_run_reports_the_failed_checks_with_expected_actual_and_time(tmp_path):
    d = od.get_design("counter")
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("kbug", d["rtl_buggy"], d["tb"], timeout=60)
    assert res.status == "FAIL"
    fails = [c for c in res.checks if c.status == "FAIL"]
    assert len(fails) == res.fail_count > 0
    assert all(c.expected is not None and c.actual is not None and c.t is not None for c in fails)
    assert {g.category for g in res.check_groups} >= {"directed", "hold", "reset"}
    # a failing check's time is a real simulation time that appears in the waveform file
    vcd = Path(res.waveform_file).read_text()
    assert any(f"#{c.t}\n" in vcd for c in fails)


@needs_iverilog
def test_long_category_and_test_names_are_not_truncated_by_the_chk_task(tmp_path):
    """A Verilog string held in a too-narrow reg silently keeps only its RIGHTMOST characters, which
    once turned `undefined_opcode` into `fined_opcode`. Labels up to the documented limits must survive."""
    cat = "x" * 4 + "_boundary_cases_ok"          # 22 chars, over the old 12 limit
    name = "a_deliberately_long_test_name_that_is_" + "0123456789"   # 48 chars, over the old 40 limit
    tb = (
        "module testbench;\n    integer pass_count = 0, fail_count = 0;\n" + od.CHK_TASK +
        f'    initial begin\n        chk("{cat}", "{name}", 4, 4);\n'
        '        $display("Passed: %0d", pass_count);\n        $display("Failed: %0d", fail_count);\n'
        "        $finish;\n    end\nendmodule\n"
    )
    res = IcarusSimulator(workspace=str(tmp_path)).simulate("klong", "module dut; endmodule\n", tb, timeout=60)
    assert res.status == "PASS", res.log_excerpt
    assert [(c.category, c.name) for c in res.checks] == [(cat, name)]


def test_mutation_sweep_kills_every_mutant_including_those_found_by_the_review():
    if shutil.which("iverilog") is None:
        pytest.skip("iverilog not installed")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    import mutation_sweep
    rows = mutation_sweep.run_sweep()
    survivors = [(r[0], r[1]) for r in rows if not r[2]]
    assert not survivors, f"testbench blind spots: {survivors}"
    assert len(rows) >= 27


@needs_iverilog
def test_rerun_returns_the_matching_waveform_not_the_old_one(monkeypatch):
    """Re-running edited code must refresh the waveform together with the verdict."""
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "_check_rate_limit", lambda ip: None)
    d = od.get_design("counter")
    client = TestClient(main.app)
    good = client.post("/api/simulation/run", json={"design_id": "rw1", "rtl_code": d["rtl"], "testbench_code": d["tb"]}).json()
    bad = client.post("/api/simulation/run", json={"design_id": "rw2", "rtl_code": d["rtl_buggy"], "testbench_code": d["tb"]}).json()
    assert good["status"] == "PASS" and bad["status"] == "FAIL"
    assert good["waveform"] and bad["waveform"]
    names = {s["name"]: s["role"] for s in good["waveform"]["signals"]}
    assert names.get("clk") == "clock" and names.get("count") == "out" and names.get("enable") == "in"
    assert good["check_groups"] and bad["checks"]
