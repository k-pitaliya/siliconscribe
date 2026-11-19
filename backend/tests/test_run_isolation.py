"""Run isolation (self-review findings, 19 Nov 2026, all reproduced before the fix).

* Two concurrent runs of the SAME design_id overwrote each other's files: false verdicts in 25 of 25 tries.
* A testbench that dumps to its own file name left the previous run's design.vcd in place, and it was reported.
* A compile timeout killed only the `iverilog` driver; its `ivl` child kept running at 100% CPU.
"""
import shutil
import subprocess
import threading
import time

import pytest

import simulator
from simulator import IcarusSimulator

needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog not installed")

RTL = "module c(output [3:0] y); assign y = 4'd{v}; endmodule"
TB = """module testbench; wire [3:0] y; integer p = 0, f = 0; c dut(.y(y));
initial begin {dump} #1; repeat (200) begin #1; if (y === 4'd1) p = p + 1; else f = f + 1; end
  $display("Passed: %0d", p); $display("Failed: %0d", f); $finish; end endmodule"""


@needs_iverilog
def test_concurrent_runs_of_one_design_id_do_not_mix_their_files(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    for _ in range(6):
        out = {}

        def go(name, v):
            out[name] = sim.simulate("shared1", RTL.format(v=v), TB.format(dump=""), timeout=20).status

        threads = [threading.Thread(target=go, args=("good", 1)), threading.Thread(target=go, args=("bad", 2))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert out == {"good": "PASS", "bad": "FAIL"}, out


@needs_iverilog
def test_a_previous_runs_waveform_is_never_reported_for_a_new_run(tmp_path):
    sim = IcarusSimulator(workspace=str(tmp_path))
    first = sim.simulate("stale1", RTL.format(v=1), TB.format(dump=""), timeout=20)
    assert first.status == "PASS" and first.waveform_file and first.waveform_file.endswith("design.vcd")
    second = sim.simulate("stale1", RTL.format(v=1), TB.format(dump='$dumpfile("mine.vcd"); $dumpvars(0, testbench);'),
                          timeout=20)
    assert second.status == "PASS"
    assert not (tmp_path / "stale1" / "design.vcd").exists()
    assert not (second.waveform_file or "").endswith("design.vcd")


def test_a_timed_out_tool_is_killed_with_all_its_children(tmp_path):
    marker = tmp_path / "child_alive"
    # The shell starts a grandchild that would keep touching the marker after the parent is killed.
    script = f"(while true; do touch {marker}; sleep 0.05; done) & wait"
    with pytest.raises(subprocess.TimeoutExpired):
        simulator.run_tool(["/bin/sh", "-c", script], 0.3)
    time.sleep(0.2)
    marker.unlink(missing_ok=True)
    time.sleep(0.3)
    assert not marker.exists(), "a child of the timed-out tool is still running"


def test_cleanup_keeps_a_folder_whose_file_was_just_rewritten_and_ignores_foreign_folders(tmp_path):
    """Self-review findings: the age came from the folder's own mtime (rewriting a file does not change it), and any old
    sub-folder of the workspace was deleted, whatever it was."""
    import os

    from cleanup import cleanup_old_workspaces
    old = time.time() - 30 * 3600
    active = tmp_path / "abc123"
    active.mkdir()
    (active / "design.sv").write_text("module m; endmodule")     # rewritten just now
    os.utime(active, (old, old))
    stale = tmp_path / "def456"
    stale.mkdir()
    (stale / "design.sv").write_text("x")
    os.utime(stale / "design.sv", (old, old))
    os.utime(stale, (old, old))
    foreign = tmp_path / "My Notes.backup"
    foreign.mkdir()
    os.utime(foreign, (old, old))
    assert cleanup_old_workspaces(str(tmp_path), ttl_hours=24) == 1
    assert active.exists() and foreign.exists() and not stale.exists()
