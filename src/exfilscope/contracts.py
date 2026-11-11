"""Versioned evidence contracts. No contract for persisted evidence contains raw bodies."""

import json
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Label = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,96}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DIVERGENCE_LABELS = frozenset({"BLOCK_BYPASS", "DESTINATION_DIVERGENCE",
                             "METHOD_ROUTE_DIVERGENCE", "PAYLOAD_DIVERGENCE",
                             "CLAIM_INCONSISTENCY"})


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: str = "1.0"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    REDACT = "REDACT"
    BLOCK = "BLOCK"


class Claim(StrEnum):
    EXECUTED_SUCCESS = "EXECUTED_SUCCESS"
    EXECUTED_FAILED = "EXECUTED_FAILED"
    NOT_EXECUTED = "NOT_EXECUTED"


class ProposedAction(Contract):
    """Transient input only; body is raw JSON so duplicate keys remain detectable."""

    session_id: UUID = Field(default_factory=uuid4)
    tool: str = "http_json"
    url: str
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)
    body: str
    allow_redaction: bool = False  # Deprecated compatibility input; never grants authority.


class PermittedAction(Contract):
    """Transient authorization result; never serialize this into a ledger."""

    url: str
    method: str
    body: str
    endpoint_id: Label
    route_id: Label


class Metadata(Contract):
    endpoint_id: Label
    route_id: Label
    method: Label


class ProtectedHit(Contract):
    protected_id: Label
    source_ref: Label
    data_type: Label
    # Ordinal object positions avoid copying malicious key names into evidence.
    location: Annotated[str, StringConstraints(pattern=r"^\$(/(o|a)[0-9]+)*(\/key)?$")]


class RuntimeEvent(Contract):
    schema_version: str = "1.1"
    event_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    tool: Label = "http_json"
    proposed: Metadata
    hits: tuple[ProtectedHit, ...] = ()
    decision: Decision
    reason: Label
    policy_version: Label = "policy-1"
    permitted: Metadata | None = None
    payload_hmac: Digest | None = None
    key_id: Label
    canonicalization_version: Label = "rfc8785-0.1.4"
    claim: Claim = Claim.NOT_EXECUTED
    error_category: Label | None = None
    response_status: int | None = None
    decision_time: float
    completion_time: float | None = None
    decision_monotonic: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    completion_monotonic: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    host_id: Label | None = None
    clock_domain_id: Label | None = None


class ObservedEvent(Contract):
    schema_version: str = "1.1"
    event_id: UUID = Field(default_factory=uuid4)
    trace_id: UUID | None
    observed: Metadata
    payload_hmac: Digest | None
    key_id: Label
    canonicalization_version: Label = "rfc8785-0.1.4"
    request_time: float
    request_size: int = Field(ge=0)
    response_status: int | None = None
    anomalies: tuple[Label, ...] = ()
    request_monotonic: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    host_id: Label | None = None
    clock_domain_id: Label | None = None


class VerificationResult(Contract):
    schema_version: Literal["2.0"] = "2.0"
    runtime_event_id: UUID
    network_event_id: UUID | None = None
    result: Literal["MATCH", "MISMATCH", "UNVERIFIED"]
    evidence_status: Literal["VERIFIED", "UNVERIFIED"]
    labels: tuple[Label, ...] = ()
    diagnostics: tuple[Label, ...] = ()

    @model_validator(mode="after")
    def consistent_outcome(self):
        if (self.result == "MATCH" and self.evidence_status != "VERIFIED") or (
            self.result == "UNVERIFIED" and self.evidence_status != "UNVERIFIED"
        ) or (self.result == "MISMATCH" and not DIVERGENCE_LABELS.intersection(self.labels)) \
                or (self.result == "MATCH" and self.labels) \
                or (self.result == "UNVERIFIED" and DIVERGENCE_LABELS.intersection(self.labels)):
            raise ValueError("INCONSISTENT_VERIFICATION_OUTCOME")
        return self


def decode_verification_result(data: dict) -> VerificationResult:
    """Explicit in-memory migration; never rewrites historical ledger/export files."""
    version = data.get("schema_version", "1.0")
    if version == "1.0":
        data = dict(data, schema_version="2.0")
        # 1.0 reported evidence gaps as MISMATCH/UNVERIFIED. Only a gap without any
        # supported divergence label becomes UNVERIFIED; a supported divergence stays MISMATCH.
        if data.get("result") == "MISMATCH" and data.get("evidence_status") == "UNVERIFIED" \
                and not DIVERGENCE_LABELS.intersection(data.get("labels", ())):
            data["result"] = "UNVERIFIED"
    elif version != "2.0":
        raise ValueError("UNSUPPORTED_RESULT_SCHEMA")
    # JSON mode accepts historical string UUIDs and tuple arrays.
    return VerificationResult.model_validate_json(json.dumps(data))


class Authorization(Contract):
    event: RuntimeEvent
    permitted_action: PermittedAction | None = None
