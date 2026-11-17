"""The browser uses /api/design/stream, so a finished streamed run must be saved
and listed by the Projects drawer (it previously was not: only /api/design/run saved)."""

import json

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def _run_stream(prompt: str) -> dict:
    done = None
    with client.stream("POST", "/api/design/stream", json={"prompt": prompt, "max_iterations": 1}) as r:
        assert r.status_code == 200
        for line in r.iter_lines():
            if line.startswith("data: "):
                ev = json.loads(line[6:])
                if ev.get("stage") == "done":
                    done = ev
    assert done is not None, "stream never reached the done stage"
    return done


def test_streamed_run_is_persisted_and_listed():
    done = _run_stream("Design a 4-bit counter")
    design_id = done["response"]["design_id"]

    listing = client.get("/api/projects").json()
    assert design_id in [p["design_id"] for p in listing["projects"]]

    full = client.get(f"/api/projects/{design_id}")
    assert full.status_code == 200
    assert full.json()["rtl_code"] == done["response"]["rtl_code"]
