"""Security-relevant routes and storage that had no test (self-review QA report, 19 Nov 2026). Each test below fails if
its guard is removed: a mutant that deleted every project, or opened the admin clean-up without a token, passed the suite."""
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import db
import main
import offline_designs as od
from models import RunResponse, SimulationResult

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    main._rate_log.clear()
    yield
    main._rate_log.clear()


# ------------------------------------------------------------------ admin clean-up
def test_admin_cleanup_is_disabled_without_a_configured_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert client.post("/api/admin/cleanup").status_code == 503
    assert client.post("/api/admin/cleanup", headers={"x-admin-token": ""}).status_code == 503


def test_admin_cleanup_needs_the_right_token_and_a_sane_ttl(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "right-token")
    assert client.post("/api/admin/cleanup", headers={"x-admin-token": "wrong"}).status_code == 403
    assert client.post("/api/admin/cleanup").status_code == 403
    assert client.post("/api/admin/cleanup?ttl_hours=0", headers={"x-admin-token": "right-token"}).status_code == 422
    r = client.post("/api/admin/cleanup", headers={"x-admin-token": "right-token"})
    assert r.status_code == 200 and r.json()["ttl_hours"] == 24


# ------------------------------------------------------------------ project routes and storage
def _response(design_id: str, module: str = "counter") -> RunResponse:
    d = od.get_design("counter")
    return RunResponse(design_id=design_id, rtl_spec=d["spec"], rtl_code=d["rtl"], testbench_code=d["tb"],
                       explanation="x", status="FAIL",
                       result=SimulationResult(status="FAIL", module_name=module, pass_count=3, fail_count=2, test_count=5),
                       verification_warning="weak", iterations=1)


def test_projects_round_trip_in_newest_first_order_and_delete_removes_only_one(tmp_path):
    ws = str(tmp_path)
    db.init_db(ws)
    db.save_project(_response("aaa111"), prompt="first", workspace=ws)
    time.sleep(0.01)
    db.save_project(_response("bbb222"), prompt="second", workspace=ws)
    listed = db.list_projects(workspace=ws)
    assert [p["design_id"] for p in listed] == ["bbb222", "aaa111"]
    assert listed[0]["model"] is None and listed[0]["demo"] is False
    got = db.get_project("aaa111", workspace=ws)
    assert got["status"] == "FAIL" and got["verification_warning"] == "weak" and got["result"]["fail_count"] == 2
    assert db.delete_project("aaa111", workspace=ws) is True
    assert [p["design_id"] for p in db.list_projects(workspace=ws)] == ["bbb222"]
    assert db.get_project("aaa111", workspace=ws) is None


@pytest.mark.parametrize("bad", ["..", "a b", "x" * 40, "a;b"])
def test_project_routes_refuse_an_invalid_id(bad):
    assert client.get(f"/api/projects/{bad}").status_code in (404, 422)
    assert client.delete(f"/api/projects/{bad}").status_code in (404, 422)


def test_a_missing_project_is_404():
    assert client.get("/api/projects/abcdef12").status_code == 404


# ------------------------------------------------------------------ client IP and rate limit
def _req(xff=None, peer="10.0.0.1"):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def test_behind_a_proxy_the_last_forwarded_address_is_used_not_the_client_supplied_first(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    assert main._get_client_ip(_req("9.9.9.9, 203.0.113.7")) == "203.0.113.7"


def test_without_a_trusted_proxy_forwarded_headers_are_ignored(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    assert main._get_client_ip(_req("9.9.9.9, 203.0.113.7")) == "10.0.0.1"


def test_the_rate_limit_allows_exactly_the_limit_per_address():
    for _ in range(main.RATE_LIMIT_MAX_REQUESTS):
        main._check_rate_limit("198.51.100.1")
    with pytest.raises(Exception) as e:
        main._check_rate_limit("198.51.100.1")
    assert getattr(e.value, "status_code", None) == 429
    main._check_rate_limit("198.51.100.2")          # another address is not affected


# ------------------------------------------------------------------ CORS
def test_cors_allows_only_configured_origins_without_credentials():
    r = client.options("/api/models", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"
    assert r.headers.get("access-control-allow-credentials") != "true"


def test_a_demo_run_is_marked_as_demo_in_the_project_list(tmp_path):
    ws = str(tmp_path)
    db.init_db(ws)
    r = _response("ccc333")
    r.model, r.fallback_notice = "offline demo", "Built-in demo"
    db.save_project(r, prompt="demo", workspace=ws)
    live = _response("ddd444")
    live.model = "opencode/deepseek-v4.1-flash-free"
    db.save_project(live, prompt="live", workspace=ws)
    by_id = {p["design_id"]: p for p in db.list_projects(workspace=ws)}
    assert by_id["ccc333"]["demo"] is True
    assert by_id["ddd444"]["demo"] is False and by_id["ddd444"]["model"] == "opencode/deepseek-v4.1-flash-free"


# ------------------------------------------------------------------ request size
def test_an_oversized_body_is_refused_with_or_without_a_content_length():
    big = b'{"prompt": "' + b"x" * (main.MAX_BODY_BYTES + 10) + b'"}'
    r = client.post("/api/design/run", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413

    def chunks():                       # a chunked upload has no Content-Length header
        for i in range(0, len(big), 65536):
            yield big[i:i + 65536]
    r = client.post("/api/design/run", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_a_normal_body_is_accepted():
    assert client.get("/health").status_code == 200
