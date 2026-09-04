import shutil
import pytest
from fastapi.testclient import TestClient

import main

needs_iverilog = pytest.mark.skipif(
    shutil.which("iverilog") is None, reason="iverilog not installed"
)

client = TestClient(main.app)


def test_root_reports_offline():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["offline"] is True
    assert body["provider"] == "offline"


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "simulator" in body


@needs_iverilog
def test_design_run_endpoint():
    r = client.post("/api/design/run", json={"prompt": "Design a 4-bit ALU", "max_iterations": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PASS"
    assert body["waveform"]["signals"]
    assert body["schematic"]["module_name"] == "alu_4bit"


@needs_iverilog
def test_stream_endpoint_emits_done():
    with client.stream("POST", "/api/design/stream",
                       json={"prompt": "Design a counter", "max_iterations": 2}) as resp:
        assert resp.status_code == 200
        text = "".join(resp.iter_text())
    assert '"stage": "done"' in text
    assert '"stage": "intent"' in text


# --- Security regression tests ---


def test_rate_limit_enforced():
    """Regression: exceeding rate limit must return 429."""
    # Temporarily lower the limit for this test.
    old_max = main.RATE_LIMIT_MAX_REQUESTS
    old_window = main.RATE_LIMIT_WINDOW
    main.RATE_LIMIT_MAX_REQUESTS = 3
    main.RATE_LIMIT_WINDOW = 60
    try:
        ip = "test_rate_limit_client"
        main._rate_log[ip] = []
        for _ in range(3):
            client.post("/api/design/run",
                        json={"prompt": "Design a counter", "max_iterations": 1})
        r = client.post("/api/design/run",
                        json={"prompt": "Design a counter", "max_iterations": 1})
        assert r.status_code == 429
        assert "rate limit" in r.json()["detail"].lower()
    finally:
        main.RATE_LIMIT_MAX_REQUESTS = old_max
        main.RATE_LIMIT_WINDOW = old_window
        main._rate_log.pop("test_rate_limit_client", None)
