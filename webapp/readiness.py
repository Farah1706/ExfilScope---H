"""Real readiness checks. Every state comes from a probe made when it is requested.

States: missing, installed, configured, running, healthy, unhealthy, not_required.
"""

import hashlib
import shutil
import time

import httpx

from dashboard.evidence import load_catalog

from .paths import ROOT, SNAPSHOTS, agent_python, core_python, embedding_cache, mitmdump

from phase2.contracts import MODEL, MODEL_MANIFEST_DIGEST, OLLAMA_URL

MODEL_DIGEST = MODEL_MANIFEST_DIGEST
EMBEDDING_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
OLLAMA = OLLAMA_URL
_hash_cache: dict[tuple, bool] = {}


def item(identifier, label, state, detail, needed_for):
    return {"id": identifier, "label": label, "state": state, "detail": detail,
            "needed_for": needed_for}


def _embedding() -> dict:
    archive = embedding_cache() / "onnx.tar.gz"
    documents = ROOT / "examples/phase2/documents.json"
    if not archive.is_file() or not documents.is_file():
        return item("retrieval", "Retrieval resources", "missing",
                    "Embedding archive or synthetic documents not found", ["live", "stub"])
    stat = archive.stat()
    key = (str(archive), stat.st_size, stat.st_mtime_ns)
    if key not in _hash_cache:
        _hash_cache[key] = hashlib.sha256(archive.read_bytes()).hexdigest() == EMBEDDING_SHA256
    if not _hash_cache[key]:
        return item("retrieval", "Retrieval resources", "unhealthy",
                    "Embedding archive SHA-256 differs from Chroma's pinned value",
                    ["live", "stub"])
    return item("retrieval", "Retrieval resources", "healthy",
                "all-MiniLM-L6-v2 archive verified; synthetic documents present",
                ["live", "stub"])


def _ollama() -> dict:
    try:
        with httpx.Client(trust_env=False, timeout=2.0) as client:
            models = client.get(f"{OLLAMA}/api/tags").json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return item("ollama", "Ollama and Qwen3 model", "missing",
                    "Ollama is not answering on 127.0.0.1:11435", ["live"])
    found = next((m for m in models if m.get("name") == MODEL), None)
    if found is None:
        return item("ollama", "Ollama and Qwen3 model", "running",
                    f"Ollama is running but {MODEL} is not pulled", ["live"])
    if found.get("digest") != MODEL_DIGEST:
        return item("ollama", "Ollama and Qwen3 model", "unhealthy",
                    "Model digest differs from the recorded digest", ["live"])
    return item("ollama", "Ollama and Qwen3 model", "healthy",
                f"{MODEL}, digest {MODEL_DIGEST[:12]}… matches", ["live"])


def _gateway() -> dict:
    from exfilscope.policy import GatewayPolicy
    from exfilscope.registry import Registry

    try:
        policy = GatewayPolicy.load(ROOT / "examples/policy.json")
        registry = Registry.load(ROOT / "examples/registry.json")
    except (OSError, ValueError):
        return item("gateway", "Security gateway", "unhealthy",
                    "Trusted policy or registry failed validation", ["live", "stub", "lab"])
    return item("gateway", "Security gateway", "configured",
                f"Policy {policy.version}, {len(registry.items)} registered protected items; "
                "started per run", ["live", "stub", "lab"])


def _evidence() -> dict:
    catalog, issues = load_catalog(SNAPSHOTS)
    if issues or not catalog:
        return item("evidence", "Evidence validation", "unhealthy",
                    "A committed snapshot failed its hash or schema check", [])
    total = sum(len(b.incidents) for b in catalog.values())
    return item("evidence", "Evidence validation", "healthy",
                f"{len(catalog)} committed snapshots, {total} incidents, hashes and schema valid",
                [])


def check() -> dict:
    started = time.monotonic()
    core = core_python().is_file()
    items = [
        item("core", "Core environment", "installed" if core else "missing",
             ".venv with the forensic core" if core else ".venv not found",
             ["live", "stub", "lab"]),
        item("lab", "mitmproxy and lab harness",
             "installed" if mitmdump().is_file() else "missing",
             "mitmdump present; a separate proxy process starts for each run"
             if mitmdump().is_file() else "mitmdump not found in .venv",
             ["live", "stub", "lab"]),
        _gateway(),
        item("agent", "Agent environment", "installed" if agent_python().is_file() else "missing",
             ".venv-agent with LangGraph and Chroma" if agent_python().is_file()
             else ".venv-agent not found", ["live", "stub"]),
        _embedding(),
        _ollama(),
        _evidence(),
        item("docker", "Docker", "installed" if shutil.which("docker") else "not_required",
             "Not used by local demonstrations; container validation is a custodian procedure",
             []),
    ]
    good = {"installed", "configured", "running", "healthy"}
    ready = {}
    for mode in ("lab", "stub", "live", "trust"):
        # The trust extension needs exactly what the lab harness needs.
        needs = "lab" if mode == "trust" else mode
        blocking = [i["id"] for i in items if needs in i["needed_for"] and (
            i["state"] not in good or (i["id"] == "ollama" and i["state"] != "healthy"))]
        ready[mode] = {"ready": not blocking, "blocking": blocking}
    return {"items": items, "modes": ready, "checked_at": time.time(),
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}
