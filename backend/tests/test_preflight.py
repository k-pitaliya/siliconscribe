"""Preflight helpers: version parsing, a closed port is not 'healthy', and the OFFLINE_MODE handling."""
import importlib.util
import os
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("preflight", Path(__file__).resolve().parents[1] / "tools" / "preflight.py")
pf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pf)


def test_version_parsing():
    assert pf.parse_version("Icarus Verilog version 12.0 (stable) ()") == (12, 0)
    assert pf.parse_version("Icarus Verilog version 11.0 (stable)") == (11, 0)
    assert pf.parse_version("version 13") == (13, 0)
    assert pf.parse_version("no digits here") is None and pf.parse_version("") is None


def test_a_closed_port_is_not_reported_healthy():
    assert pf.http_ok("http://127.0.0.1:9/health", timeout=0.5) is False


def test_run_reports_missing_tools_and_timeouts_without_raising():
    assert pf.run(["definitely-not-a-real-binary-xyz"]) == (127, "not found")
    rc, out = pf.run(["sleep", "5"], timeout=1)
    assert rc == 124 and out == "timed out"


def test_offline_check_restores_the_users_offline_setting(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "0")
    pf.RESULTS.clear()
    pf.check_offline_pipeline()
    assert os.environ["OFFLINE_MODE"] == "0"                     # not clobbered
    assert pf.RESULTS[-1][1] == "Offline demo pipeline"
    monkeypatch.delenv("OFFLINE_MODE")
    pf.check_offline_pipeline()
    assert "OFFLINE_MODE" not in os.environ                       # and not left set when it was unset


def test_a_failing_check_gives_a_nonzero_exit_status(monkeypatch):
    pf.RESULTS.clear()
    monkeypatch.setattr(pf, "check_simulator", lambda: pf.record("FAIL", "x", "broken"))
    for name in ("check_yosys", "check_servers", "check_storage"):
        monkeypatch.setattr(pf, name, lambda: None)
    monkeypatch.setattr(pf, "check_offline_pipeline", lambda: True)
    monkeypatch.setattr(pf, "check_live_config", lambda: False)
    monkeypatch.setattr(pf, "check_evidence", lambda: True)
    monkeypatch.setattr("sys.argv", ["preflight.py"])
    assert pf.main() == 1
