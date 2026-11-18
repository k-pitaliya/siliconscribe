"""Reviewing the specification before generating: the parse-only endpoint, a confirmed spec replacing the model's reading,
and the limits on a user-edited spec."""

import pytest
from fastapi.testclient import TestClient

import llm_service
import orchestrator
from models import ParameterSpec, PortSpec, RTLDesignSpec, RunRequest
from simulator import IcarusSimulator
from test_independent_testbench import DEFAULT, GOOD_RTL, GOOD_TB, script  # noqa: F401  (the scripted live stand-in)

PROMPT = "Design a 4-bit synchronous up-counter with async reset and enable"


def spec(**over):
    base = dict(module_name="counter", ports=[PortSpec(name="clk", direction="input", width=1), PortSpec(name="count", direction="output", width=4)],
                behavior="Counts up on every clock edge.", constraints=["asynchronous active-low reset"])
    base.update(over)
    return RTLDesignSpec(**base)


@pytest.fixture()
def client(monkeypatch):
    import main
    monkeypatch.setattr(main, "_check_rate_limit", lambda ip: None)
    return TestClient(main.app)


def test_parsing_alone_returns_the_specification_and_generates_nothing(client, monkeypatch):
    calls = []
    monkeypatch.setattr(llm_service, "generate_rtl", lambda *a, **k: calls.append("rtl"))
    r = client.post("/api/spec/parse", json={"prompt": PROMPT})
    assert r.status_code == 200
    body = r.json()
    assert body["module_name"] and body["ports"] and body["behavior"] and calls == []


def test_parse_endpoint_validates_its_input_and_reports_an_unusable_model_plainly(client, monkeypatch):
    assert client.post("/api/spec/parse", json={"prompt": ""}).status_code == 422
    assert client.post("/api/spec/parse", json={"prompt": "x", "model": "--help"}).status_code == 422
    def not_set_up(*a, **k):
        raise llm_service.ModelNotAvailable("NVIDIA NIM is not set up.")
    monkeypatch.setattr(llm_service, "parse_intent", not_set_up)
    r = client.post("/api/spec/parse", json={"prompt": "x", "model": "nim/a/b"})
    assert r.status_code == 400 and "NVIDIA NIM is not set up" in r.json()["detail"]
    def down(*a, **k):
        raise llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: x after 360s")
    monkeypatch.setattr(llm_service, "parse_intent", down)
    r = client.post("/api/spec/parse", json={"prompt": "x"})
    assert r.status_code == 502 and "did not answer in time" in r.json()["detail"]


@pytest.mark.parametrize("bad", [
    dict(module_name="my counter"), dict(module_name="a;b"), dict(module_name="x" * 65), dict(module_name="1abc"),
    dict(ports=[]), dict(ports=[PortSpec(name="clk", direction="input", width=1)] * 65),
    dict(ports=[PortSpec(name="bad name", direction="input", width=1)]),
    dict(ports=[PortSpec(name="a", direction="input", width=1, description="d" * 301)]),
    dict(parameters=[ParameterSpec(name="P", default=1)] * 17), dict(parameters=[ParameterSpec(name="bad-name", default=1)]),
    dict(behavior="b" * 4001), dict(constraints=["c"] * 31), dict(constraints=["c" * 501]),
])
def test_a_user_edited_specification_is_bounded_and_uses_plain_identifiers(bad):
    with pytest.raises(Exception):
        RunRequest(prompt="x", spec=spec(**bad))


def test_an_ordinary_edited_specification_is_accepted():
    r = RunRequest(prompt="x", spec=spec(behavior="Counts up and wraps.", constraints=["reset wins over enable"]))
    assert r.spec.module_name == "counter" and r.spec.constraints == ["reset wins over enable"]


def test_a_confirmed_specification_replaces_the_models_reading_and_is_what_gets_built(script, tmp_path, monkeypatch):  # noqa: F811
    seen = {}
    real_rtl = llm_service.generate_rtl
    def rtl(sp, freq=None, model=None, **k):
        seen["spec"] = sp
        return real_rtl(sp, freq, model=model, **k)
    monkeypatch.setattr(llm_service, "generate_rtl", rtl)
    confirmed = RTLDesignSpec(module_name="counter", behavior="EDITED BY THE USER: wraps at 15.",
                              ports=[PortSpec(name="clk", direction="input", width=1), PortSpec(name="rst_n", direction="input", width=1),
                                     PortSpec(name="enable", direction="input", width=1), PortSpec(name="count", direction="output", width=4)])
    events = list(orchestrator.pipeline_events(PROMPT, "spec1", IcarusSimulator(workspace=str(tmp_path)), spec_override=confirmed))
    assert not any(fn == "parse_intent" for fn, _ in script.calls)                 # the model was not asked to read the prompt again
    assert seen["spec"].behavior == "EDITED BY THE USER: wraps at 15."
    intent = next(e for e in events if e["stage"] == "intent")
    assert "Using the specification you confirmed" in intent["message"] and intent["rtl_spec"]["behavior"].startswith("EDITED BY THE USER")
    assert next(e for e in events if e["stage"] == "done")["response"]["rtl_spec"]["behavior"].startswith("EDITED BY THE USER")


def test_after_a_confirmed_specification_an_outage_fails_honestly_instead_of_swapping_in_the_demo(script, tmp_path, monkeypatch):  # noqa: F811
    def down(*a, **k):
        raise llm_service.LLMUpstreamError("LLM_UPSTREAM:Timeout: x after 360s")
    monkeypatch.setattr(llm_service, "generate_rtl", down)
    events = list(orchestrator.pipeline_events(PROMPT, "spec2", IcarusSimulator(workspace=str(tmp_path)), spec_override=spec()))
    assert events[-1]["stage"] == "error" and not any(e["stage"] == "done" for e in events)
    assert "became unavailable" in events[-1]["message"] or "did not answer" in events[-1]["message"]


def test_the_stream_endpoint_passes_the_confirmed_spec_and_testbench_model_through(client, monkeypatch):
    import main
    got = {}
    def fake_events(**kw):
        got.update(kw)
        yield {"stage": "done", "status": "PASS", "message": "ok", "response": None}
    monkeypatch.setattr(main, "pipeline_events", fake_events)
    monkeypatch.setattr(main, "db", None)
    body = {"prompt": PROMPT, "testbench_model": "nim/poolside/laguna-xs-2.1",
            "spec": spec().model_dump()}
    client.post("/api/design/stream", json=body)
    assert got["testbench_model"] == "nim/poolside/laguna-xs-2.1" and got["spec_override"].module_name == "counter"
