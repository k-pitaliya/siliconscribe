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
