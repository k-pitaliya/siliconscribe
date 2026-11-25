import os
import sys
from pathlib import Path

# Force offline mode BEFORE any backend module imports its provider.
os.environ["OFFLINE_MODE"] = "1"
# main.py runs the workspace clean-up and opens the projects database AT IMPORT. Point it at a throw-away folder before
# any test module imports it (self-review finding: collecting the tests deleted old folders of the real workspace).
import tempfile  # noqa: E402
os.environ["SILICONSCRIBE_WORKSPACE"] = tempfile.mkdtemp(prefix="ss_test_ws_")

# Make backend importable as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_credentials_or_network_models(monkeypatch):
    """No test may depend on the developer's real Cloudflare key (backend/.env is loaded at import) or reach Cloudflare.

    Without this a real key in backend/.env made list_models() append the live Cloudflare catalogue to every
    result and call the network. Tests that need Cloudflare set fake values themselves, against a local stand-in.
    """
    import model_catalog
    for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_KEY", "CLOUDFLARE_API_BASE",
                 "NVIDIA_NIM_API_KEY", "NVIDIA_NIM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    # The real model_hidden.json lists tonight's failed models; tests must not depend on it (tests that need a list
    # point MODEL_HIDDEN_FILE at their own file).
    monkeypatch.setenv("MODEL_HIDDEN_FILE", "/nonexistent/model_hidden.json")
    # The testbench fallback (orchestrator.testbench_fallback_model) is off unless a test turns it on, so tests of
    # "the chosen model failed and the run says so" keep their meaning.
    monkeypatch.setenv("TESTBENCH_FALLBACK_MODEL", "")
    # The developer machine has the real Claude Code CLI; menu tests must not depend on it (tests that need it turn it on).
    monkeypatch.setenv("CLAUDE_CODE_PROVIDER", "0")
    model_catalog.clear_cache()
    yield
    model_catalog.clear_cache()


@pytest.fixture(autouse=True, scope="session")
def _isolated_workspace(tmp_path_factory):
    """Run the whole suite against a throw-away workspace and projects database.

    Without this the API tests wrote rows into the developer's real
    backend/workspace/projects.db (and design folders next to it) on every run.
    """
    import main
    import db
    from simulator import IcarusSimulator

    ws = tmp_path_factory.mktemp("workspace")
    old_ws, old_sim = main.WORKSPACE, main.simulator
    main.WORKSPACE = str(ws)
    main.simulator = IcarusSimulator(workspace=str(ws))
    db.init_db(str(ws))
    yield
    main.WORKSPACE, main.simulator = old_ws, old_sim
