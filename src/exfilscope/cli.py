"""Lab CLI for single scenarios and engineering pilots; not a research-batch runner."""

import argparse
import csv
import json
import time
from pathlib import Path

from .lab import Lab
from .privacy import routine_paths, scan_routine_files
from .scenarios import SCENARIOS, run_fault_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="ExfilScope controlled lab")
    parser.add_argument("command", choices=("scenario", "pilot"))
    parser.add_argument("--scenario", choices=SCENARIOS, default="allow")
    parser.add_argument("--protocol", choices=("http", "https", "both"), default="http")
    parser.add_argument("--cases-per-class", type=int, choices=(6, 10), default=6)
    parser.add_argument("--window", type=float, default=5.0)
    parser.add_argument("--claim-mode", choices=("plausible", "false_not_executed"),
                        default="plausible")
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    if not 0 < args.window <= 60:
        parser.error("window must be >0 and <=60 seconds")
    # A fixed lab window smaller than 5 s is only a test/pilot override, recorded below.
    run_dir = args.output / f"pilot-{time.time_ns()}"
    protocols = ("http", "https") if args.protocol == "both" else (args.protocol,)
    if args.command == "pilot" and args.protocol != "both":
        parser.error("pilot requires --protocol both to preserve the HTTP/HTTPS balance")
    count = args.cases_per_class // len(protocols) if args.command == "pilot" else 1
    scenarios = SCENARIOS if args.command == "pilot" else (args.scenario,)
    rows = []
    for protocol_index, protocol in enumerate(protocols):
        with Lab(run_dir / protocol, protocol) as lab:
            for scenario in scenarios:
                for index in range(count):
                    trial = run_fault_scenario(lab, scenario,
                                               case=index + protocol_index * count,
                                               window=args.window, claim_mode=args.claim_mode)
                    row = {"scenario": scenario, "protocol": protocol,
                           "result_schema_version": trial.verification.schema_version,
                           "event_schema_version": trial.event.schema_version,
                           "policy_version": trial.event.policy_version,
                           "trace_id": str(trial.event.trace_id),
                           "runtime_event_id": str(trial.verification.runtime_event_id),
                           "network_event_id": str(trial.verification.network_event_id or ""),
                           "decision": trial.event.decision.value,
                           "runtime_claim": trial.event.claim.value,
                           "fault_claim_mode": args.claim_mode,
                           "result": trial.verification.result,
                           "evidence_status": trial.verification.evidence_status,
                           "labels": "|".join(trial.verification.labels),
                           "diagnostics": "|".join(trial.verification.diagnostics),
                           "elapsed_ms": round(trial.elapsed_ms, 3),
                           "receiver_count": trial.receiver_count,
                           "window_seconds": args.window,
                           "drain_grace_seconds": 1.0}
                    rows.append(row)
                    print(json.dumps(row))
            leaks = scan_routine_files(routine_paths(lab.directory), lab.registry)
            if leaks:
                raise RuntimeError("ROUTINE_SYNTHETIC_EXPOSURE_DETECTED")
    with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Completed {len(rows)} deterministic engineering trials: {run_dir / 'results.csv'}")
    print("BLOCK MATCH is scoped to the covered proxy request boundary and window only.")


if __name__ == "__main__":
    main()
