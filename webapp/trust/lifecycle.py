"""Operator-driven sandbox lifecycle. All authority dies with this runner process."""

import re
import time

from webapp.government_data import load_snapshot
from webapp.runs import read_json

from .capability import AgentIdentity, Issuer, Validator, fingerprint
from .demo import (AGENT_ID, PILOT_TASK, SCHEMA, SELECTION_CHECKS, execute_attempt,
                   grounded_proposal, pilot_mandate)
from .dispatch import ProtectedDispatch

WAIT_SECONDS = 90


def wait_command(run, operation, actor, stage, **facts):
    state = {"authorize": "WAITING_AUTHORIZATION", "revoke": "WAITING_REVOCATION",
             "recover": "WAITING_RECOVERY"}[operation]
    stage("gateway", "running", "Awaiting authenticated operator decision",
          operator_state=state, **facts)
    path = run / ("operator-" + operation + ".json")
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if path.is_file():
            command = read_json(path)
            if (not isinstance(command, dict) or set(command) != {"operation", "actor", "at"}
                    or command["operation"] != operation or command["actor"] != actor
                    or type(command["at"]) not in (int, float)
                    or not 0 < command["at"] <= time.time() + 1):
                raise RuntimeError("OPERATOR_COMMAND_INVALID")
            return command
        time.sleep(0.1)
    raise RuntimeError("OPERATOR_DECISION_TIMED_OUT")


def run_lifecycle(lab, window, stage, run, actor):
    if not isinstance(actor, str) or not re.fullmatch(r"local-session-[0-9a-f]{16}", actor):
        raise RuntimeError("OPERATOR_SESSION_REQUIRED")
    issuer = Issuer()
    validator = Validator(issuer.public_key)
    agent = AgentIdentity(AGENT_ID)
    validator.register(agent.agent_id, agent.public_key)
    mandate = pilot_mandate()
    dispatch = ProtectedDispatch(lab, validator, PILOT_TASK, body_check=mandate.check)
    reference = load_snapshot().rows[-1]
    results, rows, model_seconds, operations = [], [], [], []

    def record_operation(operation, identity, **facts):
        command = wait_command(run, operation, actor, stage, **facts)
        operations.append({**command, "agent_key_fingerprint": fingerprint(identity.public_key)})

    def proposal():
        stage("proposal", "running", "Qwen3 selecting cells from the approved GDRFA data")
        action, details, seconds = grounded_proposal("AUTHORIZED", mandate)
        model_seconds.append(round(seconds, 4))
        stage("proposal", "complete", "Qwen3 selection inside the official-data mandate")
        return details, action

    def attempt(title, identity, cap, action, selection=None):
        outcome, row = execute_attempt(lab, window, dispatch, len(results), title, cap,
                                       identity.prove(cap, action), action)
        if selection:
            outcome.update(selection, selection_checks=SELECTION_CHECKS)
            if outcome["trust"] == "ACCEPTED":
                outcome["grounding_checks"] = mandate.check(action["body"])
        results.append(outcome)
        if row:
            rows.append(row)
        return outcome

    stage("proposal", "running", "Public data loaded; authority requires local operator approval",
          task=PILOT_TASK.task)
    record_operation("authorize", agent)
    cap = issuer.issue(agent.agent_id, agent.public_key, PILOT_TASK, lifetime=300)
    reserve = issuer.issue(agent.agent_id, agent.public_key, PILOT_TASK, lifetime=300)
    selected, action = proposal()
    initial = attempt("Operator approved Qwen3 pilot brief", agent, cap, action, selected)

    record_operation("revoke", agent, operator_verdict=initial.get("verification", "UNVERIFIED"),
                     receiver_requests=initial["receiver_requests"],
                     initial_receiver_requests=initial["receiver_requests"])
    validator.revoke(agent.agent_id)
    stage("gateway", "running", "Registered agent authority revoked",
          operator_state="REVOCATION_APPLIED", operator_code="AGENT_REVOKED")
    selected, next_action = proposal()
    withdrawn = attempt("Unused signed authority after revocation", agent, reserve,
                        next_action, selected)
    attempt("Previously used authority after revocation", agent, cap, action)
    if withdrawn.get("code") != "AGENT_REVOKED" or withdrawn["receiver_requests"] != 0:
        raise RuntimeError("REVOCATION_CONTROL_FAILED")

    replacement = AgentIdentity("gov-service-assistant-02")
    record_operation("recover", replacement, operator_code=withdrawn["code"],
                     receiver_requests=withdrawn["receiver_requests"])
    validator.register(replacement.agent_id, replacement.public_key)
    fresh = issuer.issue(replacement.agent_id, replacement.public_key, PILOT_TASK, lifetime=300)
    selected, recovery_action = proposal()
    recovered = attempt("New identity and newly approved Qwen3 authority", replacement,
                        fresh, recovery_action, selected)
    still_revoked = attempt("Original identity remains revoked after recovery", agent,
                            reserve, next_action)
    if recovered["trust"] != "ACCEPTED" or still_revoked.get("code") != "AGENT_REVOKED":
        raise RuntimeError("RECOVERY_CONTROL_FAILED")
    stage("gateway", "running", "Lifecycle completed with original identity still revoked",
          operator_state="RECOVERED", operator_code=still_revoked["code"])
    return {
        "schema_version": SCHEMA, "agent_id": agent.agent_id, "driver": "qwen3",
        "model_seconds": model_seconds, "official_reference": reference.model_dump(),
        "data_mandate": mandate.describe(),
        "agent_key_fingerprint": fingerprint(agent.public_key),
        "issuer_key_fingerprint": fingerprint(issuer.public_key),
        "task": PILOT_TASK.__dict__, "attempts": results, "operator_events": operations,
        "custody": "Ephemeral keys and revocation state live in the isolated runner process. "
                   "Operator identity denotes the local launch session, not a government credential.",
        "scope_note": "Withdrawal blocks subsequent protected dispatches. It does not cancel "
                      "in-flight traffic. Recovery enrolls a new identity; restart requires new approval."
    }, rows
