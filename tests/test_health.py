"""Unit health histories are fixtures, never presented as real monitor observations."""

import sqlite3
from uuid import uuid4

import pytest

from exfilscope.contracts import Claim, Decision, Metadata, ObservedEvent, RuntimeEvent
from exfilscope.health import HealthSequence, assess_coverage, health_fingerprint
from exfilscope.ledger import MonitorWriter, read_monitor_snapshot
from exfilscope.verifier import verify
from exfilscope.clock import ClockContext

BOUNDARY = "b" * 64
CLOCK = ClockContext(host_id="UNIT_HOST", clock_domain_id="unit-clock")


def runtime(decision=Decision.BLOCK, claim=Claim.NOT_EXECUTED):
    metadata = Metadata(endpoint_id="AUTHORIZED", route_id="COLLECT", method="POST")
    return RuntimeEvent(session_id=uuid4(), proposed=metadata, decision=decision, reason="TEST",
                        permitted=metadata if decision != Decision.BLOCK else None,
                        payload_hmac="a" * 64 if decision != Decision.BLOCK else None,
                        key_id="key-1", claim=claim, decision_time=100.0,
                        decision_monotonic=100.0, completion_monotonic=102.0,
                        host_id=CLOCK.host_id, clock_domain_id=CLOCK.clock_domain_id)


def observation(event, **changes):
    result = ObservedEvent(trace_id=event.trace_id, observed=event.proposed, payload_hmac="a" * 64,
                           key_id="key-1", request_time=101.0, request_monotonic=101.0,
                           host_id=CLOCK.host_id, clock_domain_id=CLOCK.clock_domain_id,
                           request_size=2)
    return result.model_copy(update=changes)


def history(events=(), *, failure=False, incident=False, gap=False, clock=False,
            clients=0, pending=0):
    producer = HealthSequence(BOUNDARY, "key-1", CLOCK)
    records = []
    times = [99.0 + i / 4 for i in range(29)]
    if gap:
        times = [99.0, 100.0, 101.0, 103.0, 105.5, 106.0]
    for index, timestamp in enumerate(times):
        state = "FAILED" if failure and timestamp >= 102 else "HEALTHY"
        mono = timestamp - (3 if clock and timestamp >= 102 else 0)
        record = producer.prepare(wall=timestamp, mono=mono,
                                  kind="START" if index == 0 else
                                  "INCIDENT" if incident and timestamp == 102 else "PULSE",
                                  state=state, open_clients=clients, pending_requests=pending,
                                  acknowledge=index != 0 and not (incident and timestamp == 102)
                                  and state == "HEALTHY" and not clients and not pending)
        records.append(record)
        producer.committed(record)
        for event in events:
            if timestamp == event.request_time:
                record = producer.prepare(wall=timestamp, mono=mono, kind="REQUEST", state=state,
                                          event=event, open_clients=clients,
                                          pending_requests=pending)
                records.append(record)
                producer.committed(record)
    return records


def verdict(a, b, records):
    return verify(a, b, health=records, expected_boundary_id=BOUNDARY, now=106, clock=CLOCK)[0]


def test_block_match_is_explicitly_scoped_and_requires_health():
    a = runtime()
    result = verdict([a], [], history())
    assert result.result == "MATCH" and result.evidence_status == "VERIFIED"
    assert result.diagnostics == ("SCOPED_PROXY_ABSENCE",)
    assert verify([a], [], now=106)[0].evidence_status == "UNVERIFIED"
    assert verify([a], [], now=106, health=history())[0].evidence_status == "UNVERIFIED"


@pytest.mark.parametrize("opening_clients,expected", [(0, "MATCH"), (1, "UNVERIFIED")])
def test_matching_failed_request_still_requires_idle_opening(opening_clients, expected):
    # Unit histories, not network evidence: model the retained timeout failure's
    # prior connection crossing the authorization boundary, then closing inside W.
    a = runtime(Decision.ALLOW, Claim.EXECUTED_FAILED)
    b = observation(a)
    producer = HealthSequence(BOUNDARY, a.key_id, CLOCK)
    records = []
    for source in history([b]):
        clients = opening_clients if 99.75 <= source.monotonic_time <= 100 else 0
        record = producer.prepare(
            wall=source.wall_time, mono=source.monotonic_time, kind=source.kind,
            state=source.state, open_clients=clients, pending_requests=0,
            event=b if source.kind == "REQUEST" else None,
            acknowledge=source.processed_through is not None and not clients)
        records.append(record)
        producer.committed(record)
    result = verdict([a], [b], records)
    assert result.result == expected
    assert result.network_event_id == b.event_id
    assert result.labels == ()
    assert result.diagnostics == (() if not opening_clients else
                                  ("UNRESOLVED_INGRESS_AT_WINDOW_BOUNDARY",))


@pytest.mark.parametrize("fault", ["missing_start", "missing_pulse", "duplicate_pulse", "no_close",
                                   "failure", "incident", "gap", "clock", "clients", "pending",
                                   "boundary", "key", "hash", "restart", "future"])
def test_coverage_faults_never_produce_block_match(fault):
    a, records = runtime(), history()
    if fault == "missing_start":
        records = records[1:]
    elif fault == "missing_pulse":
        records.pop(8)
    elif fault == "duplicate_pulse":
        records.insert(8, records[8])
    elif fault == "no_close":
        records = [r for r in records if r.wall_time < 105]
    elif fault in ("failure", "incident", "gap", "clock"):
        records = history(**{fault: True})
    elif fault in ("clients", "pending"):
        records = history(**{fault: 1})
    elif fault in ("boundary", "key", "hash"):
        name = {"boundary": "boundary_id", "key": "key_id", "hash": "record_digest"}[fault]
        records[8] = records[8].model_copy(update={name: "c" * 64})
    elif fault == "restart":
        other = history()
        records = [r for r in records if r.wall_time < 102] + \
            [r for r in other if r.wall_time >= 102]
    elif fault == "future":
        records[-5] = records[-5].model_copy(update={"monotonic_time": 107.0})
    result = verdict([a], [], records)
    assert result.result != "MATCH" and result.evidence_status == "UNVERIFIED"


@pytest.mark.parametrize("fault", ["withheld", "changed", "duplicated", "unreceipted"])
def test_request_receipts_detect_incomplete_or_changed_evidence(fault):
    a = runtime(Decision.ALLOW, Claim.EXECUTED_SUCCESS)
    b = observation(a)
    records, view = history([b]), [b]
    if fault == "withheld":
        view = []
    elif fault == "changed":
        view = [b.model_copy(update={"payload_hmac": "d" * 64})]
    elif fault == "duplicated":
        view = [b, b]
    else:
        records = history()
    result = verdict([a], view, records)
    assert result.result != "MATCH" and result.evidence_status == "UNVERIFIED"


@pytest.mark.parametrize("fault", ["unknown_trace", "missing_trace", "duplicate_trace",
                                   "metadata_anomaly", "late_other_runtime"])
def test_ambiguous_other_traffic_invalidates_block_absence(fault):
    a, other = runtime(), runtime(Decision.ALLOW, Claim.EXECUTED_SUCCESS)
    b = observation(other)
    aa, bb = [a, other], [b]
    if fault == "unknown_trace":
        aa = [a]
    elif fault == "missing_trace":
        bb = [b.model_copy(update={"trace_id": None})]
    elif fault == "duplicate_trace":
        bb.append(b.model_copy(update={"event_id": uuid4(), "request_time": 101.25,
                                        "request_monotonic": 101.25}))
    elif fault == "metadata_anomaly":
        bb = [b.model_copy(update={"anomalies": ("UNKNOWN_ROUTE",)})]
    elif fault == "late_other_runtime":
        aa = [a, other.model_copy(update={"decision_monotonic": 102.0})]
    result = verdict(aa, bb, history(bb))
    assert result.result != "MATCH" and result.evidence_status == "UNVERIFIED"


def test_known_independent_traffic_does_not_invalidate_scoped_absence():
    a, other = runtime(), runtime(Decision.ALLOW, Claim.EXECUTED_SUCCESS)
    b = observation(other)
    results = verify([a, other], [b], health=history([b]), expected_boundary_id=BOUNDARY, now=106,
                     clock=CLOCK)
    assert all(r.result == "MATCH" for r in results)


def test_plausible_success_divergence_does_not_require_false_claim():
    a = runtime(Decision.ALLOW, Claim.EXECUTED_SUCCESS)
    b = observation(a, payload_hmac="d" * 64,
                    observed=Metadata(endpoint_id="UNAUTHORIZED", route_id="COLLECT", method="POST"))
    result = verdict([a], [b], history([b]))
    assert result.labels == ("DESTINATION_DIVERGENCE", "PAYLOAD_DIVERGENCE")
    assert result.evidence_status == "VERIFIED"


def test_invalid_block_success_claim_never_matches_absence():
    result = verdict([runtime(claim=Claim.EXECUTED_SUCCESS)], [], history())
    assert "INVALID_BLOCK_EXECUTION_CLAIM" in result.diagnostics
    assert result.evidence_status == "UNVERIFIED"


def test_block_bypass_plausible_success_is_block_bypass_only():
    a = runtime(claim=Claim.EXECUTED_SUCCESS)
    b = observation(a)
    assert verdict([a], [b], history([b])).labels == ("BLOCK_BYPASS",)


def test_atomic_receipt_failure_rolls_back_observed_event(tmp_path):
    writer = MonitorWriter(tmp_path / "b.sqlite")
    producer = HealthSequence(BOUNDARY, "key-1")
    start = producer.prepare(wall=99.0, mono=9.0, kind="START", state="HEALTHY")
    writer.append_health(start)
    producer.committed(start)
    event = observation(runtime())
    receipt = producer.prepare(wall=101.0, mono=11.0, kind="REQUEST", state="HEALTHY", event=event)
    # Colliding health sequence proves event insert and receipt insert are transactional.
    with pytest.raises(sqlite3.IntegrityError):
        writer.record_observation(event, receipt.model_copy(update={"sequence": 1}))
    observed, records = read_monitor_snapshot(writer.path)
    assert observed == [] and records == [start]
    with pytest.raises(ValueError):
        writer.record_observation(event, receipt.model_copy(update={"request_digest": "d" * 64}))


def test_coverage_uses_monotonic_gap_and_validates_parameters():
    errors = assess_coverage(history(gap=True), [], start=100, end=105, now=106,
                             boundary_id=BOUNDARY, key_id="key-1",
                             host_id=CLOCK.host_id, clock_domain_id=CLOCK.clock_domain_id)
    assert "COLLECTION_HEALTH_GAP" in errors
    assert assess_coverage([], [], start=100, end=105, now=106, boundary_id=BOUNDARY,
                           key_id="key-1", max_gap=float("nan")) == ("INVALID_COVERAGE_PARAMETERS",)
    with pytest.raises(ValueError):
        verify([], [], window=float("nan"))


def test_response_status_is_excluded_from_immutable_request_receipt():
    a = runtime(Decision.ALLOW, Claim.EXECUTED_SUCCESS)
    b = observation(a)
    assert verdict([a], [b.model_copy(update={"response_status": 200})], history([b])).result == "MATCH"
    assert all(r.record_digest == health_fingerprint(r) for r in history([b]))
