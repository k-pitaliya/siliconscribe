"""ClaudeCodeProvider: drives the user's installed Claude Code CLI (`claude -p`). Every subprocess call is faked."""
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

import llm_service
import model_catalog as mc
from llm_service import ClaudeCodeProvider


def _ok(result="module m; endmodule"):
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": result, "num_turns": 1})


def _fake(stdout, code=0, seen=None):
    def run(cmd, **kw):
        if seen is not None:
            seen.update(cmd=cmd, kw=kw, cwd_was_empty=os.listdir(kw["cwd"]) == [])
        return SimpleNamespace(stdout=stdout, stderr="", returncode=code)
    return run


@pytest.fixture(autouse=True)
def online(monkeypatch):
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_PROVIDER", raising=False)
    llm_service._claude_cache.clear()
    yield
    llm_service._claude_cache.clear()


def test_runs_claude_with_no_tools_no_settings_and_our_prompt(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "run", _fake(_ok(), seen=seen))
    out = ClaudeCodeProvider()._chat("SYSTEM RULES", "write a counter", 0.2, model="claude/sonnet")
    assert out == "module m; endmodule"
    cmd, kw = seen["cmd"], seen["kw"]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--model") + 1] == "sonnet"
    assert cmd[cmd.index("--tools") + 1] == ""                       # no built-in tools at all
    assert "--strict-mcp-config" in cmd and cmd[cmd.index("--setting-sources") + 1] == ""
    assert "--no-session-persistence" in cmd and cmd[cmd.index("--system-prompt") + 1] == "SYSTEM RULES"
    assert kw["input"] == "write a counter" and "write a counter" not in cmd   # the prompt goes on stdin, not argv
    assert seen["cwd_was_empty"] is True
    assert not any(k.endswith(("_API_KEY", "_TOKEN")) for k in kw["env"])     # no secrets reach the CLI


@pytest.mark.parametrize("bad", ["claude/--help", "claude/", "claude/opus;rm", "claude/Opus Max"])
def test_a_model_name_can_never_become_a_flag(monkeypatch, bad):
    monkeypatch.setattr(subprocess, "run", _fake(_ok()))
    with pytest.raises(llm_service.ModelNotAvailable):
        ClaudeCodeProvider()._chat(None, "q", 0.2, model=bad)


@pytest.mark.parametrize("stdout,code,expected", [
    (json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "Claude AI usage limit reached"}), 1, "usage limit"),
    (json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": False, "result": ""}), 0, "error_max_turns"),
    ("not json at all", 1, "ClaudeCodeExit1"),
    (_ok(result="   "), 0, "EmptyContent"),
])
def test_failures_are_upstream_errors_with_the_reason(monkeypatch, stdout, code, expected):
    monkeypatch.setattr(subprocess, "run", _fake(stdout, code))
    with pytest.raises(llm_service.LLMUpstreamError, match=expected):
        ClaudeCodeProvider()._chat(None, "q", 0.2, model="claude/opus")


def test_a_timeout_is_an_upstream_error(monkeypatch):
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 5)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(llm_service.LLMUpstreamError, match="Timeout"):
        ClaudeCodeProvider()._chat(None, "q", 0.2, model="claude/opus")


def test_claude_ids_route_to_claude_code(monkeypatch):
    assert mc.is_routed_id("claude/opus") and mc.claude_alias("claude/haiku") == "haiku"
    assert isinstance(llm_service.get_provider("claude/opus"), ClaudeCodeProvider)
    assert llm_service.get_provider("claude/opus") is llm_service.get_provider("claude/sonnet")   # built once
    monkeypatch.setenv("CLAUDE_CODE_PROVIDER", "0")
    llm_service._claude_cache.clear()
    with pytest.raises(llm_service.ModelNotAvailable, match="switched off"):
        llm_service.get_provider("claude/opus")


def test_offline_mode_still_wins(monkeypatch):
    monkeypatch.setenv("OFFLINE_MODE", "1")
    assert isinstance(llm_service.get_provider("claude/opus"), llm_service.OfflineProvider)


def test_the_menu_offers_claude_only_when_the_cli_is_installed(monkeypatch):
    monkeypatch.setattr(mc.shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None)
    st = mc.claude_status()
    assert st["available"] and [m["id"] for m in st["models"]] == ["claude/opus", "claude/sonnet", "claude/haiku"]
    assert all(m["provider"] == "claude" and mc.is_valid_model_id(m["id"]) for m in st["models"])
    monkeypatch.setattr(mc.shutil, "which", lambda name: None)
    st = mc.claude_status()
    assert not st["available"] and st["models"] == [] and "not installed" in st["hint"]
