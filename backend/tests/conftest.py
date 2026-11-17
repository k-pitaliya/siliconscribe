import os
import sys
from pathlib import Path

# Force offline mode BEFORE any backend module imports its provider.
os.environ["OFFLINE_MODE"] = "1"

# Make backend importable as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest  # noqa: E402


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
