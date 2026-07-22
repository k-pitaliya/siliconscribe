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


def test_artifact_path_traversal_blocked():
    # Disallowed filename
    r = client.get("/api/artifacts/abcd1234/../../../etc/passwd")
    assert r.status_code in (400, 404)
    # Disallowed via filename allowlist
    r2 = client.get("/api/artifacts/abcd1234/secret.txt")
    assert r2.status_code == 400


def test_invalid_design_id_rejected():
    r = client.get("/api/artifacts/..%2f..%2fetc/design.vcd")
    assert r.status_code in (400, 404)


# --- Security regression tests ---


def test_design_id_length_cap():
    """Regression: design IDs longer than 64 chars must be rejected."""
    long_id = "a" * 65
    r = client.get(f"/api/artifacts/{long_id}/design.vcd")
    assert r.status_code == 400
    assert "too long" in r.json()["detail"].lower()


def test_design_id_special_chars_rejected():
    """Regression: design IDs with path traversal chars must be rejected."""
    for bad_id in ["abc..etc..passwd", "abc;rm -rf", "abc%00null"]:
        r = client.get(f"/api/artifacts/{bad_id}/design.vcd")
        assert r.status_code == 400, f"Expected 400 for id={bad_id!r}, got {r.status_code}"


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
