import os
import sys
from pathlib import Path

# Force offline mode BEFORE any backend module imports its provider.
os.environ["OFFLINE_MODE"] = "1"

# Make backend importable as top-level modules.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
