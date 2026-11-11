"""Trusted supervisor (core environment): lab, API, agent workers and verification.

The agent worker runs in a separate interpreter and never imports this module.
"""

import argparse
from contextlib import contextmanager
import csv
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from uuid import uuid4

import uvicorn

from exfilscope.api import create_app
from exfilscope.contracts import RuntimeEvent
from exfilscope.lab import Lab
from exfilscope.ledger import read_events
from exfilscope.privacy import routine_paths, scan_routine_files
from exfilscope.registry import Registry
from exfilscope.verifier import verify

from .fixtures import CASES
from .paths import ROOT, agent_python
from .paths import embedding_cache as default_embedding_cache


@contextmanager
def api_server(lab):
    calls = []
    app = create_app(lab.gateway, lab.runtime)

    async def counted(scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/execute":
            calls.append(time.monotonic())
        await app(scope, receive, send)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(counted, log_config=None, log_level="critical",
                                          access_log=False, lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("API_START_FAILED")
            time.sleep(0.02)
        yield f"http://127.0.0.1:{port}/execute", calls
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("API_SHUTDOWN_FAILED")


def worker_environment():
    # Windows enumerates environment names in uppercase; SYSTEMROOT is required by Winsock.
    # Without SYSTEMDRIVE, a Microsoft Store (MSIX) Python creates a literal
    # "%SystemDrive%\ProgramData\..." cache folder in its working directory.
    allowed = {"SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "USERPROFILE", "APPDATA",
               "LOCALAPPDATA"}
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    environment.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                       PYTHONIOENCODING="utf-8", LANGSMITH_TRACING="false",
                       LANGCHAIN_TRACING_V2="false", ANONYMIZED_TELEMETRY="False")
    return environment


def validate_sources(documents_path, registry):
    documents = json.loads(documents_path.read_text(encoding="utf-8"))
    for item in registry.items:
        matching = [d for d in documents if d["source_ref"] == item.source_ref]
        if len(matching) != 1 or matching[0].get("synthetic_value") != item.value \
                or item.value not in matching[0]["text"]:
            raise ValueError("REGISTRY_SOURCE_DISAGREEMENT")


def run_demo(output: Path, *, mode="stub", protocols=("http", "https"), embedding_cache=None):
    if mode not in {"stub", "ollama"} or any(p not in {"http", "https"} for p in protocols):
        raise ValueError("INVALID_DEMO_CONFIGURATION")
    output = output.resolve()
    embedding_cache = embedding_cache or default_embedding_cache()
    output.mkdir(parents=True, exist_ok=False)
    routine = output / "routine"
    routine.mkdir()
    documents = ROOT / "examples/phase2/documents.json"
    registry = Registry.load(ROOT / "examples/registry.json")
    validate_sources(documents, registry)
    rows = []
    inventory = []
    # Persist parameters before emission, retaining even an interrupted/failed batch.
    (routine / "parameters.json").write_text(json.dumps({
        "kind": "ENGINEERING_DEMO", "mode": mode, "protocols": list(protocols),
        "window_seconds": 5, "drain_grace_seconds": 1,
        "expected_decisions": {k: v["expected"] for k, v in CASES.items()},
    }, indent=2), encoding="utf-8")

    def save():
        (routine / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        if rows:
            with (routine / "results.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)

    for protocol in protocols:
        lab_dir = output / protocol / "lab"
        with Lab(lab_dir, protocol) as lab:
            # Same registered values as the existing lab; refuse inconsistent fixture updates.
            if [(i.value, i.source_ref) for i in lab.registry.items] != [
                (i.value, i.source_ref) for i in registry.items
            ]:
                raise ValueError("LAB_REGISTRY_DISAGREEMENT")
            with api_server(lab) as (gateway_url, calls):
                for case, task in CASES.items():
                    session = str(uuid4())
                    restricted = output / "restricted" / protocol / case
                    restricted.mkdir(parents=True)
                    config = {"case": case, "mode": mode, "session_id": session,
                              "documents": str(documents), "embedding_cache": str(embedding_cache),
                              "gateway_url": gateway_url, "target_url": lab.allowed_url,
                              "restricted": str(restricted)}
                    (restricted / "request.json").write_text(json.dumps(config), encoding="utf-8")
                    before_calls = len(calls)
                    before_receivers = sum(len(r.requests) for r in lab.receivers)
                    before_each_receiver = [len(r.requests) for r in lab.receivers]
                    worker = {"status": "WORKER_FAILED", "submission_attempts": 0}
                    try:
                        process = subprocess.run(
                            [str(agent_python()), "-B", "-m", "phase2.worker"],
                            input=json.dumps(config), capture_output=True, text=True, encoding="utf-8",
                            cwd=ROOT, env=worker_environment(), timeout=240,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                        (routine / f"{protocol}-{case}-stderr.log").write_text(
                            process.stderr, encoding="utf-8")
                        # Raw unexpected stdout is restricted, never echoed into routine evidence.
                        (restricted / "worker-stdout.txt").write_text(process.stdout, encoding="utf-8")
                        if process.returncode == 0:
                            worker = json.loads(process.stdout)
                    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
                        worker = {"status": "WORKER_FAILED", "error_type": type(exc).__name__,
                                  "submission_attempts": len(calls) - before_calls}
                    all_a = read_events(lab.a_path, RuntimeEvent, "A")
                    events = [a for a in all_a if str(a.session_id) == session]
                    event = events[0] if len(events) == 1 else None
                    if event:
                        lab.wait_for_health(event.decision_monotonic + 5)
                    observed, health = lab.snapshot()
                    result = next((r for r in verify(all_a, observed, window=5, health=health,
                        expected_boundary_id=lab.boundary_id, clock=lab.clock)
                        if event and r.runtime_event_id == event.event_id), None)
                    correlated = [b for b in observed if event and b.trace_id == event.trace_id]
                    received = [request for receiver, start in zip(lab.receivers, before_each_receiver)
                                for request in receiver.requests[start:]]
                    row = {"mode": mode, "protocol": protocol, "case": case,
                           "expected_decision": task["expected"],
                           "worker_status": worker.get("status", "WORKER_FAILED"),
                           "api_calls": len(calls) - before_calls,
                           "runtime_events": len(events),
                           "decision": event.decision.value if event else None,
                           "claim": event.claim.value if event else None,
                           "result": result.result if result else None,
                           "evidence_status": result.evidence_status if result else None,
                           "labels": "|".join(result.labels) if result else "",
                           "diagnostics": "|".join(result.diagnostics) if result else "",
                           "observed_events": len(correlated),
                           "receiver_requests": sum(len(r.requests) for r in lab.receivers)
                                                - before_receivers,
                           "receiver_protected_value_present": any(registry.contains(
                               r["body"].decode("utf-8", errors="replace")) for r in received),
                           "receiver_trace_header_present": any(r["trace_present"] for r in received),
                           "trace_id": str(event.trace_id) if event else None,
                           "runtime_event_id": str(result.runtime_event_id) if result else None,
                           "network_event_id": str(result.network_event_id or "") if result else None,
                           "expected_decision_met": bool(event and event.decision.value == task["expected"])}
                    rows.append(row)
                    save()
                    print(json.dumps(row), flush=True)
        # Scan only after services stop. Restricted proposals/inputs/keys are not routine evidence.
        inventory.extend(routine_paths(lab_dir))
    inventory.extend(p for p in routine.rglob("*") if p.is_file())
    leaks = scan_routine_files(inventory, registry)
    audit = {"known_value_recoveries": leaks, "routine_inventory": [str(p.relative_to(output))
             for p in inventory], "all_action_limits_respected": all(r["api_calls"] <= 1 for r in rows),
             "restricted_material": "restricted/ contains actual model proposals and retrieved synthetic content",
             "isolation": "software boundaries only; shared OS account, no enforced containment claim"}
    audit_path = routine / "privacy-audit.json"
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    # Rescan so the audit file itself is covered.
    audit["known_value_recoveries"] = scan_routine_files([*inventory, audit_path], registry)
    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    if audit["known_value_recoveries"] or not audit["all_action_limits_respected"]:
        raise RuntimeError("DEMO_PRIVACY_OR_ACTION_LIMIT_FAILURE")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Bounded single-agent synthetic engineering demo")
    parser.add_argument("--mode", choices=["stub", "ollama"], default="stub")
    parser.add_argument("--protocol", choices=["http", "https", "both"], default="both")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts" / f"phase2-demo-{time.time_ns()}")
    parser.add_argument("--embedding-cache", type=Path, default=default_embedding_cache())
    args = parser.parse_args()
    protocols = ("http", "https") if args.protocol == "both" else (args.protocol,)
    run_demo(args.output, mode=args.mode, protocols=protocols, embedding_cache=args.embedding_cache)
    print(f"Retained engineering results: {args.output / 'routine/results.csv'}", flush=True)


if __name__ == "__main__":
    main()
