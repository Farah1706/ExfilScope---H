from uuid import uuid4

import pytest

from exfilscope.contracts import Claim, Decision, Metadata, ObservedEvent, RuntimeEvent
from exfilscope.verifier import unmatched, verify
from test_health import BOUNDARY, CLOCK, history


def check(aa, bb, now=106):
    return verify(aa, bb, now=now, health=history(bb), expected_boundary_id=BOUNDARY, clock=CLOCK)


def pair(decision=Decision.ALLOW, claim=Claim.EXECUTED_SUCCESS):
    metadata = Metadata(endpoint_id="AUTHORIZED", route_id="COLLECT", method="POST")
    a = RuntimeEvent(session_id=uuid4(), proposed=metadata, decision=decision, reason="TEST",
                     permitted=metadata if decision != Decision.BLOCK else None,
                     payload_hmac="a" * 64 if decision != Decision.BLOCK else None,
                     key_id="key-1", claim=claim, decision_time=100.0,
                     decision_monotonic=100.0, completion_monotonic=102.0,
                     host_id=CLOCK.host_id, clock_domain_id=CLOCK.clock_domain_id)
    b = ObservedEvent(trace_id=a.trace_id, observed=metadata, payload_hmac="a" * 64,
                      key_id="key-1", request_time=101.0, request_monotonic=101.0,
                      host_id=CLOCK.host_id, clock_domain_id=CLOCK.clock_domain_id,
                      request_size=2)
    return a, b


@pytest.mark.parametrize("decision", [Decision.ALLOW, Decision.REDACT])
@pytest.mark.parametrize("claim", [Claim.EXECUTED_SUCCESS, Claim.EXECUTED_FAILED])
def test_observed_request_compatible_with_success_or_failure(decision, claim):
    a, b = pair(decision, claim)
    result = check([a], [b])[0]
    assert result.result == "MATCH" and result.evidence_status == "VERIFIED"


def test_block_bypass_precedes_payload_comparison():
    a, b = pair(Decision.BLOCK, Claim.NOT_EXECUTED)
    result = check([a], [b])[0]
    assert result.labels == ("BLOCK_BYPASS", "CLAIM_INCONSISTENCY")


def test_multiple_divergences_correlate_before_metadata():
    a, b = pair()
    b = b.model_copy(update={"observed": Metadata(endpoint_id="UNAUTHORIZED",
                                                 route_id="ALTERNATE", method="PUT"),
                             "payload_hmac": "b" * 64})
    result = check([a], [b])[0]
    assert result.network_event_id == b.event_id
    assert result.labels == ("DESTINATION_DIVERGENCE", "METHOD_ROUTE_DIVERGENCE",
                             "PAYLOAD_DIVERGENCE")


@pytest.mark.parametrize("decision", list(Decision))
@pytest.mark.parametrize("claim", list(Claim))
def test_absence_never_produces_false_match(decision, claim):
    a, _ = pair(decision, claim)
    result = verify([a], [], now=106)[0]
    assert result.evidence_status == "UNVERIFIED" and result.result != "MATCH"


@pytest.mark.parametrize("fault", ["duplicate_a", "duplicate_b", "missing_trace", "late",
                                   "early", "incomplete", "key", "canonical", "schema",
                                   "invalid_body", "anomaly"])
def test_unreliable_evidence_never_matches(fault):
    a, b = pair()
    events_a, events_b, now = [a], [b], 106
    if fault == "duplicate_a":
        events_a.append(a.model_copy(update={"event_id": uuid4()}))
    if fault == "duplicate_b":
        events_b.append(b.model_copy(update={"event_id": uuid4()}))
    if fault == "missing_trace":
        events_b = [b.model_copy(update={"trace_id": None})]
    if fault == "late":
        events_b = [b.model_copy(update={"request_time": 106.0, "request_monotonic": 106.0})]
    if fault == "early":
        events_b = [b.model_copy(update={"request_time": 99.0, "request_monotonic": 99.0})]
    if fault == "incomplete":
        now = 102
    if fault == "key":
        events_b = [b.model_copy(update={"key_id": "key-2"})]
    if fault == "canonical":
        events_b = [b.model_copy(update={"canonicalization_version": "other"})]
    if fault == "schema":
        events_b = [b.model_copy(update={"schema_version": "other"})]
    if fault == "invalid_body":
        events_b = [b.model_copy(update={"payload_hmac": None})]
    if fault == "anomaly":
        events_b = [b.model_copy(update={"anomalies": ("UNKNOWN_ROUTE",)})]
    result = check(events_a, events_b, now=now)[0]
    assert result.evidence_status == "UNVERIFIED" and result.result != "MATCH"


def test_claim_inconsistency_and_unmatched():
    a, b = pair(claim=Claim.NOT_EXECUTED)
    result = check([a], [b])[0]
    assert result.labels == ("CLAIM_INCONSISTENCY",)
    unknown = b.model_copy(update={"trace_id": uuid4()})
    assert unmatched([a], [unknown]) == [unknown]


def test_window_must_be_positive():
    with pytest.raises(ValueError):
        verify([], [], window=0)
