"""Additive collection contract and scoped completeness checks; no absolute egress claim."""

import hashlib
import math
from collections import Counter
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from .canonical import canonical_bytes
from .contracts import Contract, Digest, Label, ObservedEvent
from .clock import ClockContext

ZERO_DIGEST = "0" * 64


class CollectionHealth(Contract):
    schema_version: str = "collection-1.1"
    run_id: UUID
    sequence: int = Field(ge=1)
    wall_time: float = Field(ge=0, allow_inf_nan=False)
    monotonic_time: float = Field(ge=0, allow_inf_nan=False)
    kind: Literal["START", "PULSE", "REQUEST", "CLIENT_OPEN", "CLIENT_CLOSE", "HEADERS",
                  "INCIDENT", "FAILURE", "STOP"]
    state: Literal["HEALTHY", "FAILED", "STOPPED"]
    request_count: int = Field(ge=0)
    open_clients: int = Field(ge=0)
    pending_requests: int = Field(ge=0)
    boundary_id: Digest
    key_id: Label
    canonicalization_version: Label = "rfc8785-0.1.4"
    reason: Label | None = None
    request_event_id: UUID | None = None
    request_digest: Digest | None = None
    previous_digest: Digest
    record_digest: Digest
    host_id: Label | None = None
    clock_domain_id: Label | None = None
    processed_through: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    committed_request_sequence: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def receipt_fields(self):
        has_receipt = self.request_event_id is not None and self.request_digest is not None
        if (self.kind == "REQUEST") != has_receipt:
            raise ValueError("INVALID_RECEIPT_FIELDS")
        if self.kind != "REQUEST" and (self.request_event_id or self.request_digest):
            raise ValueError("UNEXPECTED_RECEIPT_FIELDS")
        if (self.processed_through is None) != (self.committed_request_sequence is None):
            raise ValueError("INCOMPLETE_BARRIER")
        if self.processed_through is not None and (self.kind != "PULSE" or
                self.state != "HEALTHY" or self.open_clients or self.pending_requests or
                self.processed_through > self.monotonic_time):
            raise ValueError("INVALID_BARRIER")
        return self


def boundary_fingerprint(catalog, proxy_identity: str | None = None) -> str:
    return hashlib.sha256(canonical_bytes({"endpoints": catalog.endpoints,
                                          "routes": catalog.routes,
                                          "proxy_identity": proxy_identity,
                                          "collection": "collection-1.0"})).hexdigest()


def request_fingerprint(event: ObservedEvent) -> str:
    # Later response updates must not change the immutable request receipt.
    excluded = {"response_status"}
    if event.schema_version == "1.0":
        excluded.update({"request_monotonic", "host_id", "clock_domain_id"})
    return hashlib.sha256(canonical_bytes(event.model_dump(
        mode="json", exclude=excluded))).hexdigest()


def health_fingerprint(record: CollectionHealth) -> str:
    excluded = {"record_digest"}
    if record.schema_version == "collection-1.0":
        excluded.update({"host_id", "clock_domain_id", "processed_through",
                         "committed_request_sequence"})
    return hashlib.sha256(canonical_bytes(record.model_dump(
        mode="json", exclude=excluded))).hexdigest()


class HealthSequence:
    """Trusted producer state; advance only after an atomic durable append succeeds."""

    def __init__(self, boundary_id: str, key_id: str, clock: ClockContext | None = None):
        self.run_id = uuid4()
        self.sequence = 0
        self.previous_digest = ZERO_DIGEST
        self.request_count = 0
        self.boundary_id, self.key_id = boundary_id, key_id
        self.clock = clock or ClockContext.local()
        self.last_request_sequence = 0

    def prepare(self, *, wall: float, mono: float, kind: str, state: str,
                open_clients: int = 0, pending_requests: int = 0, reason: str | None = None,
                event: ObservedEvent | None = None, acknowledge: bool = False) -> CollectionHealth:
        record = CollectionHealth(run_id=self.run_id, sequence=self.sequence + 1,
                                  wall_time=wall, monotonic_time=mono, kind=kind, state=state,
                                  request_count=self.request_count + (event is not None),
                                  open_clients=open_clients, pending_requests=pending_requests,
                                  boundary_id=self.boundary_id, key_id=self.key_id, reason=reason,
                                  request_event_id=event.event_id if event else None,
                                  request_digest=request_fingerprint(event) if event else None,
                                  previous_digest=self.previous_digest, record_digest=ZERO_DIGEST,
                                  host_id=self.clock.host_id,
                                  clock_domain_id=self.clock.clock_domain_id,
                                  processed_through=mono if acknowledge else None,
                                  committed_request_sequence=self.last_request_sequence
                                  if acknowledge else None)
        return record.model_copy(update={"record_digest": health_fingerprint(record)})

    def committed(self, record: CollectionHealth) -> None:
        self.sequence, self.previous_digest = record.sequence, record.record_digest
        self.request_count = record.request_count
        if record.kind == "REQUEST":
            self.last_request_sequence = record.sequence


def assess_coverage(records: list[CollectionHealth], observed: list[ObservedEvent], *,
                    start: float, end: float, now: float, boundary_id: str | None,
                    key_id: str, max_gap: float = 1.0, clock_tolerance: float = 0.1,
                    host_id: str | None = None, clock_domain_id: str | None = None,
                    drain_grace: float = 1.0
                    ) -> tuple[str, ...]:
    """Qualify this one proxy boundary/window, under a trusted complete-hook assumption.

    Receipts detect withheld/corrupt request evidence; samples alone are insufficient.
    Sequence/hash chaining detects gaps, not malicious rewriting by a trusted writer.
    """
    if not all(math.isfinite(x) for x in (start, end, now, max_gap, clock_tolerance, drain_grace)) \
            or end <= start or max_gap <= 0 or clock_tolerance < 0 or drain_grace <= 0:
        return ("INVALID_COVERAGE_PARAMETERS",)
    if now < end:
        return ("INCOMPLETE_OBSERVATION_WINDOW",)
    if not boundary_id:
        return ("BOUNDARY_BINDING_UNAVAILABLE",)
    if not host_id or not clock_domain_id:
        return ("INCOMPATIBLE_CLOCK_DOMAIN",)
    groups = {}
    for record in records:
        groups.setdefault(record.run_id, []).append(record)
    spans = []
    def barriers(run):
        # The following committed record was prepared after the acknowledged pulse
        # commit returned. Its monotonic time bounds that pulse's durable commit.
        return [(i, r) for i, r in enumerate(run[:-1]) if r.processed_through is not None
                and r.processed_through >= end and run[i + 1].monotonic_time <= end + drain_grace
                and run[i + 1].monotonic_time <= now]
    for run in groups.values():
        run = sorted(run, key=lambda r: r.sequence)
        if run and run[0].monotonic_time <= start and barriers(run):
            spans.append(run)
    if len(spans) != 1:
        faults = ["NO_UNIQUE_MONITOR_COVERAGE", "MISSING_CLOSING_BARRIER"]
        if now >= end + drain_grace:
            faults.append("EVIDENCE_DRAIN_DEADLINE_EXPIRED")
        relevant = [r for r in records if start <= r.monotonic_time <= min(now, end + drain_grace)]
        if any(r.state != "HEALTHY" for r in relevant):
            faults.append("MONITOR_COLLECTION_FAILED_OR_STOPPED")
        if any(r.open_clients or r.pending_requests for r in relevant):
            faults.append("UNRESOLVED_INGRESS_AT_WINDOW_BOUNDARY")
        return tuple(faults)
    run = spans[0]
    # Assess the complete committed prefix through the first post-window closure.
    closing, closing_record = barriers(run)[0]
    prefix = run[:closing + 2]
    errors = []
    if prefix[0].kind != "START" or prefix[0].sequence != 1:
        errors.append("MISSING_MONITOR_START")
    if any(r.sequence != i + 1 for i, r in enumerate(prefix)):
        errors.append("HEALTH_SEQUENCE_GAP_OR_DUPLICATE")
    previous = ZERO_DIGEST
    receipts = []
    count = 0
    for r in prefix:
        if r.schema_version != "collection-1.1" or r.boundary_id != boundary_id \
                or r.key_id != key_id or r.canonicalization_version != "rfc8785-0.1.4":
            errors.append("INCOMPATIBLE_COLLECTION_CONTEXT")
        if r.host_id != host_id or r.clock_domain_id != clock_domain_id:
            errors.append("INCOMPATIBLE_CLOCK_DOMAIN")
        if r.previous_digest != previous or r.record_digest != health_fingerprint(r):
            errors.append("HEALTH_CHAIN_DIVERGENCE")
        previous = r.record_digest
        if r.kind == "REQUEST":
            receipts.append(r)
            count += 1
        if r.request_count != count:
            errors.append("REQUEST_COUNT_DIVERGENCE")
        if r.monotonic_time > now:
            errors.append("FUTURE_HEALTH_EVIDENCE")
    for left, right in zip(prefix, prefix[1:]):
        mono_delta = right.monotonic_time - left.monotonic_time
        if mono_delta < 0:
            errors.append("MONITOR_CLOCK_DISCONTINUITY")
        if left.monotonic_time <= end and right.monotonic_time >= start:
            if mono_delta > max_gap:
                errors.append("COLLECTION_HEALTH_GAP")
    opening = max((r for r in prefix if r.monotonic_time <= start), key=lambda r: r.sequence)
    relevant = [r for r in prefix if start <= r.monotonic_time <= closing_record.monotonic_time]
    expected_watermark = max((r.sequence for r in prefix[:closing + 1] if r.kind == "REQUEST"),
                             default=0)
    if closing_record.committed_request_sequence != expected_watermark:
        errors.append("UNRESOLVED_COMMIT_WATERMARK")
    if opening.state != "HEALTHY" or any(r.state != "HEALTHY" for r in relevant):
        errors.append("MONITOR_COLLECTION_FAILED_OR_STOPPED")
    if any(r.kind == "INCIDENT" for r in relevant):
        errors.append("UNOBSERVED_OR_UNSUPPORTED_INGRESS")
    if any(r.open_clients or r.pending_requests for r in (opening, closing_record)):
        errors.append("UNRESOLVED_INGRESS_AT_WINDOW_BOUNDARY")
    ids = Counter(event.event_id for event in observed)
    receipt_ids = Counter(r.request_event_id for r in receipts)
    if any(count != 1 for count in receipt_ids.values()):
        errors.append("DUPLICATE_REQUEST_RECEIPT")
    by_id = {event.event_id: event for event in observed}
    for receipt in receipts:
        if ids[receipt.request_event_id] != 1:
            errors.append("MISSING_OR_DUPLICATE_REQUEST_EVIDENCE")
        elif request_fingerprint(by_id[receipt.request_event_id]) != receipt.request_digest:
            errors.append("REQUEST_RECEIPT_DIVERGENCE")
    if any(e.request_monotonic is not None and start <= e.request_monotonic <= end
           and e.event_id not in receipt_ids for e in observed):
        errors.append("UNRECEIPTED_OBSERVATION")
    return tuple(dict.fromkeys(errors))


def assess_receipt(records: list[CollectionHealth], observed: list[ObservedEvent],
                   event: ObservedEvent, boundary_id: str | None) -> tuple[str, ...]:
    """Trust a positive observation separately from assurance of continuous absence.

    A gap/failure does not erase an already committed request. Missing/corrupt receipts
    still prevent attribution: the omitted event might be another trace candidate.
    """
    receipts = [r for r in records if r.request_event_id == event.event_id]
    if len(receipts) != 1 or not boundary_id:
        return ("UNRECEIPTED_OBSERVATION",)
    receipt = receipts[0]
    run = sorted((r for r in records if r.run_id == receipt.run_id), key=lambda r: r.sequence)
    errors = []
    previous, count = ZERO_DIGEST, 0
    ids = Counter(e.event_id for e in observed)
    by_id = {e.event_id: e for e in observed}
    if not run or run[0].kind != "START":
        errors.append("MISSING_MONITOR_START")
    for i, r in enumerate(run, 1):
        if r.sequence != i or r.previous_digest != previous or r.record_digest != health_fingerprint(r):
            errors.append("HEALTH_CHAIN_DIVERGENCE")
        previous = r.record_digest
        if r.schema_version != "collection-1.1" or r.boundary_id != boundary_id \
                or r.host_id != event.host_id or r.clock_domain_id != event.clock_domain_id:
            errors.append("INCOMPATIBLE_COLLECTION_CONTEXT")
        if r.kind == "REQUEST":
            count += 1
            if ids[r.request_event_id] != 1:
                errors.append("MISSING_OR_DUPLICATE_REQUEST_EVIDENCE")
            elif request_fingerprint(by_id[r.request_event_id]) != r.request_digest:
                errors.append("REQUEST_RECEIPT_DIVERGENCE")
        if r.request_count != count:
            errors.append("REQUEST_COUNT_DIVERGENCE")
        if i > 1 and r.monotonic_time < run[i - 2].monotonic_time:
            errors.append("MONITOR_CLOCK_DISCONTINUITY")
    if event.request_monotonic is None or not (
        run[0].monotonic_time <= event.request_monotonic <= receipt.monotonic_time
    ):
        errors.append("UNUSABLE_OBSERVATION_TIMESTAMP")
    if receipt.request_digest != request_fingerprint(event):
        errors.append("REQUEST_RECEIPT_DIVERGENCE")
    return tuple(dict.fromkeys(errors))
