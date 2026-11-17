"""Signals that stop the app from overstating its evidence or giving up too early.

Found while testing free models live: a PASS backed by only 13 executed checks
looked identical to a PASS backed by 100+, and a single transient 503 from the
provider ended the run after one retry.
"""

from types import SimpleNamespace

from models import PortSpec, RTLDesignSpec
from orchestrator import MIN_EXECUTED_CHECKS, weak_verification_note


def _spec(*ports):
    return RTLDesignSpec(module_name="dut", ports=[PortSpec(**p) for p in ports], behavior="x")


def _res(status, n):
    return SimpleNamespace(status=status, test_count=n)


SEQ = _spec(dict(name="clk", direction="input", width=1),
            dict(name="rst_n", direction="input", width=1),
            dict(name="d", direction="input", width=8),
            dict(name="q", direction="output", width=8))
ADDER = _spec(dict(name="a", direction="input", width=1),
              dict(name="b", direction="input", width=1),
              dict(name="cin", direction="input", width=1),
              dict(name="sum", direction="output", width=1))


def test_few_checks_on_a_sequential_design_is_flagged():
    note = weak_verification_note(SEQ, _res("PASS", 13))
    assert note and "13" in note and str(MIN_EXECUTED_CHECKS) in note


def test_enough_checks_is_not_flagged():
    assert weak_verification_note(SEQ, _res("PASS", MIN_EXECUTED_CHECKS)) is None


def test_exhaustive_tiny_block_is_not_flagged():
    # 3 data input bits -> 8 combinations; 8 checks IS exhaustive, not weak.
    assert weak_verification_note(ADDER, _res("PASS", 8)) is None
    assert weak_verification_note(ADDER, _res("PASS", 3)) is not None


def test_only_a_pass_can_be_weak():
    assert weak_verification_note(SEQ, _res("FAIL", 2)) is None
    assert weak_verification_note(SEQ, _res("ERROR", 0)) is None


def test_clock_and_reset_do_not_count_as_data_inputs():
    only_clk_rst = _spec(dict(name="clk", direction="input", width=1),
                         dict(name="reset", direction="input", width=1),
                         dict(name="q", direction="output", width=1))
    # No data input bits -> floor is 2**0 = 1 check.
    assert weak_verification_note(only_clk_rst, _res("PASS", 1)) is None


def test_provider_retries_transient_errors_with_backoff(monkeypatch):
    from llm_service import OpenAIProvider
    monkeypatch.setenv("LLM_MAX_RETRIES", "4")
    prov = OpenAIProvider(api_key="k", base_url="http://127.0.0.1:9/v1", model="m")
    assert prov.client.max_retries == 4
    monkeypatch.delenv("LLM_MAX_RETRIES")
    assert OpenAIProvider(api_key="k", base_url="http://127.0.0.1:9/v1", model="m").client.max_retries == 3


# ------------------------------------------------------------------ repair-loop guards
import llm_service  # noqa: E402
import offline_designs as od  # noqa: E402
from orchestrator import _instantiates_dut, _tb_check_count, _tb_problems, pipeline_events  # noqa: E402
from simulator import IcarusSimulator  # noqa: E402


def test_comments_strings_and_initialisers_are_not_checks():
    assert _tb_check_count("integer fail_count = 0; // fail_count++ $error\n$display(\"$error fail_count++\");") == 0
    assert _tb_check_count("if (a !== b) fail_count = fail_count + 1;") == 1
    assert _tb_check_count("if (a !== b) errors = errors + 1;") == 1
    assert _tb_check_count('chk("reset","x", 1, 1);') == 1


def test_a_comment_mentioning_the_dut_is_not_an_instance():
    tb = "module testbench; // uses counter\n initial $finish; endmodule"
    assert not _instantiates_dut(tb, "counter")
    assert _instantiates_dut("module testbench; counter #(4) dut(.clk(c)); endmodule", "counter")
    assert _instantiates_dut("module testbench; counter dut (.clk(c)); endmodule", "counter")
    assert "it does not instantiate the DUT module 'counter'" in _tb_problems(tb, "counter")


def _run_with_fix(tmp_path, monkeypatch, fix_rtl, fix_tb):
    def _fix(self, rtl_code, tb_code, log_excerpt, model=None, reasoning_effort=None, spec=None):
        return {"rtl_code": fix_rtl, "testbench_code": fix_tb, "fix_summary": "stub", "fix_type": "test"}
    monkeypatch.setattr(llm_service.OfflineProvider, "fix_design", _fix)
    sim = IcarusSimulator(workspace=str(tmp_path))
    events = list(pipeline_events("Design a buggy 4-bit counter", "g1", sim, max_iterations=2))
    return events, next(e for e in events if e["stage"] == "done")["response"]


def test_fixer_rtl_that_is_not_a_complete_module_is_rejected(tmp_path, monkeypatch):
    events, resp = _run_with_fix(tmp_path, monkeypatch, "assign x = 1;", od.get_design("counter")["tb"])
    notes = " ".join(e.get("message", "") for e in events if e["stage"] == "fix")
    assert "RTL change rejected" in notes
    assert "assign x = 1;" not in resp["rtl_code"]


def test_fixer_testbench_that_never_instantiates_the_dut_is_rejected(tmp_path, monkeypatch):
    tb = ("module testbench; integer fail_count = 0;\n initial begin "
          'if (1\'b0) fail_count = fail_count + 1; $display("Passed: 30"); $display("Failed: 0"); $finish; end endmodule\n')
    events, resp = _run_with_fix(tmp_path, monkeypatch, od.get_design("counter")["rtl"], tb)
    notes = " ".join(e.get("message", "") for e in events if e["stage"] == "fix")
    assert "Testbench change rejected" in notes and "does not instantiate" in notes
    assert resp["testbench_code"] == od.get_design("counter")["tb"]


def test_a_relaxed_testbench_that_passes_a_still_wrong_design_is_flagged(tmp_path, monkeypatch):
    """The fixer cannot fix the RTL, so it rewrites every comparison to if (1'b1)."""
    # at least as many check SITES as the original testbench, or the anti-cheat count guard stops it first
    always_true = "if (1'b1) pass_count = pass_count + 1; else fail_count = fail_count + 1;\n" * 20
    tb = ("`timescale 1ns/1ps\nmodule testbench;\n reg clk, rst_n, enable; wire [3:0] count;\n"
          " integer pass_count = 0; integer fail_count = 0;\n"
          " counter #(4) dut(.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));\n"
          " initial begin clk = 0; rst_n = 1; enable = 1; #10;\n" + always_true +
          ' $display("Passed: %0d", pass_count); $display("Failed: %0d", fail_count); $finish; end\nendmodule\n')
    _, resp = _run_with_fix(tmp_path, monkeypatch, od.get_design("counter")["rtl_buggy"], tb)
    assert resp["status"] == "PASS"                       # the relaxed testbench is satisfied...
    assert "ORIGINAL testbench" in (resp["verification_warning"] or "")   # ...but the app says so


# ------------------------------------------------------------------ rate limiter, CORS, Re-run
def test_forwarded_headers_are_ignored_unless_a_trusted_proxy_is_configured(monkeypatch):
    from types import SimpleNamespace
    import main
    req = SimpleNamespace(headers={"x-forwarded-for": "6.6.6.6", "cf-connecting-ip": "7.7.7.7"},
                          client=SimpleNamespace(host="10.0.0.9"))
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    assert main._get_client_ip(req) == "10.0.0.9"          # a spoofed header buys nothing
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    assert main._get_client_ip(req) == "6.6.6.6"           # behind a trusted proxy it is honoured


def test_rerun_refuses_a_pass_from_a_testbench_with_no_checks(monkeypatch):
    from fastapi.testclient import TestClient
    import main
    d = od.get_design("counter")
    tb = ("`timescale 1ns/1ps\nmodule testbench; reg clk, rst_n, enable; wire [3:0] count;\n"
          " counter #(4) dut(.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));\n"
          ' initial begin clk = 0; rst_n = 1; enable = 0; #10; $display("Passed: 5"); '
          '$display("Failed: 0"); $display("ALL TESTS PASSED"); $finish; end\nendmodule\n')
    assert _tb_check_count(tb) == 0
    monkeypatch.setattr(main, "_check_rate_limit", lambda ip: None)
    r = TestClient(main.app).post("/api/simulation/run",
                                  json={"design_id": "rerun1", "rtl_code": d["rtl"], "testbench_code": tb})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ERROR"
    assert any("no self-checks" in e["message"] for e in body["errors"])


def test_malformed_json_error_text_is_not_mistaken_for_a_provider_outage():
    from orchestrator import _is_upstream_error
    assert not _is_upstream_error(Exception("Expecting ',' delimiter: line 1 column 12 (char 504)"))
    assert not _is_upstream_error(Exception("output was truncated (finish_reason=length, reasoning_tokens=2500)"))
    assert _is_upstream_error(llm_service.LLMUpstreamError("LLM_UPSTREAM:APIConnectionError: boom"))
    assert _is_upstream_error(Exception("Connection error."))


def test_multi_module_replies_keep_every_module():
    from llm_service import _strip_code_fence
    from orchestrator import _has_complete_module
    text = ("Here you go:\n```verilog\nmodule full_adder(input a, b, cin, output s, co);\n"
            " assign {co, s} = a + b + cin;\nendmodule\n\nmodule ripple4(input [3:0] a, b, output [4:0] s);\n"
            " wire c; full_adder fa(a[0], b[0], 1'b0, s[0], c);\nendmodule\n```\nHope that helps!")
    out = _strip_code_fence(text)
    assert _has_complete_module(out, "full_adder") and _has_complete_module(out, "ripple4")
    assert "Hope that helps" not in out
