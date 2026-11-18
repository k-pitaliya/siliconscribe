"""The model menu: OpenCode's real list, Cloudflare Workers AI, and what is refused."""
import subprocess

import pytest

import model_catalog as mc
from cf_fake import ACCOUNT, TOKEN, FakeCloudflare, model_entry

OC = """opencode/deepseek-v4.1-flash-free
opencode/big-pickle
opencode/gpt-5.5
opencode-go/kimi-k3
opencode-go/hy4-flash-free
nvidia/deepseek-ai/deepseek-v4.1-flash
openrouter/meta-llama/llama-3.3-70b-instruct:free
openrouter/anthropic/claude-x

--help
two words/here
opencode/deepseek-v4.1-flash-free
justonename
"""


@pytest.fixture(autouse=True)
def fresh_cache():
    mc.clear_cache()
    yield
    mc.clear_cache()


@pytest.mark.parametrize("good", ["opencode/deepseek-v4.1-flash-free", "@cf/openai/gpt-oss-120b", "nvidia/deepseek-ai/x", "a", "gpt-5.3-codex-spark:high"])
def test_ordinary_model_ids_are_accepted(good):
    assert mc.is_valid_model_id(good)


@pytest.mark.parametrize("bad", ["", "--help", "-m", "a b", "a;b", "a\nb", "$(x)", "x" * 101, "/abs", ".hidden", None, 5, "a`b`"])
def test_ids_that_could_become_flags_or_shell_text_are_refused(bad):
    assert not mc.is_valid_model_id(bad)


def test_parsing_keeps_valid_unique_ids_marks_only_named_free_models_and_orders_free_first():
    ms = mc.parse_opencode_models(OC)
    ids = [m["id"] for m in ms]
    assert len(ids) == len(set(ids)) == 8                         # junk, flags and the duplicate are gone
    assert "--help" not in ids and "justonename" not in ids
    by = {m["id"]: m for m in ms}
    assert by["opencode/deepseek-v4.1-flash-free"]["free"] is True
    assert by["openrouter/meta-llama/llama-3.3-70b-instruct:free"]["free"] is True
    assert by["opencode/gpt-5.5"]["free"] is None                  # not claimed to be paid: nothing proves it
    assert by["opencode/big-pickle"]["free"] is None
    assert by["opencode/deepseek-v4.1-flash-free"]["group"] == "OpenCode" and by["opencode-go/kimi-k3"]["group"] == "OpenCode Go"
    opencode_first = [m["id"] for m in ms if m["provider"] == "opencode"]
    assert opencode_first[0] == "opencode/deepseek-v4.1-flash-free"  # free before the rest within a provider
    assert [m["provider"] for m in ms][:3] == ["opencode"] * 3       # providers in a fixed order


def test_listing_is_cached_and_a_refresh_asks_again(monkeypatch):
    calls = []
    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=OC, stderr="")
    monkeypatch.setattr(mc.subprocess, "run", fake_run)
    assert len(mc.opencode_models()) == 8 and len(mc.opencode_models()) == 8
    assert len(calls) == 1 and calls[0] == ["opencode", "models"]
    mc.opencode_models(refresh=True)
    assert len(calls) == 2


def test_a_missing_or_failing_app_gives_an_empty_list_and_is_retried_soon(monkeypatch):
    def boom(cmd, **kw):
        raise FileNotFoundError("opencode")
    monkeypatch.setattr(mc.subprocess, "run", boom)
    assert mc.opencode_models() == []
    state = {"now": 1000.0}
    monkeypatch.setattr(mc.time, "time", lambda: state["now"])
    mc.clear_cache()
    assert mc.opencode_models() == []
    monkeypatch.setattr(mc.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=OC, stderr=""))
    assert mc.opencode_models() == []                   # still inside the 30 s failure window
    state["now"] += mc.FAILURE_TTL + 1
    assert len(mc.opencode_models()) == 8               # retried after it


def test_cloudflare_needs_a_valid_account_id_and_a_token(monkeypatch):
    for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert mc.cloudflare_config() is None
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    assert mc.cloudflare_config() is None                              # no token yet
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "your_token_here")
    assert mc.cloudflare_config() is None                              # a placeholder is not a token
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    assert mc.cloudflare_config() == (ACCOUNT, TOKEN)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "../../etc")
    assert mc.cloudflare_config() is None                              # the account id ends up in a URL: 32 hex characters only
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN")
    monkeypatch.setenv("CLOUDFLARE_API_KEY", TOKEN)                    # the name Cloudflare's own docs use
    assert mc.cloudflare_config() == (ACCOUNT, TOKEN)


def test_not_configured_says_what_to_do_and_lists_nothing(monkeypatch):
    for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    st = mc.cloudflare_status()
    assert st["available"] is False and st["models"] == [] and "CLOUDFLARE_ACCOUNT_ID" in st["hint"]


def test_search_results_keep_text_models_only_and_refuse_odd_names():
    payload = {"result": [model_entry("@cf/openai/gpt-oss-120b"), model_entry("@cf/baai/bge-large-en-v1.5", task="Text Embeddings"),
                          model_entry("@hf/mistral/mistral-7b-instruct-v0.2"), {"name": "@cf/no/task"}, model_entry("not-cloudflare/x"),
                          model_entry("@cf/bad name/x"), model_entry("@cf/x/long", description="d" * 500)]}
    ids = [m["id"] for m in mc.parse_cloudflare_search(payload)]
    assert ids == ["@cf/openai/gpt-oss-120b", "@hf/mistral/mistral-7b-instruct-v0.2", "@cf/no/task", "@cf/x/long"]
    assert all(len(m["note"]) <= 140 for m in mc.parse_cloudflare_search(payload))
    assert mc.parse_cloudflare_search({}) == [] and mc.parse_cloudflare_search(None) == []


@pytest.fixture()
def cf(monkeypatch):
    def make(**kw):
        server = FakeCloudflare(**kw)
        monkeypatch.setenv("CLOUDFLARE_API_BASE", server.base)
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
        return server
    return make


def test_live_catalogue_is_read_with_the_bearer_token_across_pages(cf):
    page1 = [model_entry(f"@cf/v/m{i:03d}") for i in range(100)]
    page2 = [model_entry("@cf/openai/gpt-oss-120b"), model_entry("@cf/baai/embed", task="Text Embeddings")]
    with cf(search_pages=[page1, page2]) as server:
        st = mc.cloudflare_status()
    assert st["available"] and st["hint"] is None and len(st["models"]) == 101
    assert st["models"][0]["id"] == "@cf/openai/gpt-oss-120b"             # the suggested default sorts first
    methods = [(m, p.split("?")[0]) for m, p, h, b in server.requests]
    assert methods == [("GET", f"/client/v4/accounts/{ACCOUNT}/ai/models/search")] * 2
    assert all(h["authorization"] == f"Bearer {TOKEN}" for _, _, h, _ in server.requests)
    assert "per_page=100" in server.requests[0][1] and "page=2" in server.requests[1][1]


def test_a_forbidden_token_falls_back_to_suggested_models_with_a_plain_hint_and_no_secret(cf):
    with cf(search_status=403):
        st = mc.cloudflare_status()
    assert st["available"] and len(st["models"]) == len(mc.STATIC_CLOUDFLARE)
    assert "HTTP 403" in st["hint"] and TOKEN not in st["hint"] and ACCOUNT not in st["hint"]


def test_an_unreachable_cloudflare_also_falls_back(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_BASE", "http://127.0.0.1:1/client/v4")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    st = mc.cloudflare_status()
    assert st["available"] and st["models"] and "suggested models" in st["hint"] and TOKEN not in st["hint"]


def test_cloudflare_catalogue_is_cached_until_refreshed(cf):
    with cf(search_pages=[[model_entry("@cf/openai/gpt-oss-120b")]]) as server:
        mc.cloudflare_status(); mc.cloudflare_status()
        assert len(server.requests) == 1
        mc.cloudflare_status(refresh=True)
        assert len(server.requests) == 2
