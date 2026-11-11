"""Trusted snapshot exporter, run in the core environment; never imported by the UI.

Copy closed DB/WAL files before using existing evidence readers. Original evidence
is not opened by SQLite. Only allowlisted minimized fields enter dashboard/data.
Incidents use the verifier's recorded event identifiers; observations are never re-paired.
"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import time
from uuid import UUID

from exfilscope.contracts import RuntimeEvent
from exfilscope.ledger import read_events, read_monitor_snapshot
from exfilscope.privacy import scan_routine_files
from exfilscope.registry import Registry

from .evidence import SCHEMA, Bundle, Incident, Observation, Runtime

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = {
    "qwen3-live": ("routine/results.csv", "lab/ledger_a/runtime.sqlite",
                   "lab/ledger_b/network.sqlite"),
    "engineering-faults": ("results.csv", "ledger_a/runtime.sqlite", "ledger_b/network.sqlite"),
}
# Curated sources for the committed snapshots; override with --live/--faults.
DEFAULT_SOURCES = {
    "qwen3-live": ROOT / "artifacts" / "phase2-live-stageb-1793375995",
    "engineering-faults": ROOT / "artifacts" / "methodology-smoke-1793375753689191900",
}
FAULTS = {"block_bypass", "payload_divergence", "destination_divergence", "no_observation"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def one(items, error):
    if len(items) != 1:
        raise ValueError(error)
    return items[0]


def incident(investigation, run_id, protocol, row, events_a, events_b, health):
    if not row.get("runtime_event_id") or "network_event_id" not in row:
        raise ValueError("RESULT_EXPORT_LACKS_VERIFIER_PAIRING")
    a = one([e for e in events_a if e.event_id == UUID(row["runtime_event_id"])],
            "AMBIGUOUS_RUNTIME_SOURCE")
    if str(a.trace_id) != row["trace_id"] or a.schema_version != "1.1" \
            or a.decision.value != row["decision"]:
        raise ValueError("SOURCE_CONTRACT_DISAGREEMENT")
    b = None
    if row["network_event_id"]:
        b = one([e for e in events_b if e.event_id == UUID(row["network_event_id"])],
                "AMBIGUOUS_NETWORK_SOURCE")
    if row.get("result_schema_version", "2.0") != "2.0":
        raise ValueError("HISTORICAL_RESULT_NOT_CURRENT")
    case = row.get("case", row.get("scenario"))
    raw_a, raw_b = a.model_dump(mode="json"), b.model_dump(mode="json") if b else None
    origin = "LLM run" if investigation == "qwen3-live" else (
        "Controlled fault injection" if case in FAULTS else "Deterministic replay")
    return {
        "run_id": run_id, "scenario": case, "protocol": protocol, "origin": origin,
        "runtime": {key: raw_a[key] for key in Runtime.model_fields},
        "observation": {key: raw_b[key] for key in Observation.model_fields} if raw_b else None,
        "verification": {"schema_version": "2.0", "runtime_event_id": str(a.event_id),
                         "network_event_id": str(b.event_id) if b else None,
                         "result": row["result"], "evidence_status": row["evidence_status"],
                         "labels": [s for s in row["labels"].split("|") if s],
                         "diagnostics": [s for s in row["diagnostics"].split("|") if s]},
        "window_seconds": float(row.get("window_seconds", 5)),
        "health_records": len(health), "monitor_generations": len({h.run_id for h in health}),
        "observation_withheld": case == "no_observation",
    }


def prepare(output=None, sources=None):
    output = output or ROOT / "dashboard/data"
    sources = sources or DEFAULT_SOURCES
    if output.exists():
        raise FileExistsError("Snapshot directory exists; preserve it and choose a new output.")
    scratch = ROOT / "artifacts" / f"dashboard-export-{time.time_ns()}"
    scratch.mkdir(parents=True)
    bundles, original_bytes = {}, {}
    registry = Registry.load(ROOT / "examples/registry.json")
    for investigation, source in sources.items():
        csv_name, a_name, b_name = LAYOUTS[investigation]
        source, run_id = Path(source), Path(source).name
        raw = (source / csv_name).read_bytes()
        original_bytes[source / csv_name] = digest(raw)
        hashes = {"results.csv": digest(raw)}
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        incidents = []
        for protocol in ["http", "https"]:
            for name in [a_name, b_name]:
                db = source / protocol / name
                for p in [db, Path(str(db) + "-wal")]:
                    if p == db or p.exists():
                        data = p.read_bytes()
                        original_bytes[p] = digest(data)
                        relative = p.relative_to(source)
                        hashes[str(relative).replace("\\", "/")] = digest(data)
                        target = scratch / run_id / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(data)
            events_a = read_events(scratch / run_id / protocol / a_name, RuntimeEvent, "A")
            events_b, health = read_monitor_snapshot(scratch / run_id / protocol / b_name)
            for row in (r for r in rows if r["protocol"] == protocol):
                record = incident(investigation, run_id, protocol, row, events_a, events_b, health)
                Incident.model_validate_json(json.dumps(record))
                incidents.append(record)
        bundle = {"schema_version": SCHEMA, "investigation_id": investigation,
                  "source_hashes": hashes, "incidents": incidents}
        Bundle.model_validate_json(json.dumps(bundle))
        bundles[investigation] = json.dumps(bundle, indent=2).encode("utf-8")
    if any(digest(p.read_bytes()) != h for p, h in original_bytes.items()):
        raise RuntimeError("SOURCE_CHANGED_DURING_EXPORT")
    # Reject known protected values before publishing any UI-accessible data.
    for data in bundles.values():
        if registry.contains(data.decode("utf-8")):
            raise ValueError("UNSAFE_EXPORT")
    output.mkdir(parents=True, exist_ok=False)
    for identifier, data in bundles.items():
        (output / (identifier + ".json")).write_bytes(data)
    manifest = {"schema_version": SCHEMA,
                "files": {name: digest(data) for name, data in bundles.items()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    leaks = scan_routine_files(list(output.glob("*.json")), registry)
    if leaks:
        raise RuntimeError("EXPORTED_SNAPSHOT_PRIVACY_FAILURE")
    report = {"original_files": {str(p): h for p, h in original_bytes.items()},
              "originals_unchanged": all(digest(p.read_bytes()) == h
                                         for p, h in original_bytes.items()),
              "known_value_recoveries": leaks, "output": str(output),
              "incidents": {name: len(json.loads(data)["incidents"])
                            for name, data in bundles.items()}}
    (scratch / "export-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "original_files"}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="Export minimized dashboard snapshots")
    parser.add_argument("--live", type=Path, default=DEFAULT_SOURCES["qwen3-live"])
    parser.add_argument("--faults", type=Path, default=DEFAULT_SOURCES["engineering-faults"])
    parser.add_argument("--output", type=Path, default=ROOT / "dashboard/data")
    args = parser.parse_args()
    prepare(args.output, {"qwen3-live": args.live, "engineering-faults": args.faults})


if __name__ == "__main__":
    main()
