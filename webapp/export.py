"""Trusted exporter for one platform run (core environment, runner process only).

It follows ``dashboard.prepare``: closed ledger files are copied before the existing
readers open them, incidents are built by ``dashboard.prepare.incident`` from the
verifier's own event pairing, and the result is checked against the registry before an
atomic publication into ``export/``.
"""

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil

from dashboard.prepare import incident
from exfilscope.contracts import RuntimeEvent
from exfilscope.ledger import read_events, read_monitor_snapshot
from exfilscope.privacy import scan_routine_files
from exfilscope.registry import Registry

from .evidence import SCHEMA, RunSnapshot, load_run_snapshot
from .paths import ROOT

# results file, Ledger A and Ledger B relative to the evidence folder (per protocol).
LAYOUTS = {
    "lab": ("results.csv", "{p}/ledger_a/runtime.sqlite", "{p}/ledger_b/network.sqlite"),
    "live": ("routine/results.csv", "{p}/lab/ledger_a/runtime.sqlite",
             "{p}/lab/ledger_b/network.sqlite"),
}
LAYOUTS["stub"] = LAYOUTS["live"]
LAYOUTS["trust"] = LAYOUTS["lab"]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_run(run: Path, run_id: str, scenario_id: str, mode: str, protocol: str,
               claim_mode: str, extra: dict[str, bytes] | None = None) -> RunSnapshot:
    """``extra`` holds separately versioned files (the trust audit), published alongside."""
    evidence, work = run / "evidence", run / "export-work"
    final, staging = run / "export", run / "export.tmp"
    if final.exists() or staging.exists() or work.exists():
        raise FileExistsError("EXPORT_ALREADY_STARTED")
    results, a_name, b_name = (name.format(p=protocol) for name in LAYOUTS[mode])
    raw = (evidence / results).read_bytes()
    hashes, originals = {"results.csv": digest(raw)}, {}
    for name in (a_name, b_name):
        for source in (evidence / name, evidence / (name + "-wal")):
            if source.exists() or source.suffix == ".sqlite":
                data = source.read_bytes()
                originals[source] = digest(data)
                relative = source.relative_to(evidence).as_posix()
                hashes[relative] = digest(data)
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    events_a = read_events(work / a_name, RuntimeEvent, "A")
    events_b, health = read_monitor_snapshot(work / b_name)
    rows = [r for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            if r["protocol"] == protocol]
    if not 1 <= len(rows) <= (2 if mode == "trust" else 1):
        raise ValueError("RUN_RESULT_NOT_UNIQUE")
    investigation = "qwen3-live" if mode in ("live", "stub") else "engineering-faults"
    records = [incident(investigation, run_id, protocol, row, events_a, events_b, health)
               for row in rows]
    if mode == "stub":
        records[0]["origin"] = "Deterministic replay"
    # Strict models accept UUIDs only from JSON, as in dashboard.prepare.
    snapshot = RunSnapshot.model_validate_json(json.dumps({
        "schema_version": SCHEMA, "run_id": run_id, "scenario_id": scenario_id, "mode": mode,
        "protocol": protocol, "claim_mode": claim_mode, "source_hashes": hashes,
        "incidents": records}))
    data = json.dumps(snapshot.model_dump(mode="json"), indent=2).encode("utf-8")
    registry = Registry.load(ROOT / "examples/registry.json")
    files = {"snapshot.json": data, **(extra or {})}
    if set(files) - {"snapshot.json", "trust-audit.json"} or any(
            registry.contains(content.decode("utf-8")) for content in files.values()):
        raise ValueError("UNSAFE_EXPORT")
    if any(digest(p.read_bytes()) != h for p, h in originals.items()):
        raise RuntimeError("SOURCE_CHANGED_DURING_EXPORT")
    staging.mkdir()
    for name, content in files.items():
        (staging / name).write_bytes(content)
    (staging / "manifest.json").write_text(json.dumps(
        {"schema_version": SCHEMA, "files": {n: digest(c) for n, c in files.items()}}, indent=2),
        encoding="utf-8")
    if scan_routine_files(list(staging.glob("*.json")), registry):
        raise RuntimeError("EXPORTED_SNAPSHOT_PRIVACY_FAILURE")
    load_run_snapshot(staging)
    if "trust-audit.json" in files:
        from .trust.audit import load_trust_audit

        load_trust_audit(staging)
    os.replace(staging, final)
    shutil.rmtree(work)
    return snapshot
