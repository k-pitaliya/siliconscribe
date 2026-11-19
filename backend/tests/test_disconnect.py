"""A browser tab closing mid-run must stop the pipeline from starting further stages.

Measured against a real uvicorn server: after the client hangs up, only the stage already in
flight may finish (a model call cannot be interrupted); no later stage may begin, so a closed
tab cannot keep spending model quota for the rest of the run.
"""
import json
import socket
import threading
import time

import httpx
import uvicorn

import main


def test_no_new_stage_starts_after_the_client_disconnects(monkeypatch):
    began = []
    t0 = time.time()

    def slow_pipeline(**_kw):
        for stage in ("start", "intent", "rtl", "testbench", "simulate", "done"):
            began.append(stage)
            time.sleep(0.6)  # one stage (a model call in real life)
            yield {"stage": stage, "message": stage}

    monkeypatch.setattr(main, "pipeline_events", slow_pipeline)
    monkeypatch.setattr(main, "_check_rate_limit", lambda ip: None)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started, "test server did not start"

        with httpx.stream("POST", f"http://127.0.0.1:{port}/api/design/stream",
                          json={"prompt": "Design a counter"}, timeout=20) as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    assert json.loads(line[5:])["stage"] == "start"
                    break  # the tab is closed here
        time.sleep(3.0)  # long enough for four more stages if the loop kept running
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    # 'start' was delivered; at most the one stage already running may have begun afterwards.
    assert len(began) <= 2, f"stages kept starting after the client left: {began}"
    assert time.time() - t0 < 20
