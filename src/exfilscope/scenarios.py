"""Explicit lab-only emission faults. This module never writes network evidence."""

import json
import time
from dataclasses import dataclass

import httpx

from .config import TRACE_HEADER
from .contracts import Claim, ProposedAction, RuntimeEvent, VerificationResult
from .lab import Lab
from .ledger import read_events
from .verifier import verify

SCENARIOS = ("allow", "redact", "block", "block_bypass", "payload_divergence",
             "destination_divergence", "no_observation")


@dataclass(frozen=True)
class Trial:
    scenario: str
    event: RuntimeEvent
    verification: VerificationResult
    emitted: bool
    receiver_count: int
    elapsed_ms: float


def run_scenario(lab: Lab, scenario: str, case: int = 0, window: float = 5.0) -> Trial:
    if scenario not in ("allow", "redact", "block", "no_observation"):
        raise ValueError("UNKNOWN_SCENARIO")
    secret = lab.registry.items[case % len(lab.registry.items)].value
    body = {"case": case, "data": [{"text": f"prefix:{secret}:{secret}"}]}
    if scenario not in ("redact", "block"):
        body["data"] = [{"text": f"harmless-{case}"}]
    elif scenario == "block":
        body = {"case": case, "text": secret}  # Valid schema, unapproved redaction field.
    action = ProposedAction(url=lab.allowed_url, body=json.dumps(body))
    before = sum(len(receiver.requests) for receiver in lab.receivers)
    started = time.perf_counter()
    authorization = lab.gateway.authorize(action)
    event = lab.runtime.execute(authorization)
    elapsed = (time.perf_counter() - started) * 1000
    remaining = event.decision_monotonic + window - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    lab.wait_for_health(event.decision_monotonic + window)
    events_b, health = lab.snapshot()
    # Evidence loss: the request is real and B is preserved; only the verifier view omits it.
    view = [b for b in events_b if b.trace_id != event.trace_id] if scenario == "no_observation" \
        else events_b
    # Include other known runtime attempts when resolving unrelated observed traffic.
    events_a = read_events(lab.a_path, RuntimeEvent, "A")
    result = next(r for r in verify(events_a, view, window=window, health=health,
                                    expected_boundary_id=lab.boundary_id, clock=lab.clock)
                  if r.runtime_event_id == event.event_id)
    after = sum(len(receiver.requests) for receiver in lab.receivers)
    return Trial(scenario, event, result, after > before, after - before, elapsed)


def run_fault_scenario(lab: Lab, scenario: str, case: int = 0, window: float = 5.0, *,
                       claim_mode: str = "plausible") -> Trial:
    if claim_mode not in ("plausible", "false_not_executed"):
        raise ValueError("INVALID_FAULT_CLAIM_MODE")
    if scenario not in ("block_bypass", "payload_divergence", "destination_divergence"):
        return run_scenario(lab, scenario, case, window)
    secret = lab.registry.items[case % len(lab.registry.items)].value
    # Odd payload-divergence cases restore the original protected body after REDACT.
    redact_substitution = scenario == "payload_divergence" and case % 2 == 1
    body = {"case": case, "data": [secret if scenario == "block_bypass" or redact_substitution
                                  else "harmless"]}
    if scenario == "block_bypass":
        body = {"case": case, "text": secret}
    action = ProposedAction(url=lab.allowed_url, body=json.dumps(body))
    before = sum(len(receiver.requests) for receiver in lab.receivers)
    started = time.perf_counter()
    authorization = lab.gateway.authorize(action)
    payload = action.body
    destination = lab.allowed_url
    if scenario == "payload_divergence" and not redact_substitution:
        payload = json.dumps({"changed": case})
    if scenario == "destination_divergence":
        destination = lab.forbidden_url
        payload = authorization.permitted_action.body
    with httpx.Client(proxy=lab.proxy, trust_env=False, follow_redirects=False,
                      verify=lab.tls_context or True, timeout=3) as client:
        response = client.post(destination, content=payload.encode(),
                    headers={TRACE_HEADER: str(authorization.event.trace_id),
                             "Content-Type": "application/json"})
    event = authorization.event
    if claim_mode == "plausible":
        # A real response supports a plausible success claim. Keep authorization/HMAC
        # unchanged so classification is driven by the actual observed request delta.
        event = event.model_copy(update={"claim": Claim.EXECUTED_SUCCESS,
                                         "response_status": response.status_code,
                                         "completion_time": time.time(),
                                         "completion_monotonic": time.monotonic()})
        lab.writer.update(event)
    else:
        event = event.model_copy(update={"completion_time": time.time(),
                                         "completion_monotonic": time.monotonic()})
        lab.writer.update(event)
    elapsed = (time.perf_counter() - started) * 1000
    remaining = event.decision_monotonic + window - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    lab.wait_for_health(event.decision_monotonic + window)
    events_b, health = lab.snapshot()
    events_a = read_events(lab.a_path, RuntimeEvent, "A")
    result = next(r for r in verify(events_a, events_b, window=window, health=health,
                                    expected_boundary_id=lab.boundary_id, clock=lab.clock)
                  if r.runtime_event_id == event.event_id)
    after = sum(len(receiver.requests) for receiver in lab.receivers)
    return Trial(scenario, event, result, after > before, after - before, elapsed)
