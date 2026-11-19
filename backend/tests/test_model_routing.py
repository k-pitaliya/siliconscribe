"""Per-stage model routing: the model-agnostic seam that lets a deployment swap in
stronger models for the verification-critical stages without code changes."""

from types import SimpleNamespace

from models import RTLDesignSpec, PortSpec


def _provider(monkeypatch, **stage_env):
    from llm_service import OpenAIProvider
    for k in ("INTENT", "RTL", "TESTBENCH", "EXPLAIN", "FIX"):
        monkeypatch.delenv(f"LLM_MODEL_{k}", raising=False)
    for k, v in stage_env.items():
        monkeypatch.setenv(f"LLM_MODEL_{k.upper()}", v)
    prov = OpenAIProvider(api_key="test-key", base_url="http://127.0.0.1:9/v1",
                          model="base-model", mini_model="mini-model", name="test")
    seen = []

    def fake_create(**kw):
        seen.append(kw["model"])
        msg = SimpleNamespace(content="module m; endmodule")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)

    prov.client.chat.completions.create = fake_create
    return prov, seen


SPEC = RTLDesignSpec(module_name="m", ports=[PortSpec(name="a", direction="input", width=1)], behavior="x")


def test_default_model_used_when_no_routing(monkeypatch):
    prov, seen = _provider(monkeypatch)
    prov.generate_rtl(SPEC, None)
    prov.generate_testbench("module m; endmodule", SPEC)
    assert seen == ["base-model", "base-model"]


def test_stage_models_route_each_stage(monkeypatch):
    prov, seen = _provider(monkeypatch, testbench="strong-tb-model", rtl="rtl-model", fix="strong-fix-model")
    prov.generate_rtl(SPEC, None)
    prov.generate_testbench("module m; endmodule", SPEC)
    prov.fix_design("module m; endmodule", "module testbench; endmodule", "log")
    # The stand-in's repair reply is unreadable, so the fixer asks once more: both calls go to the fix model.
    assert seen[:3] == ["rtl-model", "strong-tb-model", "strong-fix-model"] and set(seen[2:]) == {"strong-fix-model"}


def test_explicit_per_request_model_beats_stage_model(monkeypatch):
    prov, seen = _provider(monkeypatch, testbench="strong-tb-model")
    prov.generate_testbench("module m; endmodule", SPEC, model="user-picked-model")
    assert seen == ["user-picked-model"]


def test_ui_sending_the_default_model_does_not_disable_routing(monkeypatch):
    # The web UI always sends the currently configured model id. That must not
    # count as an override, or stage routing could never take effect in the app.
    prov, seen = _provider(monkeypatch, testbench="strong-tb-model")
    prov.generate_testbench("module m; endmodule", SPEC, model="base-model")
    assert seen == ["strong-tb-model"]


def test_explain_uses_mini_model_by_default_and_stage_model_when_set(monkeypatch):
    prov, seen = _provider(monkeypatch)
    prov.explain_design("module m; endmodule", SPEC)
    assert seen == ["mini-model"]
    prov, seen = _provider(monkeypatch, explain="tiny-explainer")
    prov.explain_design("module m; endmodule", SPEC)
    assert seen == ["tiny-explainer"]


def test_models_endpoint_reports_a_separate_testbench_model_and_logs_each_stage(monkeypatch, caplog):
    import logging
    import llm_service
    prov, _seen = _provider(monkeypatch, testbench="other-tb-model")
    monkeypatch.setattr(llm_service, "_provider", prov)
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    info = llm_service.list_models()
    assert info["stage_models"] == {"testbench": "other-tb-model"}
    default = next(m for m in info["models"] if m["id"] == "base-model")
    assert "testbench written by other-tb-model" in default["note"]

    with caplog.at_level(logging.INFO, logger="siliconscribe.llm"):
        prov.generate_rtl(SPEC, None)
        prov.generate_testbench("module m; endmodule", SPEC)
    lines = [r.getMessage() for r in caplog.records]
    assert "llm stage=rtl model=base-model" in lines
    assert "llm stage=testbench model=other-tb-model" in lines          # the two stages used different models


def test_no_stage_note_when_every_stage_uses_the_default_model(monkeypatch):
    import llm_service
    prov, _seen = _provider(monkeypatch, testbench="base-model")          # same as the default: not "separate"
    monkeypatch.setattr(llm_service, "_provider", prov)
    monkeypatch.delenv("OFFLINE_MODE", raising=False)
    info = llm_service.list_models()
    assert info["stage_models"] == {}
    assert "testbench written by" not in info["models"][0]["note"]



def test_an_unreadable_repair_reply_is_asked_for_once_more(monkeypatch):
    prov, seen = _provider(monkeypatch, fix="fix-model")          # the stand-in always answers "module m; endmodule"
    out = prov.fix_design("module m; endmodule", "module testbench; endmodule", "log")
    assert seen == ["fix-model", "fix-model"] and out["parse_failed"] is True
