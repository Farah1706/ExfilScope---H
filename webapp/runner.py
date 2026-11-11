"""Fixed run entry point, started by the control service as ``python -m webapp.runner``.

stdin carries one validated request: the run directory chosen by the service plus a
RunRequest. stdout carries only stage records (``{"xs_stage": ...}``) and codes, never
evidence content. The runner reuses the lab harness (``run_fault_scenario``) and the agent
supervisor (``phase2.demo.run_demo``) unchanged and then exports the run.
"""

import csv
import json
from pathlib import Path
import sys
import time
import traceback

from .contracts import RUN_ID, RunRequest
from .paths import RUNS
from .scenarios import BY_ID, lab_case

WINDOW = 5.0


def stage(name: str, status: str, detail: str = "", **facts) -> None:
    print(json.dumps({"xs_stage": name, "status": status, "detail": detail, "facts": facts,
                      "at": time.time()}), flush=True)


def lab_run(evidence: Path, request: RunRequest) -> dict:
    from exfilscope.lab import Lab
    from exfilscope.privacy import routine_paths, scan_routine_files
    from exfilscope.scenarios import run_fault_scenario

    scenario = BY_ID[request.scenario_id]
    case = lab_case(scenario, request.protected_item)
    stage("preparation", "running", "Starting local receivers, TLS material and mitmdump")
    with Lab(evidence / request.protocol, request.protocol) as lab:
        stage("preparation", "complete", "Lab harness ready: receivers, monitor and ledgers",
              protocol=request.protocol, case=case)
        stage("proposal", "complete", "Deterministic laboratory case prepared",
              lab_scenario=scenario.lab_scenario)
        stage("gateway", "running", "Authorizing, emitting and waiting for the window",
              window_seconds=WINDOW)
        trial = run_fault_scenario(lab, scenario.lab_scenario, case=case, window=WINDOW,
                                   claim_mode=request.claim_mode)
        event, result = trial.event, trial.verification
        leaks = scan_routine_files(routine_paths(lab.directory), lab.registry)
    stage("gateway", "complete", "Decision recorded in Ledger A before emission",
          decision=event.decision.value, reason=event.reason, policy=event.policy_version)
    stage("execution", "complete", "Runtime claim recorded in Ledger A",
          claim=event.claim.value, fault=scenario.origin == "Controlled fault injection")
    stage("observation", "complete",
          "Correlated observation paired by the verifier" if result.network_event_id
          else "No observation paired by the verifier", paired=bool(result.network_event_id))
    stage("drain", "complete", "Window closed and monitor health drained",
          window_seconds=WINDOW)
    stage("verification", "complete", "Verifier classified the attempt", result=result.result,
          evidence_status=result.evidence_status, labels=list(result.labels))
    if leaks:
        raise RuntimeError("ROUTINE_SYNTHETIC_EXPOSURE_DETECTED")
    row = {"scenario": scenario.lab_scenario, "protocol": request.protocol,
           "result_schema_version": result.schema_version,
           "trace_id": str(event.trace_id), "runtime_event_id": str(result.runtime_event_id),
           "network_event_id": str(result.network_event_id or ""),
           "decision": event.decision.value, "runtime_claim": event.claim.value,
           "fault_claim_mode": request.claim_mode, "result": result.result,
           "evidence_status": result.evidence_status, "labels": "|".join(result.labels),
           "diagnostics": "|".join(result.diagnostics), "window_seconds": WINDOW,
           "receiver_count": trial.receiver_count}
    with (evidence / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return row


def agent_run(evidence: Path, request: RunRequest) -> dict:
    import phase2.demo as demo
    from phase2.fixtures import CASES

    scenario = BY_ID[request.scenario_id]
    # Restrict the unchanged supervisor loop to the one selected frozen task.
    demo.CASES = {scenario.live_case: CASES[scenario.live_case]}
    stage("preparation", "complete", "Synthetic documents and registry agree",
          task=scenario.live_case)
    stage("proposal", "running",
          "Qwen3 retrieves documents and proposes one action" if request.mode == "live"
          else "Agent pipeline with the deterministic stub proposal")
    rows = demo.run_demo(evidence, mode="ollama" if request.mode == "live" else "stub",
                         protocols=(request.protocol,))
    row = rows[0]
    worker_ok = row["worker_status"] not in ("WORKER_FAILED", "SETUP_FAILED")
    stage("proposal", "complete" if worker_ok else "failed",
          f"Agent worker status {row['worker_status']}", api_calls=row["api_calls"])
    if not row["decision"]:
        for name in ("gateway", "execution", "observation", "drain", "verification"):
            stage(name, "unavailable", "No runtime event: the agent made no tool submission")
        raise RuntimeError("NO_RUNTIME_EVENT")
    stage("gateway", "complete", "Decision recorded in Ledger A before emission",
          decision=row["decision"], expected=row["expected_decision"])
    stage("execution", "complete", "Runtime claim recorded in Ledger A", claim=row["claim"])
    stage("observation", "complete",
          "Correlated observation paired by the verifier" if row["network_event_id"]
          else "No observation paired by the verifier", paired=bool(row["network_event_id"]))
    stage("drain", "complete", "Window closed and monitor health drained",
          window_seconds=WINDOW)
    stage("verification", "complete", "Verifier classified the attempt", result=row["result"],
          evidence_status=row["evidence_status"],
          labels=[s for s in row["labels"].split("|") if s])
    return row


def trust_run(evidence: Path, request: RunRequest, operator_id=None) -> bytes:
    from exfilscope.lab import Lab
    from exfilscope.privacy import routine_paths, scan_routine_files

    from .trust.demo import run_trust

    stage("preparation", "running", "Starting local receivers, TLS material and mitmdump")
    with Lab(evidence / request.protocol, request.protocol) as lab:
        stage("preparation", "complete", "Lab harness ready: receivers, monitor and ledgers",
              protocol=request.protocol)
        if request.operator_lifecycle:
            from .trust.lifecycle import run_lifecycle
            audit, rows = run_lifecycle(lab, WINDOW, stage, evidence.parent, operator_id)
            row = rows[-1]
        else:
            audit, row = run_trust(lab, WINDOW, stage, driver=request.trust_driver)
            rows = [row]
        leaks = scan_routine_files(routine_paths(lab.directory), lab.registry)
    if leaks:
        raise RuntimeError("ROUTINE_SYNTHETIC_EXPOSURE_DETECTED")
    if row is None:
        raise RuntimeError("NO_ACCEPTED_TRUST_ATTEMPT")
    stage("gateway", "complete", "Accepted attempt authorized by the research gateway",
          decision=row["decision"])
    stage("execution", "complete", "Runtime claim recorded in Ledger A")
    stage("observation", "complete",
          "Correlated observation paired by the verifier" if row["network_event_id"]
          else "No observation paired by the verifier", paired=bool(row["network_event_id"]))
    stage("drain", "complete", "Window closed and monitor health drained",
          window_seconds=WINDOW)
    stage("verification", "complete", "Verifier classified the accepted attempt",
          result=row["result"], evidence_status=row["evidence_status"])
    with (evidence / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerows(rows)
    return json.dumps(audit, indent=2).encode("utf-8")


def main() -> int:
    from .export import export_run

    try:
        config = json.loads(sys.stdin.read())
        run_id = config.pop("run_id")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise ValueError("INVALID_RUN_ID")
        operator_id = config.pop("operator_id", None)
        request = RunRequest.model_validate(config)
    except Exception:
        stage("environment", "failed", "INVALID_RUN_REQUEST")
        return 2
    run = RUNS / run_id
    evidence = run / "evidence"
    current = "environment"
    try:
        if not run.is_dir() or evidence.exists():
            raise FileExistsError("RUN_DIRECTORY_STATE_INVALID")
        stage("environment", "complete", "Run directory and request validated", run_id=run_id)
        current = "proposal"
        extra = None
        if request.mode == "lab":
            lab_run(evidence, request)
        elif request.mode == "trust":
            extra = {"trust-audit.json": trust_run(evidence, request, operator_id)}
        else:
            evidence.parent.mkdir(exist_ok=True)
            agent_run(evidence, request)
        current = "export"
        stage("export", "running", "Privacy scan and validated snapshot export")
        snapshot = export_run(run, run_id, request.scenario_id, request.mode, request.protocol,
                              request.claim_mode, extra)
        stage("export", "complete", "Snapshot validated and published",
              incidents=len(snapshot.incidents))
        return 0
    except Exception as exc:
        # Only the exception class and our own codes leave the process; the traceback goes
        # to the run's restricted folder because it may quote evidence content.
        restricted = run / "restricted"
        restricted.mkdir(parents=True, exist_ok=True)
        (restricted / "runner-traceback.txt").write_text(traceback.format_exc(),
                                                          encoding="utf-8")
        code = str(exc) if str(exc).isupper() and str(exc).replace("_", "").isalnum() \
            else type(exc).__name__
        stage(current, "failed", code)
        return 1


if __name__ == "__main__":
    sys.exit(main())
