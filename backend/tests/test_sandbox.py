"""Sandbox policy: untrusted Verilog must not reach files outside the workspace.

Found during the final review: a testbench could use $fopen/$fgets/$fwrite to
read or write any path the server process could reach, and the contents came
back in the API response. These tests pin the fix (defence in depth: a static
policy check, a scrubbed child environment and an output-size cap).
"""

import shutil

import pytest

from simulator import IcarusSimulator, clean_env, sandbox_violations

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog not installed"
)

RTL = "module dut(input a, output y); assign y = a; endmodule\n"


def _tb(body: str) -> str:
    return (
        "module testbench;\n  reg a; wire y;\n  dut d(.a(a), .y(y));\n"
        "  initial begin\n" + body + "\n"
        '    $display("Passed: 1"); $display("Failed: 0"); $display("ALL TESTS PASSED");\n'
        "    $finish;\n  end\nendmodule\n"
    )


@pytest.mark.parametrize("body", [
    'fd = $fopen("/etc/passwd", "r");',
    '$fwrite(fd, "x");',
    '$fdisplay(fd, "x");',
    '$fgets(line, fd);',
    '$fscanf(fd, "%d", x);',
    '$readmemh("/etc/passwd", mem);',
    '$system("id");',
    '$display("//"); $fopen("/etc/passwd", "r");',   # a "//" inside a string must not hide the call
    '$dumpfile("../../outside.vcd");',
    '$dumpfile("/tmp/x.vcd");',
    '$dumpfile(name);',
    '`include "/etc/passwd"',
    '`define F(a) $f``a',
])
def test_policy_rejects_dangerous_constructs(body):
    assert sandbox_violations(RTL, _tb(body)), f"policy missed: {body}"


def test_policy_allows_normal_testbench_and_plain_dumpfile():
    ok = _tb('$dumpfile("design.vcd"); $dumpvars(0, testbench); a = 0; #5;')
    assert sandbox_violations(RTL, ok) == []


def test_policy_allows_curated_designs():
    import offline_designs as od
    for key in ("counter", "alu", "alu8", "adder", "mux"):
        d = od.get_design(key)
        assert sandbox_violations(d["rtl"], d["tb"]) == [], key


def test_clean_env_drops_secrets(monkeypatch):
    for k in ("OPENCODE_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY", "ADMIN_TOKEN"):
        monkeypatch.setenv(k, "super-secret")
    env = clean_env()
    assert "PATH" in env
    assert not any("KEY" in k or "TOKEN" in k for k in env)


@needs_iverilog
def test_file_read_and_write_blocked_end_to_end(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("FAKE_API_KEY=sk-PLANTED-SECRET\n")
    outfile = tmp_path / "written_by_sim.txt"
    tb = _tb(
        f'fd = $fopen("{secret}", "r"); n = $fgets(line, fd); $display("LEAK: %0s", line);\n'
        f'    fo = $fopen("{outfile}", "w"); $fwrite(fo, "arbitrary write");'
    ).replace("reg a; wire y;", "reg a; wire y; integer fd, fo, n; reg [8*80-1:0] line;")

    sim = IcarusSimulator(workspace=str(tmp_path / "ws"))
    res = sim.simulate("sandbox1", RTL, tb, timeout=10)

    assert res.status == "ERROR"
    assert "sandbox policy" in res.log_excerpt.lower()
    assert "PLANTED-SECRET" not in res.log_excerpt
    assert not outfile.exists(), "testbench managed to write outside the workspace"


@needs_iverilog
def test_runaway_output_is_capped(tmp_path):
    tb = (
        "module testbench;\n  reg a; wire y;\n  dut d(.a(a), .y(y));\n"
        '  initial begin forever $display("spam spam spam spam spam spam spam spam"); end\n'
        "endmodule\n"
    )
    sim = IcarusSimulator(workspace=str(tmp_path))
    res = sim.simulate("spam1", RTL, tb, timeout=6)
    assert res.status != "PASS"
    log = tmp_path / "spam1" / "transcript.log"
    assert log.exists()
    assert log.stat().st_size <= 140 * 1024 * 1024, "output size cap not enforced"


def test_simultaneous_simulations_are_capped_and_the_slot_is_always_released(tmp_path, monkeypatch):
    """A burst of requests must queue, not all run at once; a crashing job must not leak its slot."""
    import threading
    import time
    import simulator as sim_mod
    from models import SimulationResult

    monkeypatch.setattr(sim_mod, "_SIM_SLOTS", threading.BoundedSemaphore(2))
    sim = IcarusSimulator(workspace=str(tmp_path))
    running = peak = 0
    lock = threading.Lock()

    def fake_compile(self, rtl_file, tb_file):
        return True, ""

    def fake_run(self, design_id, top_module="testbench", timeout=60, dut_instances=None):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.15)
        with lock:
            running -= 1
        if design_id == "boom":
            raise RuntimeError("simulated crash")
        return SimulationResult(status="PASS", module_name="m")

    monkeypatch.setattr(IcarusSimulator, "compile", fake_compile)
    monkeypatch.setattr(IcarusSimulator, "run", fake_run)
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(sim.simulate(f"d{i}", "module m; endmodule", "module testbench; endmodule")))
               for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 6 and all(r.status == "PASS" for r in results)
    assert peak == 2, f"expected at most 2 concurrent simulations, saw {peak}"

    with pytest.raises(RuntimeError):
        sim.simulate("boom", "module m; endmodule", "module testbench; endmodule")
    # both slots are free again: two more jobs can still start without waiting forever
    assert sim.simulate("again", "module m; endmodule", "module testbench; endmodule").status == "PASS"
