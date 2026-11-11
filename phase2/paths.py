"""Local resource locations for the agent integration, overridable per workstation."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def embedding_cache() -> Path:
    """Verified all-MiniLM-L6-v2 ONNX cache; never downloaded implicitly."""
    configured = os.environ.get("EXFILSCOPE_EMBEDDING_CACHE")
    return Path(configured) if configured else ROOT / "models" / "all-MiniLM-L6-v2"


def agent_python() -> Path:
    """Interpreter of the isolated agent environment used for worker subprocesses."""
    configured = os.environ.get("EXFILSCOPE_AGENT_PYTHON")
    if configured:
        return Path(configured)
    return ROOT / ".venv-agent" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
