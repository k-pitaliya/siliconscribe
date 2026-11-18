"""The model menu: OpenCode's real list, Cloudflare Workers AI, and what is refused."""
import subprocess

import pytest

import model_catalog as mc
from cf_fake import ACCOUNT, TOKEN, FakeCloudflare, model_entry
from nim_fake import KEY as NIM_KEY, OTHER_KEY, FakeNim

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


def test_https_uses_the_certificate_bundle_the_app_ships_with_not_the_systems(monkeypatch):
    ctx = mc._ssl_context()
    assert ctx.verify_mode.name == "CERT_REQUIRED" and ctx.check_hostname                       # verification stays on
    import certifi
    assert len(ctx.get_ca_certs()) > 50 and certifi.where()                                       # and has real roots (the default build had none)
    seen = {}
    monkeypatch.setattr(mc.urllib.request, "urlopen", lambda req, timeout=None, context=None: seen.update(ctx=context) or (_ for _ in ()).throw(OSError("stop")))
    with pytest.raises(OSError):
        mc._urlopen(mc.urllib.request.Request("https://api.cloudflare.com/x"), 5)
    assert seen["ctx"] is not None                                                                # https gets the context
    with pytest.raises(OSError):
        mc._urlopen(mc.urllib.request.Request("http://127.0.0.1:1/x"), 5)
    assert seen["ctx"] is None                                                                    # the local test stand-in does not


# ------------------------------------------------------------------------------------ NVIDIA NIM
NIM_LIST = ["nvidia/nemotron-3.5-lightning-30b-a3b", "poolside/laguna-xs-2.1", "google/gemma-4-31b-it", "nvidia/nv-embedqa-e5-v5",
            "meta/llama-guard-4-12b", "nvidia/nemotron-3-ultra-550b-a55b", "minimaxai/minimax-m3.1-flash", "nvidia/nemotron-voicechat",
            "nvidia/ising-calibration-1.5-31b", "nobodyslash", "--bad/x", "google/gemma-4-31b-it", "bigcode/starcoder2-15b"]


def test_nim_prefix_keeps_nvidias_ids_apart_from_opencodes_own_nvidia_ids():
    assert mc.is_nim_id("nim/nvidia/nemotron-3-ultra-550b-a55b") and not mc.is_nim_id("nvidia/nvidia/nemotron-3-ultra-550b-a55b")
    assert mc.is_routed_id("nim/x/y") and mc.is_routed_id("@cf/x/y") and not mc.is_routed_id("opencode/x") and not mc.is_routed_id(None)


def test_nim_key_comes_from_one_deliberate_variable_and_never_from_the_unrelated_nvidia_api_key(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", OTHER_KEY)              # some other key that merely exists in the shell
    assert mc.nim_config() is None                              # is NOT picked up
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "your_nvidia_key_here")
    assert mc.nim_config() is None                              # a placeholder is not a key
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "not-an-nvapi-key")
    assert mc.nim_config() is None
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", NIM_KEY)
    assert mc.nim_config() == (NIM_KEY, mc.DEFAULT_NIM_BASE)
    monkeypatch.setenv("NVIDIA_NIM_BASE_URL", "http://127.0.0.1:9/v1/")
    assert mc.nim_config() == (NIM_KEY, "http://127.0.0.1:9/v1")


def test_nim_not_configured_says_what_to_do_and_lists_nothing():
    st = mc.nim_status()
    assert st["available"] is False and st["models"] == [] and "NVIDIA_NIM_API_KEY" in st["hint"]


def test_nim_catalogue_keeps_chat_models_prefixes_them_and_lists_the_fast_ones_first():
    ms = mc.parse_nim_models({"data": [{"id": i} for i in NIM_LIST]})
    ids = [m["id"] for m in ms]
    assert ids[:4] == ["nim/poolside/laguna-xs-2.1", "nim/nvidia/nemotron-3-ultra-550b-a55b", "nim/nvidia/nemotron-3.5-lightning-30b-a3b",
                       "nim/minimaxai/minimax-m3.1-flash"]
    assert ids[4:] == ["nim/google/gemma-4-31b-it"]                                  # the rest alphabetical, no duplicates
    assert not any(x in " ".join(ids) for x in ("embed", "guard", "voicechat", "calibration", "bad", "nobodyslash", "starcoder2"))   # starcoder2: listed but 404
    assert ms[0]["label"] == "poolside/laguna-xs-2.1" and ms[0]["group"] == "NVIDIA NIM" and ms[0]["provider"] == "nim"
    assert mc.parse_nim_models({}) == [] and mc.parse_nim_models(None) == []


@pytest.fixture()
def nim(monkeypatch):
    def make(**kw):
        server = FakeNim(**kw)
        monkeypatch.setenv("NVIDIA_NIM_BASE_URL", server.base)
        monkeypatch.setenv("NVIDIA_NIM_API_KEY", NIM_KEY)
        return server
    return make


def test_nim_live_catalogue_is_read_with_the_bearer_key(nim):
    with nim(models=NIM_LIST) as server:
        st = mc.nim_status()
    assert st["available"] and st["hint"] is None and len(st["models"]) == 5
    (method, path, headers, _), = server.requests
    assert (method, path) == ("GET", "/v1/models") and headers["authorization"] == f"Bearer {NIM_KEY}"


def test_nim_failures_fall_back_to_the_tested_models_with_a_plain_hint_and_no_secret(nim, monkeypatch):
    with nim(models_status=403):
        st = mc.nim_status()
    assert st["available"] and [m["id"] for m in st["models"]][0] == "nim/poolside/laguna-xs-2.1"
    assert "HTTP 403" in st["hint"] and NIM_KEY not in st["hint"]
    mc.clear_cache()
    monkeypatch.setenv("NVIDIA_NIM_BASE_URL", "http://127.0.0.1:1/v1")
    st = mc.nim_status()
    assert st["available"] and st["models"] and "tested fast" in st["hint"] and NIM_KEY not in st["hint"]


def test_nim_catalogue_is_cached_until_refreshed(nim):
    with nim(models=NIM_LIST) as server:
        mc.nim_status(); mc.nim_status()
        assert len(server.requests) == 1
        mc.nim_status(refresh=True)
        assert len(server.requests) == 2


def test_the_opencode_app_never_receives_the_nim_key_either(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", NIM_KEY)
    monkeypatch.setenv("NVIDIA_API_KEY", OTHER_KEY)             # the older variable is left alone: OpenCode may use it itself
    env = mc.child_env()
    assert "NVIDIA_NIM_API_KEY" not in env and NIM_KEY not in env.values() and env["NVIDIA_API_KEY"] == OTHER_KEY


def test_copilot_auto_is_labelled_honestly_and_never_called_free():
    ms = mc.parse_opencode_models("opencode/deepseek-v4.1-flash-free\ngithub-copilot/auto\nnvidia/x/y\n")
    cp = next(m for m in ms if m["id"] == "github-copilot/auto")
    assert cp["group"] == "GitHub Copilot" and cp["free"] is None                      # hidden behind "Show other models"
    assert "does not say which" in cp["note"] and "allowance" in cp["note"]
    assert [m["provider"] for m in ms] == ["opencode", "github-copilot", "nvidia"]     # shown after OpenCode, before the rest

