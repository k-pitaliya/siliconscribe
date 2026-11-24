"""The debugging agent: waveform queries, code search, the JSON tool loop, fix verification, the no-AI path, the API."""

import json
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

import agent
import main
import offline_designs as od
import wave_query
from simulator import IcarusSimulator
from wave_query import fmt_value, parse_value

needs_icarus = pytest.mark.skipif(shutil.which("iverilog") is None, reason="Icarus Verilog not installed")
COUNTER = od.get_design("counter")


# ---------------------------------------------------------------- value parsing / formatting
@pytest.mark.parametrize("text,width,bits", [
    ("9", 4, "1001"), ("4'h9", 4, "1001"), ("0x9", 4, "1001"), ("4'b1001", 4, "1001"), ("'d9", 4, "1001"),
    ("x", 4, "xxxx"), ("z", 1, "z"), ("1", 1, "1"), ("8'hff", 8, "11111111"), ("-1", 4, "1111"), ("4'b10x1", 4, "10x1"),
])
def test_parse_value(text, width, bits):
    assert parse_value(text, width) == bits


@pytest.mark.parametrize("text", ["", "banana", "4'hzz9g", "4'b102"])
def test_parse_value_rejects_garbage(text):
    assert parse_value(text, 4) is None


def test_fmt_value():
    assert fmt_value("1001", 4) == "4'h9 (9)"
    assert fmt_value("10x1", 4) == "4'hx"
    assert fmt_value("1", 1) == "1"
    assert fmt_value(None, 4) == "no value yet"


# ---------------------------------------------------------------- a real failing run
@pytest.fixture(scope="module")
def buggy_run():
    if shutil.which("iverilog") is None:
        pytest.skip("Icarus Verilog not installed")
    sim = IcarusSimulator(workspace=tempfile.mkdtemp(prefix="ss_agent_"))
    res = sim.simulate("agent_buggy", COUNTER["rtl_buggy"], COUNTER["tb"], timeout=30)
    assert res.status == "FAIL"
    db = wave_query.load(res.waveform_file)
    assert db is not None

    def simulate(rtl, tb):
        return sim.simulate("agent_fix", rtl, tb, timeout=30)
    return db, res, simulate


def _tools(buggy_run):
    db, res, simulate = buggy_run
    return agent.Toolbox(db, res, COUNTER["rtl_buggy"], COUNTER["tb"], simulate=simulate)


def test_resolve_prefers_the_design_copy(buggy_run):
    db = buggy_run[0]
    sig, others = db.resolve("count")
    assert sig.path == "testbench.dut.count"
    assert "testbench.count" in others
    assert db.resolve("testbench.count")[0].path == "testbench.count"     # an exact path is taken as given
    assert db.resolve("nonexistent")[0] is None


def test_value_before_and_after_an_edge(buggy_run):
    db = buggy_run[0]
    count = db.resolve("count")[0]
    clk = db.clocks()[0]
    first_enabled = db.edges(clk, 0, db.end_time, "posedge")[1]
    assert count.value_before(first_enabled) == "0000"
    assert count.value_at(first_enabled) == "0010"       # the bug: +2 instead of +1


def test_tools_show_the_bug(buggy_run):
    t = _tools(buggy_run)
    assert "expected 1 got 2" in t.failing_checks()
    table = t.cycle_table(["enable", "count"], 0, 50)
    assert "4'h0 (0) -> 4'h2 (2)" in table
    assert "never held 4'h1" in t.find_value("count", "1")
    drivers = t.drivers("count")
    assert "rtl line 14" in drivers and "count + 2'd2" in drivers
    assert "instance port" in drivers and "task chk" not in drivers     # an instance is not inside the task above it
    assert "@15ns -> 4'h2 (2)" in t.changes("count", 0, 20)


def test_tool_errors_go_back_to_the_model(buggy_run):
    t = _tools(buggy_run)
    with pytest.raises(agent.ToolError, match="No signal named"):
        t.call("changes", {"signal": "nope"})
    with pytest.raises(agent.ToolError, match="Unknown tool"):
        t.call("rm_rf", {})
    with pytest.raises(agent.ToolError, match="Bad arguments"):
        t.call("drivers", {"signal": "count", "extra": 1})
    with pytest.raises(agent.ToolError, match="nanoseconds"):
        t.call("values_at", {"t_ns": "soon"})
    assert "nope: No signal named" in t.values_at(10, ["nope", "count"])   # one bad name does not lose the others


def test_test_fix_is_limited(buggy_run):
    t = _tools(buggy_run)
    for _ in range(agent.MAX_FIX_TESTS):
        assert "Candidate fix: PASS" in t.test_fix("rtl", COUNTER["rtl"])
    with pytest.raises(agent.ToolError, match="already used"):
        t.test_fix("rtl", COUNTER["rtl"])


def test_find_drivers_ignores_comparisons():
    rtl = "module m(input a, output reg y, output reg [3:0] c);\n" \
          "always @* begin\n  if (c <= 4'd3) y = 1'b1;\n  else y = (c == 4'd9);\nend\nendmodule\n"
    assert find(rtl, "c") == []
    assert [h["line"] for h in find(rtl, "y")] == [3, 4]


def find(rtl, name):
    return agent.find_drivers(name, rtl, "")


# ---------------------------------------------------------------- the loop, with a scripted model
def _script(*replies):
    seen = []
    it = iter(replies)

    def chat(system, user):
        seen.append(user)
        r = next(it)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)
    return chat, seen


def test_loop_calls_tools_then_verifies_the_fix(buggy_run):
    chat, seen = _script(
        {"thought": "look at the first cycles", "tool": "cycle_table", "args": {"signals": ["count"], "from_ns": 0, "to_ns": 50}},
        "Sure! ```json\n{\"tool\": \"drivers\", \"args\": {\"signal\": \"count\"}}\n```",
        {"answer": "`count` goes 0 -> 2 @15ns; line 14 adds 2.", "suspect": "design", "confidence": "high",
         "fix": {"file": "rtl", "code": COUNTER["rtl"]}},
    )
    events = list(agent.ask("why does count skip 1?", _tools(buggy_run), chat=chat))
    assert [e["type"] for e in events] == ["tool", "tool", "answer"]
    assert "4'h0 (0) -> 4'h2 (2)" in events[0]["result"]
    assert "Result:" in seen[2] and "count + 2'd2" in seen[2]            # the model saw both tool results
    ans = events[-1]
    assert ans["fix"]["status"] == "PASS" and ans["fix"]["fail_count"] == 0
    assert ans["suspect"] == "design" and ans["rule_based"] is False


def test_a_wrong_fix_is_shown_failing(buggy_run):
    still_buggy = COUNTER["rtl_buggy"].replace("2'd2", "2'd3")
    chat, _ = _script({"tool": "changes", "args": {"signal": "count", "from_ns": 0, "to_ns": 30}},
                      {"answer": "Fixed it.", "fix": {"file": "rtl", "code": still_buggy}, "confidence": "high"})
    ans = list(agent.ask("fix it", _tools(buggy_run), chat=chat))[-1]
    assert ans["fix"]["status"] == "FAIL"          # the model's claim is not what the user sees: the re-simulation is


def test_unchanged_fix_is_dropped(buggy_run):
    chat, _ = _script({"tool": "values_at", "args": {"t_ns": 20}}, {"answer": "Looks fine.", "fix": {"file": "rtl", "code": COUNTER["rtl_buggy"]}})
    assert list(agent.ask("q", _tools(buggy_run), chat=chat))[-1]["fix"] is None


def test_model_failure_falls_back_to_labelled_evidence(buggy_run):
    chat, _ = _script(RuntimeError("LLM_UPSTREAM: 429 FreeUsageLimitError"))
    ans = list(agent.ask("q", _tools(buggy_run), chat=chat))[-1]
    assert ans["rule_based"] is True
    assert "usage limit" in ans["text"] and "not an AI diagnosis" in ans["text"]
    assert "count_up_to_1" in ans["text"]


def test_two_format_slips_return_unchecked_text(buggy_run):
    chat, seen = _script("I think it is the adder.", "Really, the adder.")
    ans = list(agent.ask("q", _tools(buggy_run), chat=chat))[-1]
    assert ans["text"] == "Really, the adder." and "unchecked" in ans["note"]
    assert "not one JSON object" in seen[1]


def test_step_limit_ends_with_an_answer(buggy_run):
    chat, _ = _script(*[{"tool": "failing_checks", "args": {}}] * agent.MAX_STEPS)
    events = list(agent.ask("q", _tools(buggy_run), chat=chat))
    assert len(events) == agent.MAX_STEPS + 1
    assert events[-1]["type"] == "answer" and events[-1]["rule_based"] is True


def test_bad_tool_call_is_reported_and_the_loop_continues(buggy_run):
    chat, seen = _script({"tool": "values_at", "args": {"t_ns": -5}}, {"answer": "done"}, {"answer": "done"})
    events = list(agent.ask("q", _tools(buggy_run), chat=chat))
    assert events[0]["ok"] is False and "negative" in events[0]["result"]
    assert "Tool error" in seen[1]


def test_test_fix_code_is_not_echoed_in_events(buggy_run):
    chat, seen = _script({"tool": "test_fix", "args": {"file": "rtl", "code": COUNTER["rtl"]}}, {"answer": "ok"})
    events = list(agent.ask("q", _tools(buggy_run), chat=chat))
    assert events[0]["args"]["code"].startswith("<") and "Candidate fix: PASS" in events[0]["result"]
    assert "always @(posedge clk" not in seen[1].split("Your steps so far")[1]


def test_history_is_in_the_prompt(buggy_run):
    chat, seen = _script({"answer": "ok"}, {"answer": "ok"})
    list(agent.ask("and now?", _tools(buggy_run), history=[{"question": "first q", "answer": "first a"}], chat=chat))
    assert "User: first q" in seen[0] and "You: first a" in seen[0]


def test_no_waveform_still_answers():
    from models import SimError, SimulationResult
    res = SimulationResult(status="ERROR", module_name="", errors=[SimError(message="design.sv:3: syntax error")])
    t = agent.Toolbox(None, res, "module m; endmodule", "module testbench; endmodule", simulate=lambda r, tb: res)
    with pytest.raises(agent.ToolError, match="no waveform"):
        t.changes("x")
    ans = agent.rule_based_answer(t, "No AI.")
    assert "syntax error" in ans["text"]
    assert "Signals in the waveform" not in agent.overview(t) and "syntax error" in agent.overview(t)


# ---------------------------------------------------------------- the API (offline mode in the test suite)
client = TestClient(main.app)


def _events(body):
    main._rate_log.clear()
    with client.stream("POST", "/api/agent/ask", json=body) as r:
        assert r.status_code == 200
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


@needs_icarus
def test_api_offline_gives_rule_based_evidence():
    ev = _events({"rtl_code": COUNTER["rtl_buggy"], "testbench_code": COUNTER["tb"], "question": "why fail?"})
    assert [e["type"] for e in ev] == ["status", "run", "answer"]
    assert ev[1]["result"]["status"] == "FAIL" and ev[1]["result"]["waveform"]["signals"]
    assert ev[2]["rule_based"] is True and ev[2]["model"] is None
    assert "count_up_to_1" in ev[2]["text"]


@needs_icarus
def test_api_sandbox_still_applies():
    bad_tb = COUNTER["tb"].replace("initial begin", 'initial begin $system("ls");', 1)
    ev = _events({"rtl_code": COUNTER["rtl"], "testbench_code": bad_tb, "question": "q"})
    assert ev[1]["result"]["status"] == "ERROR"
    assert any("system" in e["message"].lower() for e in ev[1]["result"]["errors"])
    assert ev[-1]["type"] == "answer"


@pytest.mark.parametrize("body", [
    {"rtl_code": "x", "testbench_code": "y", "question": ""},
    {"rtl_code": "x", "testbench_code": "y", "question": "q", "model": "--flag"},
    {"rtl_code": "x" * 50001, "testbench_code": "y", "question": "q"},
    {"rtl_code": "x", "testbench_code": "y", "question": "q", "history": [{"question": "a", "answer": "b"}] * 7},
])
def test_api_rejects_bad_requests(body):
    main._rate_log.clear()
    assert client.post("/api/agent/ask", json=body).status_code == 422


def test_an_answer_without_waveform_evidence_is_sent_back_once(buggy_run):
    chat, seen = _script({"answer": "It adds 2."}, {"tool": "cycle_table", "args": {"signals": ["count"], "from_ns": 0, "to_ns": 30}},
                         {"answer": "It adds 2 @15ns."})
    events = list(agent.ask("q", _tools(buggy_run), chat=chat))
    assert [e["type"] for e in events] == ["tool", "answer"] and events[-1]["text"] == "It adds 2 @15ns."
    assert "at least one waveform query" in seen[1]


def test_a_second_unsupported_answer_is_accepted(buggy_run):
    chat, seen = _script({"answer": "first"}, {"answer": "second"})
    events = list(agent.ask("q", _tools(buggy_run), chat=chat))
    assert events[-1]["text"] == "second" and len(seen) == 2


def test_a_failed_waveform_query_does_not_count_as_evidence(buggy_run):
    chat, seen = _script({"tool": "changes", "args": {"signal": "nope"}}, {"answer": "a"}, {"answer": "b"})
    assert list(agent.ask("q", _tools(buggy_run), chat=chat))[-1]["text"] == "b"


@pytest.mark.parametrize("err,expected", [
    ("LLM_UPSTREAM:PermissionDeniedError: model=@cf/zai-org/glm-5.3 err=Error code: 403", "needs a paid plan"),
    ('LLM_UPSTREAM:OpenCodeError: {"message": "Upstream request failed: Model is unavailable.", "status": 400}',
     "not serving this model"),
    ('LLM_UPSTREAM:OpenCodeError: {"type": "provider.auth", "message": "An active OpenCode Go subscription is required"}',
     "paid plan or subscription"),
    ("LLM_UPSTREAM:Timeout: opencode model=x after 90s", "did not answer in time"),
])
def test_a_failed_model_is_named_with_a_plain_reason(buggy_run, err, expected):
    chat, _ = _script(RuntimeError(err))
    ans = list(agent.ask("q", _tools(buggy_run), model="@cf/zai-org/glm-5.3", chat=chat))[-1]
    assert ans["rule_based"] is True
    assert "@cf/zai-org/glm-5.3 could not be used" in ans["text"] and expected in ans["text"]
    assert "Pick another model" in ans["text"]
