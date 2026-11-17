"""OpenCodeAppProvider: drives the user's installed OpenCode app via ``opencode run``.

Every subprocess call is faked here; no OpenCode account, network or tokens are used.
"""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from llm_service import OpenCodeAppProvider


def _events(*texts, extra=()):
    lines = [json.dumps({"type": "step_start"})]
    lines += [json.dumps({"type": "text", "part": {"text": t}}) for t in texts]
    lines += list(extra) + [json.dumps({"type": "step_finish"})]
    return "\n".join(lines) + "\n"


def _fake_run(stdout="", stderr="", code=0, capture=None):
    def run(cmd, **kwargs):
        if capture is not None:
            capture["cmd"], capture["kwargs"] = cmd, kwargs
            capture["cwd_was_empty"] = os.listdir(kwargs["cwd"]) == []
        return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=code)
    return run


def test_builds_a_safe_scripted_command_and_returns_the_text(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(_events("```verilog\nmodule m; endmodule\n```"), capture=seen))
    prov = OpenCodeAppProvider(model="mimo-v2.6-flash-free")
    out = prov._chat("SYSTEM RULES", "write a counter", 0.2)
    assert out == "```verilog\nmodule m; endmodule\n```"
    cmd = seen["cmd"]
    assert cmd[:2] == ["opencode", "run"]
    assert cmd[cmd.index("-m") + 1] == "opencode/mimo-v2.6-flash-free"
    assert cmd[cmd.index("--agent") + 1] == "plan"          # read-only agent by default
    assert "--archived" in cmd and cmd[cmd.index("--format") + 1] == "json"
    assert "SYSTEM RULES" in cmd[-1] and "write a counter" in cmd[-1]
    assert seen["cwd_was_empty"], "must run in a fresh empty directory, never the project"
    assert seen["kwargs"].get("shell") in (None, False)


def test_multiple_text_events_are_joined_in_order(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(_events("module a;", " endmodule")))
    assert OpenCodeAppProvider(model="x")._chat(None, "hi", 0.2) == "module a; endmodule"


def test_per_stage_and_per_request_model_routing(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", _fake_run(_events("ok"), capture=seen))
    monkeypatch.setenv("LLM_MODEL_TESTBENCH", "glm-5.3-flash-free")
    prov = OpenCodeAppProvider(model="mimo-v2.6-flash-free")
    prov._chat(None, "tb", 0.2, stage="testbench")
    assert seen["cmd"][seen["cmd"].index("-m") + 1] == "opencode/glm-5.3-flash-free"
    prov._chat(None, "x", 0.2, model="deepseek-v4.1-flash-free", stage="testbench")
    assert seen["cmd"][seen["cmd"].index("-m") + 1] == "opencode/deepseek-v4.1-flash-free"


def test_error_event_becomes_an_upstream_error(monkeypatch):
    err = json.dumps({"type": "error", "error": {"message": "rate limited"}})
    monkeypatch.setattr(subprocess, "run", _fake_run(_events(extra=[err])))
    with pytest.raises(RuntimeError, match="LLM_UPSTREAM:OpenCodeError"):
        OpenCodeAppProvider(model="x")._chat(None, "hi", 0.2)


def test_nonzero_exit_without_text_is_an_upstream_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="", stderr="boom", code=2))
    with pytest.raises(RuntimeError, match="LLM_UPSTREAM:OpenCodeExit2"):
        OpenCodeAppProvider(model="x")._chat(None, "hi", 0.2)


def test_empty_output_is_an_upstream_error_not_a_silent_blank(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(_events()))
    with pytest.raises(RuntimeError, match="LLM_UPSTREAM:EmptyContent"):
        OpenCodeAppProvider(model="x")._chat(None, "hi", 0.2)


def test_timeout_is_an_upstream_error(monkeypatch):
    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="LLM_UPSTREAM:Timeout"):
        OpenCodeAppProvider(model="x")._chat(None, "hi", 0.2)


def test_opt_in_selection_and_fallback_when_app_missing(monkeypatch):
    import llm_service
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "opencode-app")
    monkeypatch.setenv("LLM_MODEL", "mimo-v2.6-flash-free")
    monkeypatch.setattr(llm_service.shutil, "which", lambda name: "/usr/bin/opencode")
    prov = llm_service._make_provider()
    assert isinstance(prov, OpenCodeAppProvider) and prov.model == "mimo-v2.6-flash-free"
    monkeypatch.setattr(llm_service.shutil, "which", lambda name: None)
    assert isinstance(llm_service._make_provider(), llm_service.OfflineProvider)
