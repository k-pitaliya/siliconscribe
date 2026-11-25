"""The model's own reasoning is shown next to the step that produced it: display only, never the answer, and never
attached to another request (the web server reuses threads)."""
import json
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

import llm_service
import offline_designs as od
import orchestrator
from llm_service import OpenCodeAppProvider, _reply_reasoning, take_reasoning
from simulator import IcarusSimulator


@pytest.fixture(autouse=True)
def clean_slot():
    take_reasoning()
    yield
    take_reasoning()


def _opencode_stdout(reasoning, text):
    lines = [{"type": "step_start"}, {"type": "reasoning", "part": {"text": reasoning}},
             {"type": "text", "part": {"text": text}}, {"type": "step_finish"}]
    return "\n".join(json.dumps(x) for x in lines) + "\n"


def test_opencode_reasoning_is_recorded_but_never_part_of_the_answer(monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(stdout=_opencode_stdout("I will use a case statement.", "module m; endmodule"), stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "run", run)
    out = OpenCodeAppProvider(model="deepseek-v4.1-flash-free")._chat(None, "write it", 0.2)
    assert out == "module m; endmodule"                                   # the answer only
    assert "--thinking" in seen["cmd"] and seen["cmd"][-1] == "write it"   # the prompt stays the last argument
    assert take_reasoning() == "I will use a case statement."
    assert take_reasoning() == ""                                         # taking it clears it


def test_thinking_can_be_switched_off(monkeypatch):
    seen = {}
    monkeypatch.setenv("OPENCODE_THINKING", "0")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: (seen.setdefault("cmd", cmd),
                        SimpleNamespace(stdout=_opencode_stdout("x", "ok"), stderr="", returncode=0))[1])
    OpenCodeAppProvider(model="deepseek-v4.1-flash-free")._chat(None, "q", 0.2)
    assert "--thinking" not in seen["cmd"]


@pytest.mark.parametrize("msg,expected", [
    (SimpleNamespace(content="a", reasoning_content="because"), "because"),
    (SimpleNamespace(content="a", reasoning=None, model_extra={"reasoning": "via extra"}), "via extra"),
    ({"content": "a", "reasoning_content": "dict form"}, "dict form"),
    (SimpleNamespace(content="a"), None),
    (SimpleNamespace(content="a", reasoning_content="   "), None),
])
def test_reasoning_is_read_from_openai_compatible_replies(msg, expected):
    assert _reply_reasoning(msg) == expected


def test_reasoning_is_capped():
    llm_service._note_reasoning("x" * (llm_service.REASONING_MAX_CHARS * 3))
    assert len(take_reasoning()) <= llm_service.REASONING_MAX_CHARS + 20


def test_another_threads_reasoning_is_invisible():
    t = threading.Thread(target=lambda: llm_service._note_reasoning("other request"))
    t.start()
    t.join()
    assert take_reasoning() == ""


# ---------------------------------------------------------------- the pipeline attaches it to the right step
needs_icarus = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")
GOOD_TB, GOOD_RTL = od.get_design("counter")["tb"], od.get_design("counter")["rtl"]


@pytest.fixture()
def scripted(monkeypatch):
    off = llm_service.OfflineProvider()

    def parse_intent(prompt, model=None, **k):
        return off.parse_intent(prompt)                         # no reasoning for this step

    def generate_rtl(spec, freq=None, model=None, **k):
        llm_service._note_reasoning("RTL: a 4-bit register with enable.")
        return GOOD_RTL

    def generate_testbench(rtl, spec, model=None, **k):
        llm_service._note_reasoning("TB: count 0..15, then hold with enable low.")
        return GOOD_TB

    monkeypatch.setattr(llm_service, "parse_intent", parse_intent)
    monkeypatch.setattr(llm_service, "generate_rtl", generate_rtl)
    monkeypatch.setattr(llm_service, "generate_testbench", generate_testbench)
    monkeypatch.setattr(llm_service, "explain_design", lambda rtl, spec, model=None, **k: "x")
    monkeypatch.setattr(llm_service, "get_provider", lambda model=None: SimpleNamespace(name="standin"))
    monkeypatch.setattr(llm_service, "current_model_id", lambda: "opencode/default-m")
    monkeypatch.setattr(llm_service, "is_default_model", lambda m: not m or m == "opencode/default-m")


@needs_icarus
def test_each_step_shows_its_own_reasoning_and_nothing_leaks_in(scripted, tmp_path):
    llm_service._note_reasoning("LEFT OVER FROM ANOTHER REQUEST ON THIS THREAD")
    events = list(orchestrator.pipeline_events("Design a 4-bit counter", "rs1", IcarusSimulator(workspace=str(tmp_path)),
                                               model="opencode/x"))
    by_stage = {e["stage"]: e for e in events}
    assert by_stage["rtl"]["reasoning"] == "RTL: a 4-bit register with enable."
    assert by_stage["testbench"]["reasoning"] == "TB: count 0..15, then hold with enable low."
    assert "reasoning" not in by_stage["intent"]                          # the leftover was dropped, not attached
    assert not any("LEFT OVER" in json.dumps(e) for e in events)
    assert by_stage["done"]["response"]["result"]["status"] == "PASS"     # the run itself is unchanged
    assert "reasoning" not in by_stage["done"]


def test_closing_the_stream_closes_the_pipeline(monkeypatch, tmp_path):
    closed = {}

    def fake_steps(*a, **k):
        try:
            yield {"stage": "start", "message": "s"}
            yield {"stage": "intent", "message": "i"}
        finally:
            closed["yes"] = True
    monkeypatch.setattr(orchestrator, "_pipeline_steps", fake_steps)
    gen = orchestrator.pipeline_events("p", "id")
    assert next(gen)["stage"] == "start"
    gen.close()
    assert closed.get("yes") is True
