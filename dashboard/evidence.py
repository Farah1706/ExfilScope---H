"""Strict read-only snapshot access. No core, registry, SQLite or agent imports."""

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

DATA_ROOT = Path(__file__).resolve().parent / "data"
SCHEMA = "dashboard-1.1"
TITLES = {"qwen3-live": "Qwen3 live agent", "engineering-faults": "Controlled fault cases"}
SCENARIOS = {"allow": "Normal ALLOW", "redact": "Normal REDACT", "block": "Normal BLOCK",
             "block_bypass": "Block bypass", "payload_divergence": "Payload divergence",
             "destination_divergence": "Destination divergence", "no_observation": "No correlated observation"}
Label = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,96}$")]
Code = Annotated[str, StringConstraints(pattern=r"^[A-Z_]{1,96}$")]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Divergence = Literal["BLOCK_BYPASS", "PAYLOAD_DIVERGENCE", "DESTINATION_DIVERGENCE",
                     "METHOD_ROUTE_DIVERGENCE", "CLAIM_INCONSISTENCY", "NO_CORRELATED_OBSERVATION"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Metadata(Strict):
    schema_version: Literal["1.0"]
    endpoint_id: Label
    route_id: Label
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "UNSUPPORTED"]


class Hit(Strict):
    schema_version: Literal["1.0"]
    protected_id: Annotated[str, StringConstraints(pattern=r"^SECRET_[0-9]{3,}$")]
    source_ref: Annotated[str, StringConstraints(pattern=r"^DOC_[A-Z0-9_]+:chunk_[0-9]+$")]
    data_type: Code
    location: Annotated[str, StringConstraints(pattern=r"^\$(/(o|a)[0-9]+)*(\/key)?$")]


class Runtime(Strict):
    schema_version: Literal["1.1"]
    event_id: UUID
    trace_id: UUID
    session_id: UUID
    proposed: Metadata
    hits: list[Hit]
    decision: Literal["ALLOW", "REDACT", "BLOCK"]
    reason: Code
    policy_version: Label
    permitted: Metadata | None
    payload_hmac: Digest | None
    key_id: Label
    canonicalization_version: Label
    claim: Literal["NOT_EXECUTED", "EXECUTED_SUCCESS", "EXECUTED_FAILED"]
    error_category: Code | None
    response_status: int | None
    decision_time: float = Field(ge=0, le=4102444800, allow_inf_nan=False)
    completion_time: float | None = Field(ge=0, le=4102444800, allow_inf_nan=False)
    decision_monotonic: float = Field(ge=0, allow_inf_nan=False)
    host_id: Label
    clock_domain_id: Label


class Observation(Strict):
    schema_version: Literal["1.1"]
    event_id: UUID
    trace_id: UUID
    observed: Metadata
    payload_hmac: Digest | None
    key_id: Label
    canonicalization_version: Label
    request_time: float = Field(ge=0, le=4102444800, allow_inf_nan=False)
    request_monotonic: float = Field(ge=0, allow_inf_nan=False)
    request_size: int = Field(ge=0)
    response_status: int | None
    anomalies: list[Code]
    host_id: Label
    clock_domain_id: Label


class Verification(Strict):
    schema_version: Literal["2.0"]
    runtime_event_id: UUID
    # The verifier's own pairing; None when it paired no observation.
    network_event_id: UUID | None
    result: Literal["MATCH", "MISMATCH", "UNVERIFIED"]
    evidence_status: Literal["VERIFIED", "UNVERIFIED"]
    labels: list[Divergence]
    diagnostics: list[Code]

    @model_validator(mode="after")
    def consistent(self):
        demonstrated = set(self.labels) - {"NO_CORRELATED_OBSERVATION"}
        if (self.result == "MATCH" and (self.labels or self.evidence_status != "VERIFIED")) \
                or (self.result == "MISMATCH" and not demonstrated) \
                or (self.result == "UNVERIFIED" and (demonstrated or self.evidence_status != "UNVERIFIED")):
            raise ValueError("CONTRADICTORY_RESULT")
        return self


class Incident(Strict):
    run_id: Label
    scenario: Literal["allow", "redact", "block", "block_bypass", "payload_divergence",
                      "destination_divergence", "no_observation"]
    protocol: Literal["http", "https"]
    origin: Literal["LLM run", "Deterministic replay", "Controlled fault injection"]
    runtime: Runtime
    observation: Observation | None
    verification: Verification
    window_seconds: float = Field(gt=0, allow_inf_nan=False)
    health_records: int = Field(ge=0)
    monitor_generations: int = Field(ge=0)
    observation_withheld: bool

    @model_validator(mode="after")
    def defensible_pair(self):
        a, b, v = self.runtime, self.observation, self.verification
        if self.observation_withheld and b is not None:
            raise ValueError("WITHHELD_OBSERVATION_RESTORED")
        if v.runtime_event_id != a.event_id:
            raise ValueError("RESULT_RUNTIME_EVENT_MISMATCH")
        # Display only the observation the verifier paired; never a re-derived candidate.
        if (b.event_id if b else None) != v.network_event_id:
            raise ValueError("OBSERVATION_NOT_VERIFIER_PAIRED")
        if b and (b.trace_id != a.trace_id or b.host_id != a.host_id or
                  b.clock_domain_id != a.clock_domain_id or not
                  0 <= b.request_monotonic - a.decision_monotonic <= self.window_seconds):
            raise ValueError("UNUSABLE_PAIR")
        if a.decision == "BLOCK" and (a.permitted is not None or a.payload_hmac is not None):
            raise ValueError("BLOCK_HAS_PERMITTED_BODY")
        if v.result == "MATCH":
            if not self.health_records or not self.monitor_generations:
                raise ValueError("MATCH_WITHOUT_SOURCE_HEALTH")
            if not b and not (a.decision == "BLOCK" and a.claim == "NOT_EXECUTED" and
                              "SCOPED_PROXY_ABSENCE" in v.diagnostics):
                raise ValueError("MATCH_WITHOUT_USABLE_OBSERVATION")
            if b and a.decision == "BLOCK":
                raise ValueError("BLOCK_MATCH_WITH_OBSERVATION")
            if b and (a.permitted != b.observed or not a.payload_hmac or
                      a.payload_hmac != b.payload_hmac or a.key_id != b.key_id or
                      a.canonicalization_version != b.canonicalization_version or
                      a.claim == "NOT_EXECUTED"):
                raise ValueError("CONTRADICTORY_MATCH")
        return self

    @property
    def identifier(self):
        return f"{self.run_id}:{self.runtime.event_id}"


class Bundle(Strict):
    schema_version: Literal["dashboard-1.1"]
    investigation_id: Literal["qwen3-live", "engineering-faults"]
    source_hashes: dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_./-]{1,160}$")], Digest]
    incidents: list[Incident] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_records(self):
        ids = [i.identifier for i in self.incidents]
        traces = [(i.run_id, i.runtime.trace_id) for i in self.incidents]
        if len(ids) != len(set(ids)) or len(traces) != len(set(traces)):
            raise ValueError("DUPLICATE_RECORD")
        return self


def read_json(path: Path):
    if path.is_symlink() or path.stat().st_size > 4_000_000:
        raise ValueError("UNSAFE_SNAPSHOT_FILE")
    return path.read_bytes()


def load_catalog(root: Path = DATA_ROOT) -> tuple[dict[str, Bundle], list[str]]:
    """Only fixed, allowlisted snapshots; bad investigations excluded without input echo."""
    catalog, issues = {}, []
    try:
        if root.is_symlink():
            raise ValueError()
        manifest = json.loads(read_json(root / "manifest.json"))
        if set(manifest) != {"schema_version", "files"} or manifest["schema_version"] != SCHEMA:
            raise ValueError()
        if not isinstance(manifest["files"], dict) or set(manifest["files"]) - set(TITLES):
            raise ValueError()
    except (OSError, ValueError, TypeError):
        return {}, ["Evidence catalog unavailable or incompatible. No records loaded."]
    for identifier, expected in manifest["files"].items():
        try:
            data = read_json(root / (identifier + ".json"))
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError()
            bundle = Bundle.model_validate_json(data)
            if bundle.investigation_id != identifier:
                raise ValueError()
            catalog[identifier] = bundle
        except (OSError, ValueError, TypeError):
            issues.append(f"{identifier}: snapshot rejected (integrity, schema or missing evidence).")
    return catalog, issues


def select(records, identifier):
    return next((i for i in records if i.identifier == identifier), None)


def filter_records(records, *, protocols=None, decisions=None, outcomes=None, scenarios=None, runs=None,
                   search="", start=None, end=None):
    return [i for i in records if
            (protocols is None or i.protocol in protocols) and
            (decisions is None or i.runtime.decision in decisions) and
            (outcomes is None or i.verification.result in outcomes) and
            (scenarios is None or i.scenario in scenarios) and
            (runs is None or i.run_id in runs) and
            (start is None or i.runtime.decision_time >= start) and
            (end is None or i.runtime.decision_time <= end) and
            (not search or search.lower() in " ".join([str(i.runtime.trace_id), i.run_id,
                i.scenario, i.runtime.reason, i.runtime.proposed.endpoint_id,
                *i.verification.labels, *i.verification.diagnostics]).lower())]


def counts(records):
    return {"total": len(records), "decisions": dict(Counter(i.runtime.decision for i in records)),
            "outcomes": dict(Counter(i.verification.result for i in records)),
            "protocols": dict(Counter(i.protocol.upper() for i in records))}


def comparison(i):
    a, b = i.runtime, i.observation
    unavailable = "Unavailable"
    if not b:
        return {"Destination": unavailable, "Method / route": unavailable,
                "Payload commitment": unavailable, "Runtime claim": unavailable}
    permitted = a.permitted
    compatible = a.key_id == b.key_id and a.canonicalization_version == b.canonicalization_version
    return {"Destination": "No permitted request" if permitted is None else
            "Agrees" if permitted.endpoint_id == b.observed.endpoint_id else "Diverges",
            "Method / route": "No permitted request" if permitted is None else
            "Agrees" if (permitted.method, permitted.route_id) == (b.observed.method, b.observed.route_id)
            else "Diverges",
            "Payload commitment": "Not applicable" if a.decision == "BLOCK" else
            unavailable if not compatible or not a.payload_hmac or not b.payload_hmac else
            "Equal" if a.payload_hmac == b.payload_hmac else "Different",
            "Runtime claim": "Incompatible with observed emission" if a.claim == "NOT_EXECUTED"
            else "Compatible with observed emission"}


def absence_explanation(i):
    if i.runtime.decision == "BLOCK" and "SCOPED_PROXY_ABSENCE" in i.verification.diagnostics:
        return ("No corresponding completed request was observed at this proxy request hook during "
                "the recorded window, under the documented health and coverage assumptions. "
                "This does not prove absolute network absence or host-wide containment.")
    if i.observation_withheld:
        return ("The engineering harness withheld the observation from the verifier view. "
                "The original monitor ledger was preserved; its withheld content is not restored here.")
    return ("A proxy observation establishes arrival at the monitored boundary, not successful "
            "remote-server processing. Missing evidence alone does not establish non-transmission.")


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if value is not None else "Unavailable"


def table_rows(records):
    return [{"Trace": str(i.runtime.trace_id), "Scenario": SCENARIOS[i.scenario],
             "Decision": i.runtime.decision, "Result": i.verification.result,
             "Protocol": i.protocol.upper(), "Recorded (UTC)": utc(i.runtime.decision_time),
             "Origin": i.origin} for i in records]


def export_csv(records):
    fields = ["run_id", "event_id", "trace_id", "scenario", "origin", "protocol", "decision",
              "result", "evidence_status", "claim", "proposed_endpoint", "permitted_endpoint",
              "observed_endpoint", "labels", "diagnostics", "recorded_utc"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for i in records:
        a, b, v = i.runtime, i.observation, i.verification
        row = dict(zip(fields, [i.run_id, str(a.event_id), str(a.trace_id), i.scenario, i.origin,
            i.protocol, a.decision, v.result, v.evidence_status, a.claim, a.proposed.endpoint_id,
            a.permitted.endpoint_id if a.permitted else "", b.observed.endpoint_id if b else "",
            "|".join(v.labels), "|".join(v.diagnostics), utc(a.decision_time)]))
        writer.writerow({k: "'" + str(v) if str(v).startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                         else v for k,v in row.items()})
    return stream.getvalue().encode("utf-8")
