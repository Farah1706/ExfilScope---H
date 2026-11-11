"""Strict schema for the trust audit published with a trust run (``trust-audit-1.0``)."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from uuid import UUID

from pydantic import Field, StringConstraints

from dashboard.evidence import Code, Strict, read_json
from datetime import date

from webapp.gdrfa_statistics import APPROVED_DIGEST, load_statistics
from webapp.government_data import ResidenceRow
from .grounding import BINDING, CHECKS
from .model import Citation, Notice, Selection

Text = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9 ,.:;()/'-]{1,240}$")]
Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]


class Grant(Strict):
    agent_id: Token
    task: Token
    jti: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}$")]
    expires_in_s: float


class CitedCell(Citation):
    value: int = Field(gt=0)


class Attempt(Strict):
    attempt: int = Field(ge=1, le=16)
    title: Text
    requested_endpoint: Literal["AUTHORIZED", "UNAUTHORIZED"]
    trust: Literal["ACCEPTED", "REJECTED"]
    code: Code
    gateway: Literal["ALLOW", "REDACT", "BLOCK", "NOT_CALLED"]
    receiver_requests: int = Field(ge=0)
    runtime_event_id: UUID | None = None
    network_event_id: UUID | None = None
    model_selection: Notice | Selection | None = None
    selection_checks: list[Literal["YEAR_MATCH", "COUNT_MATCH", "ENDPOINT_MATCH", "YEARS_IN_MANDATE",
                                   "METRICS_IN_MANDATE"]] = Field(default_factory=list)
    citations: list[CitedCell] = Field(default_factory=list, max_length=3)
    grounding_checks: list[Literal["SOURCE_DIGEST_MATCH", "CELLS_IN_MANDATE",
                                   "NO_UNGROUNDED_NUMBERS", "SOURCE_AND_PAYLOAD_BOUND"]] = Field(default_factory=list)
    fixture: Literal["ALTERED_FIGURE"] | None = None
    grant: Grant | None = None
    verification: Literal["MATCH", "MISMATCH", "UNVERIFIED"] | None = None
    labels: list[Code] = []
    trace_prefix: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{8}$")] | None = None
    proposed_action_hmac: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None
    runtime_claim: Literal["EXECUTED_SUCCESS", "EXECUTED_FAILED", "NOT_EXECUTED"] | None = None
    observation_paired: bool | None = None


class Task(Strict):
    task: Token
    tool: Token
    endpoint_id: Token
    method: Literal["POST"]
    route_id: Token


class OperatorEvent(Strict):
    operation: Literal["authorize", "revoke", "recover"]
    actor: Annotated[str, StringConstraints(pattern=r"^local-session-[0-9a-f]{16}$")]
    at: float = Field(gt=0, allow_inf_nan=False)
    agent_key_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]


class DataMandateRecord(Strict):
    publisher: Literal["GDRFA Dubai"]
    dataset: Text
    classification: Literal["OPEN_AGGREGATE"]
    years: list[int] = Field(min_length=1, max_length=8)
    metrics: list[Token] = Field(min_length=1, max_length=5)
    digest: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    retrieved: date
    binding: Literal["structured-cells-v1"] | None = None


class TrustAudit(Strict):
    schema_version: Literal["trust-audit-1.0"]
    agent_id: Token
    agent_key_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    issuer_key_fingerprint: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16}$")]
    task: Task
    driver: Literal["scripted", "qwen3"] = "scripted"
    model_seconds: list[float] = Field(default_factory=list)
    attempts: list[Attempt] = Field(min_length=1)
    custody: Text
    scope_note: Text
    official_reference: ResidenceRow | None = None
    operator_events: list[OperatorEvent] = Field(default_factory=list)
    data_mandate: DataMandateRecord | None = None


def load_trust_audit(export: Path) -> TrustAudit:
    manifest = json.loads(read_json(export / "manifest.json"))
    expected = manifest["files"].get("trust-audit.json")
    data = read_json(export / "trust-audit.json")
    if not expected or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("TRUST_AUDIT_HASH_MISMATCH")
    audit = TrustAudit.model_validate_json(data)
    from webapp.evidence import load_run_snapshot

    snapshot = load_run_snapshot(export)
    incidents = {i.runtime.event_id: i for i in snapshot.incidents}
    stats = load_statistics() if audit.data_mandate else None
    if audit.data_mandate and audit.data_mandate.digest != APPROVED_DIGEST:
        raise ValueError("TRUST_MANDATE_DIGEST_MISMATCH")
    for attempt in audit.attempts:
        if isinstance(attempt.model_selection, Selection) or attempt.citations:
            selected, mandate = attempt.model_selection, audit.data_mandate
            if (mandate is None or not isinstance(selected, Selection)
                    or selected.endpoint_id != attempt.requested_endpoint
                    or [(c.year, c.metric) for c in selected.citations]
                    != [(c.year, c.metric) for c in attempt.citations]
                    or any(c.year not in mandate.years or c.metric not in mandate.metrics
                           or c.value != stats.cell(c.year, c.metric) for c in attempt.citations)):
                raise ValueError("TRUST_CITATION_DISAGREEMENT")
            expected_checks = CHECKS if mandate.binding == BINDING else [
                "SOURCE_DIGEST_MATCH", "CELLS_IN_MANDATE", "NO_UNGROUNDED_NUMBERS"]
            if attempt.trust == "ACCEPTED" and attempt.grounding_checks != expected_checks:
                raise ValueError("TRUST_GROUNDING_MISSING")
        if attempt.fixture and (attempt.trust != "REJECTED" or attempt.receiver_requests != 0):
            raise ValueError("TRUST_FIXTURE_DISAGREEMENT")
        if isinstance(attempt.model_selection, Notice):
            selected, reference = attempt.model_selection, audit.official_reference
            if (reference is None or (selected.year, selected.transactions) != (
                    reference.year, reference.transactions)
                    or selected.endpoint_id != attempt.requested_endpoint
                    or attempt.selection_checks != ["YEAR_MATCH", "COUNT_MATCH", "ENDPOINT_MATCH"]):
                raise ValueError("TRUST_SELECTION_DISAGREEMENT")
        if attempt.runtime_event_id:
            record = incidents.get(attempt.runtime_event_id)
            if (record is None or attempt.trust != "ACCEPTED"
                    or attempt.gateway != record.runtime.decision
                    or attempt.runtime_claim != record.runtime.claim
                    or attempt.verification != record.verification.result
                    or attempt.network_event_id != record.verification.network_event_id):
                raise ValueError("TRUST_EVENT_DISAGREEMENT")
        elif attempt.trust == "REJECTED" and (
                attempt.gateway != "NOT_CALLED" or attempt.runtime_claim is not None
                or attempt.network_event_id is not None or attempt.receiver_requests != 0):
            raise ValueError("TRUST_REJECTION_DISAGREEMENT")
    return audit
