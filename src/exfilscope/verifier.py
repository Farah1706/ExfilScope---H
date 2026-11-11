"""Trace/monotonic correlation, independently supported findings, scoped absence."""

import hmac
import math
import time
from collections import Counter

from .contracts import Claim, Decision, ObservedEvent, RuntimeEvent, VerificationResult
from .health import CollectionHealth, assess_coverage, assess_receipt
from .clock import ClockContext


def same_clock(a, b) -> bool:
    return bool(a.host_id and a.clock_domain_id and a.host_id == b.host_id
                and a.clock_domain_id == b.clock_domain_id)


def verify(events_a: list[RuntimeEvent], events_b: list[ObservedEvent], *, window: float = 5.0,
           now: float | None = None, health: list[CollectionHealth] | None = None,
           expected_boundary_id: str | None = None,
           max_health_gap: float = 1.0, drain_grace: float = 1.0,
           clock: ClockContext | None = None) -> list[VerificationResult]:
    """`now`, W, and G use the configured host monotonic domain; wall time is display only.

    Positive attribution requires a committed, integrity-checked request receipt.
    MATCH additionally requires complete window coverage and a closing acknowledgement.
    Supported divergence survives unavailable comparisons/coverage, never bad pairing.
    """
    if not math.isfinite(window) or window <= 0 or not math.isfinite(drain_grace) or drain_grace <= 0:
        raise ValueError("INVALID_WINDOW")
    now = time.monotonic() if now is None else now
    clock = clock or ClockContext.local()
    if not math.isfinite(now):
        raise ValueError("INVALID_VERIFICATION_TIME")
    counts_a = Counter(e.trace_id for e in events_a)
    counts_b = Counter(e.trace_id for e in events_b)
    results = []
    for event in events_a:
        diagnostics, pairing_errors, labels = [], [], []
        start = event.decision_monotonic
        same_id = [b for b in events_b if b.trace_id == event.trace_id]
        if event.schema_version != "1.1" or start is None or not math.isfinite(start) \
                or not same_clock(clock, event):
            pairing_errors.append("INCOMPATIBLE_CLOCK_DOMAIN")
        end = start + window if start is not None else now + window
        candidates = [b for b in same_id if same_clock(event, b)
                      and b.request_monotonic is not None and start is not None
                      and start <= b.request_monotonic <= end]
        if counts_a[event.trace_id] != 1:
            pairing_errors.append("DUPLICATE_RUNTIME_TRACE")
        if len(candidates) > 1:
            pairing_errors.append("DUPLICATE_NETWORK_TRACE")
        if any(not same_clock(event, b) or b.request_monotonic is None for b in same_id):
            pairing_errors.append("INCOMPATIBLE_CLOCK_DOMAIN")
        if len(same_id) != len(candidates):
            diagnostics.append("OUTSIDE_OBSERVATION_WINDOW")
            if event.decision == Decision.BLOCK:
                diagnostics.append("LATE_OR_UNUSABLE_BLOCK_ACTIVITY")
        if event.completion_monotonic is None or event.completion_monotonic < (start or 0):
            diagnostics.append("INCOMPLETE_RUNTIME_EVIDENCE")
        elif event.completion_monotonic > now:
            diagnostics.append("FUTURE_RUNTIME_EVIDENCE")
        coverage = assess_coverage(health, events_b, start=start, end=end, now=now,
                                  boundary_id=expected_boundary_id, key_id=event.key_id,
                                  max_gap=max_health_gap, host_id=event.host_id,
                                  clock_domain_id=event.clock_domain_id, drain_grace=drain_grace
                                  ) if health is not None and start is not None else (
                                      "MONITOR_COVERAGE_UNPROVEN",)
        diagnostics.extend(coverage)
        if now < end:
            diagnostics.append("INCOMPLETE_OBSERVATION_WINDOW")

        if event.decision == Decision.BLOCK and not candidates:
            if event.claim != Claim.NOT_EXECUTED:
                diagnostics.append("INVALID_BLOCK_EXECUTION_CLAIM")
            if same_id:
                diagnostics.append("LATE_OR_UNUSABLE_BLOCK_ACTIVITY")
            for b in events_b:
                if not same_clock(event, b) or b.request_monotonic is None:
                    diagnostics.append("INCOMPATIBLE_CLOCK_DOMAIN")
                elif start is not None and start <= b.request_monotonic <= end:
                    if b.trace_id is None:
                        diagnostics.append("UNATTRIBUTED_TRAFFIC")
                    elif b.anomalies or counts_a[b.trace_id] != 1 or counts_b[b.trace_id] != 1:
                        diagnostics.append("UNRESOLVED_CORRELATION_IN_WINDOW")
                    else:
                        other = next(a for a in events_a if a.trace_id == b.trace_id)
                        if not same_clock(other, b) or other.decision_monotonic is None or not (
                            other.decision_monotonic <= b.request_monotonic
                            <= other.decision_monotonic + window
                        ):
                            diagnostics.append("UNRESOLVED_CORRELATION_IN_WINDOW")
            if not diagnostics and not pairing_errors:
                results.append(VerificationResult(runtime_event_id=event.event_id, result="MATCH",
                    evidence_status="VERIFIED", diagnostics=("SCOPED_PROXY_ABSENCE",)))
                continue

        if len(candidates) != 1:
            pairing_errors.append("NO_UNIQUE_CORRELATED_OBSERVATION")
        observed = candidates[0] if len(candidates) == 1 else None
        if observed:
            if observed.request_monotonic > now:
                pairing_errors.append("FUTURE_OBSERVATION")
            if observed.schema_version != "1.1":
                pairing_errors.append("INCOMPATIBLE_EVIDENCE_VERSIONS")
            if any(a in ("MISSING_OR_DUPLICATE_TRACE", "INVALID_TRACE") for a in observed.anomalies):
                pairing_errors.append("UNUSABLE_TRACE")
            pairing_errors.extend(assess_receipt(health, events_b, observed, expected_boundary_id)
                                  if health is not None else ("OBSERVATION_PROVENANCE_UNPROVEN",))
        diagnostics.extend(pairing_errors)
        if observed and not pairing_errors:
            diagnostics.extend(observed.anomalies)
            compatible = (event.key_id == observed.key_id and
                          event.canonicalization_version == observed.canonicalization_version
                          == "rfc8785-0.1.4")
            if not compatible:
                diagnostics.append("INCOMPATIBLE_EVIDENCE_VERSIONS")
            if event.decision == Decision.BLOCK:
                labels.append("BLOCK_BYPASS")
            else:
                if event.permitted is None:
                    diagnostics.append("INCOMPLETE_COMPARISON_EVIDENCE")
                else:
                    if event.permitted.endpoint_id != observed.observed.endpoint_id:
                        labels.append("DESTINATION_DIVERGENCE")
                    if (event.permitted.method != observed.observed.method or
                            event.permitted.route_id != observed.observed.route_id):
                        labels.append("METHOD_ROUTE_DIVERGENCE")
                if not event.payload_hmac or not observed.payload_hmac:
                    diagnostics.append("INCOMPLETE_COMPARISON_EVIDENCE")
                elif compatible and not hmac.compare_digest(event.payload_hmac, observed.payload_hmac):
                    labels.append("PAYLOAD_DIVERGENCE")
            if event.claim == Claim.NOT_EXECUTED:
                labels.append("CLAIM_INCONSISTENCY")
        diagnostics = tuple(dict.fromkeys(diagnostics))
        result = "MISMATCH" if labels else "UNVERIFIED" if diagnostics else "MATCH"
        results.append(VerificationResult(runtime_event_id=event.event_id,
            network_event_id=observed.event_id if observed and not pairing_errors else None,
            result=result, evidence_status="UNVERIFIED" if diagnostics else "VERIFIED",
            labels=tuple(labels) if labels else ("NO_CORRELATED_OBSERVATION",)
            if "NO_UNIQUE_CORRELATED_OBSERVATION" in diagnostics else (), diagnostics=diagnostics))
    return results


def unmatched(events_a: list[RuntimeEvent], events_b: list[ObservedEvent]) -> list[ObservedEvent]:
    """Unmatched traffic stays available for review without similarity-based attribution."""
    ids = {event.trace_id for event in events_a}
    return [event for event in events_b if event.trace_id not in ids]
