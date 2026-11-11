"""Fixed locations. No path below is ever taken from a browser request."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
# Set only by the run manager for its runner child (tests use a temporary root).
RUNS = Path(os.environ.get("EXFILSCOPE_PLATFORM_RUNS") or ROOT / "artifacts" / "platform-runs")
SNAPSHOTS = ROOT / "dashboard" / "data"


def env_root() -> Path:
    """Folder holding .venv, .venv-agent and models/ (the repository root by default)."""
    configured = os.environ.get("EXFILSCOPE_ENV_ROOT")
    return Path(configured).resolve() if configured else ROOT


def core_python() -> Path:
    return env_root() / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def mitmdump() -> Path:
    return core_python().parent / ("mitmdump.exe" if os.name == "nt" else "mitmdump")


def agent_python() -> Path:
    configured = os.environ.get("EXFILSCOPE_AGENT_PYTHON")
    if configured:
        return Path(configured)
    return env_root() / ".venv-agent" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def embedding_cache() -> Path:
    configured = os.environ.get("EXFILSCOPE_EMBEDDING_CACHE")
    return Path(configured) if configured else env_root() / "models" / "all-MiniLM-L6-v2"
