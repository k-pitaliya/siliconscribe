"""Choosing a model per run: OpenCode models, Cloudflare Workers AI, and what happens when the choice does not work."""
import json
import subprocess
from types import SimpleNamespace

import pytest

import llm_service
import model_catalog as mc
import orchestrator
from cf_fake import ACCOUNT, TOKEN, FakeCloudflare, model_entry
from models import PortSpec, RTLDesignSpec

SPEC = RTLDesignSpec(module_name="m", ports=[PortSpec(name="a", direction="input", width=1)], behavior="x")
CATALOG = mc.parse_opencode_models("opencode/deepseek-v4.1-flash-free\nopencode/big-pickle\nopencode/gpt-5.5\nopencode-go/kimi-k3\n"
                                   "opencode-go/hy4-flash-free\nnvidia/x/y\nopenrouter/a/b:free\nopenrouter/a/c\n")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    mc.clear_cache()
    for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_API_BASE", "OFFLINE_MODE",
              "LLM_MODEL_TESTBENCH", "LLM_MODEL_RTL"):
        monkeypatch.delenv(k, raising=False)
    llm_service._cloudflare_cache.clear()
    yield
    mc.clear_cache()
    llm_service._cloudflare_cache.clear()


def cloudflare(monkeypatch, **kw):
    server = FakeCloudflare(**kw)
    monkeypatch.setenv("CLOUDFLARE_API_BASE", server.base)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", TOKEN)
    return server


# ----------------------------------------------------------------------------------- routing
def test_cloudflare_ids_go_to_cloudflare_and_everything_else_to_the_configured_provider(monkeypatch):
    cloudflare(monkeypatch)
    assert llm_service.get_provider("@cf/openai/gpt-oss-120b").name == "cloudflare"
    assert llm_service.get_provider("@hf/mistral/x").name == "cloudflare"
    assert llm_service.get_provider("opencode/big-pickle") is llm_service._provider
    assert llm_service.get_provider(None) is llm_service._provider
    assert llm_service.get_provider("@cf/openai/gpt-oss-120b") is llm_service.get_provider("@cf/meta/x")     # one provider, built once


def test_choosing_cloudflare_without_credentials_says_how_to_set_it_up():
    with pytest.raises(llm_service.ModelNotAvailable) as e:
        llm_service.get_provider("@cf/openai/gpt-oss-120b")
    assert "CLOUDFLARE_ACCOUNT_ID" in str(e.value) and "CLOUDFLARE_API_TOKEN" in str(e.value)


def test_offline_mode_wins_over_any_model_choice(monkeypatch):
    cloudflare(monkeypatch)
    monkeypatch.setenv("OFFLINE_MODE", "1")
    assert isinstance(llm_service.get_provider("@cf/openai/gpt-oss-120b"), llm_service.OfflineProvider)


# ------------------------------------------------------------ Cloudflare end to end (local fake of its API)
def test_a_cloudflare_chat_hits_the_account_endpoint_with_the_bearer_token_and_no_reasoning_field(monkeypatch):
    with cloudflare(monkeypatch, chat_text="Counts up.") as server:
        text = llm_service.explain_design("module m; endmodule", SPEC, model="@cf/meta/llama-3.3-70b-instruct-fp8-fast")
    assert text == "Counts up."
    (method, path, headers, body), = server.requests
    assert (method, path) == ("POST", f"/client/v4/accounts/{ACCOUNT}/ai/v1/chat/completions")
    assert headers["authorization"] == f"Bearer {TOKEN}"
    assert body["model"] == "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    assert "reasoning" not in json.dumps(body) and "extra_body" not in body                      # Workers AI is strict about unknown fields
    assert body["messages"][-1]["role"] == "user" and body["max_tokens"] > 0


def test_reasoning_effort_is_forwarded_only_to_the_gpt_oss_models(monkeypatch):
    with cloudflare(monkeypatch) as server:
        prov = llm_service.get_provider("@cf/openai/gpt-oss-120b")
        prov._chat(None, "hi", 0.0, model="@cf/openai/gpt-oss-120b", reasoning_effort="high")
        prov._chat(None, "hi", 0.0, model="@cf/meta/llama-3.3-70b-instruct-fp8-fast", reasoning_effort="high")
    assert server.requests[0][3].get("reasoning_effort") == "high"
    assert "reasoning_effort" not in server.requests[1][3]


def test_the_stage_model_variables_that_name_opencode_models_never_reach_cloudflare(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TESTBENCH", "opencode/some-other-model")
    with cloudflare(monkeypatch) as server:
        prov = llm_service.get_provider("@cf/openai/gpt-oss-120b")
        prov._chat(None, "hi", 0.0, model="@cf/openai/gpt-oss-120b", stage="testbench")        # the provider's own default model
    assert prov.stage_models == {} and server.requests[0][3]["model"] == "@cf/openai/gpt-oss-120b"


def test_a_rejected_token_is_a_typed_upstream_error_that_never_contains_the_token(monkeypatch):
    with cloudflare(monkeypatch, chat_status=403) as server:
        prov = llm_service.get_provider("@cf/openai/gpt-oss-120b")
        prov.max_retries = 0
        prov.client.max_retries = 0
        with pytest.raises(llm_service.LLMUpstreamError) as e:
            prov._chat(None, "hi", 0.0, model="@cf/openai/gpt-oss-120b")
    assert TOKEN not in str(e.value) and "model=@cf/openai/gpt-oss-120b" in str(e.value)


# ------------------------------------------------------------------------------- OpenCode app
def opencode_provider(monkeypatch, cmds):
    def fake_run(cmd, **kw):
        cmds.append(cmd)
        out = json.dumps({"type": "text", "part": {"text": "ok"}})
        return subprocess.CompletedProcess(cmd, 0, stdout=out + "\n", stderr="")
    monkeypatch.setattr(llm_service.subprocess, "run", fake_run)
    monkeypatch.setattr(llm_service.shutil, "which", lambda n: "/usr/bin/opencode")
    return llm_service.OpenCodeAppProvider(model="deepseek-v4.1-flash-free")


def test_the_menu_spelling_of_the_default_model_is_the_same_model_so_stage_routing_still_applies(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TESTBENCH", "opencode/big-pickle")
    cmds = []
    prov = opencode_provider(monkeypatch, cmds)
    prov._chat(None, "x", 0.0, model="opencode/deepseek-v4.1-flash-free", stage="testbench")    # what the menu sends for the default
    prov._chat(None, "x", 0.0, model="opencode/gpt-5.5", stage="testbench")                      # a deliberate other choice wins
    assert [c[c.index("-m") + 1] for c in cmds] == ["opencode/big-pickle", "opencode/gpt-5.5"]


@pytest.mark.parametrize("bad", ["-x/y", "a b/c", "x;y", "a\nb", "$(id)/x"])
def test_a_malformed_model_name_never_reaches_the_subprocess(monkeypatch, bad):
    cmds = []
    prov = opencode_provider(monkeypatch, cmds)
    with pytest.raises(llm_service.ModelNotAvailable):
        prov._chat(None, "x", 0.0, model=bad)
    assert cmds == []


def test_a_bare_flag_cannot_act_as_one_because_it_is_always_prefixed(monkeypatch):
    cmds = []
    prov = opencode_provider(monkeypatch, cmds)
    prov._chat(None, "x", 0.0, model="--help")
    assert cmds[0][cmds[0].index("-m") + 1] == "opencode/--help"           # one argument, starting with the provider name


# ---------------------------------------------------------------------------------- the menu
def menu(monkeypatch, current="deepseek-v4.1-flash-free", **kw):
    prov = llm_service.OpenCodeAppProvider(model=current)
    monkeypatch.setattr(llm_service, "_provider", prov)
    monkeypatch.setattr(mc, "opencode_models", lambda refresh=False: [dict(m) for m in CATALOG])
    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    return llm_service.list_models(**kw)


def test_the_menu_lists_free_models_first_and_hides_the_rest_until_asked(monkeypatch):
    out = menu(monkeypatch)
    ids = [m["id"] for m in out["models"]]
    assert out["current"] == "opencode/deepseek-v4.1-flash-free" and ids[0] == out["current"]      # normalised, and first
    assert set(ids) == {"opencode/deepseek-v4.1-flash-free", "opencode-go/hy4-flash-free", "openrouter/a/b:free"}
    assert out["paid_hidden"] == 5                                                                  # 8 in the app - 3 free
    full = menu(monkeypatch, include_paid=True)
    assert len(full["models"]) == 8 and full["paid_hidden"] == 0


def test_a_configured_model_missing_from_the_apps_list_is_still_offered(monkeypatch):
    out = menu(monkeypatch, current="some-private-model")
    assert out["models"][0]["id"] == "opencode/some-private-model" and out["models"][0]["note"] == "Configured model"


def test_cloudflare_appears_as_its_own_provider_when_set_up_and_with_a_hint_when_not(monkeypatch):
    out = menu(monkeypatch)
    cf = next(p for p in out["providers"] if p["id"] == "cloudflare")
    assert cf["available"] is False and "CLOUDFLARE_ACCOUNT_ID" in cf["hint"]
    assert not any(m["provider"] == "cloudflare" for m in out["models"])
    with cloudflare(monkeypatch, search_pages=[[model_entry("@cf/openai/gpt-oss-120b"), model_entry("@cf/qwen/qwen2.5-coder-32b-instruct")]]):
        out = menu(monkeypatch)
    cf = next(p for p in out["providers"] if p["id"] == "cloudflare")
    assert cf["available"] and cf["count"] == 2
    assert [m["id"] for m in out["models"] if m["provider"] == "cloudflare"][0] == "@cf/openai/gpt-oss-120b"
    assert all("provider" in m and "group" in m for m in out["models"])


def test_other_provider_types_keep_the_curated_list_and_gain_the_new_fields(monkeypatch):
    monkeypatch.setattr(llm_service, "is_offline", lambda: False)
    monkeypatch.setattr(llm_service, "current_model", lambda: "meta/llama-3.3-70b-instruct")
    out = llm_service.list_models()
    assert out["models"][0]["id"] == "meta/llama-3.3-70b-instruct" and out["models"][0]["provider"] == "opencode"
    assert out["paid_hidden"] == 0


# ----------------------------------------------------------------------------------- a run
@pytest.fixture()
def live_stand_in(monkeypatch):
    """A 'live' provider that is really the offline designs, so a whole run can be driven without a model."""
    off = llm_service.OfflineProvider()
    seen = {"models": []}
    def wrap(name):
        def call(*a, model=None, **kw):
            seen["models"].append(model)
            if seen.get("fail") and (model or "") == seen["fail"]:
                raise llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: opencode model=x after 360s")
            return getattr(off, name)(*a, model=model, **kw)
        return call
    for fn in ("parse_intent", "generate_rtl", "generate_testbench", "explain_design", "fix_design"):
        monkeypatch.setattr(llm_service, fn, wrap(fn))
    monkeypatch.setattr(llm_service, "get_provider", lambda model=None: SimpleNamespace(name="standin"))
    monkeypatch.setattr(llm_service, "current_model_id", lambda: "opencode/the-default")
    monkeypatch.setattr(llm_service, "is_default_model", lambda m: not m or m == "opencode/the-default")
    return seen


def run(tmp_path, **kw):
    from simulator import IcarusSimulator
    return list(orchestrator.pipeline_events("Design a 4-bit synchronous up-counter with async reset and enable", "sw1",
                                             IcarusSimulator(workspace=str(tmp_path)), **kw))


def test_the_result_says_which_model_wrote_the_design(live_stand_in, tmp_path):
    default = run(tmp_path / "a")[-1]["response"]
    other = run(tmp_path / "b", model="@cf/openai/gpt-oss-120b")[-1]["response"]
    assert default["model"] == "opencode/the-default" and other["model"] == "@cf/openai/gpt-oss-120b"
    assert "opencode/the-default" in run(tmp_path / "c")[0]["message"] and "@cf/openai/gpt-oss-120b" in run(tmp_path / "d", model="@cf/openai/gpt-oss-120b")[0]["message"]


def test_a_model_the_user_chose_that_fails_is_reported_not_replaced_by_the_scripted_demo(live_stand_in, tmp_path):
    live_stand_in["fail"] = "@cf/openai/gpt-oss-120b"
    events = run(tmp_path, model="@cf/openai/gpt-oss-120b")
    assert events[-1]["stage"] == "error" and not any(e["stage"] == "done" for e in events)
    msg = events[-1]["message"]
    assert "The model you chose (@cf/openai/gpt-oss-120b) could not be used: it did not answer in time" in msg
    assert "Pick another model" in msg and len(msg) < 300


def test_the_default_model_keeps_the_labelled_offline_safety_net(live_stand_in, monkeypatch, tmp_path):
    def failing(*a, model=None, **kw):
        raise llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: x")
    monkeypatch.setattr(llm_service, "parse_intent", failing)
    done = run(tmp_path)[-1]["response"]                     # no model chosen: the configured default is in use
    assert done["fallback_notice"] and done["model"] == "offline demo"


def test_unavailable_cloudflare_is_reported_in_plain_words(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_service, "_provider", SimpleNamespace(name="standin"))    # a live provider is configured; Cloudflare is not
    events = run(tmp_path, model="@cf/openai/gpt-oss-120b")
    assert events[-1]["stage"] == "error" and "CLOUDFLARE_ACCOUNT_ID" in events[-1]["message"]
    assert not any(e["stage"] == "done" for e in events)


# ------------------------------------------------------------------------------------ the API
def test_models_endpoint_passes_the_options_and_requests_reject_malformed_ids(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    seen = {}
    monkeypatch.setattr(main.llm_service, "list_models", lambda include_paid=False, refresh=False: seen.update(p=include_paid, r=refresh) or {"models": []})
    c = TestClient(main.app)
    c.get("/api/models")
    assert seen == {"p": False, "r": False}
    c.get("/api/models?include_paid=true&refresh=true")
    assert seen == {"p": True, "r": True}
    for bad in ("--help", "a b", "x;rm", "-m", "a" * 101):
        r = c.post("/api/design/run", json={"prompt": "a counter", "model": bad})
        assert r.status_code == 422, bad
    from models import RunRequest
    for good in ("opencode/big-pickle", "@cf/openai/gpt-oss-120b", "deepseek-v4.1-flash-free", "nvidia/deepseek-ai/deepseek-v4.1-flash"):
        assert RunRequest(prompt="a counter", model=good).model == good
