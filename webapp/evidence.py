"""Strict schema and loader for platform-run snapshots; reuses the dashboard's Incident model.

Like ``dashboard.evidence`` this module imports no core, registry, SQLite or agent code, so
the service process that serves the browser never opens a ledger.
"""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from dashboard.evidence import Incident, Label, Strict, read_json

from .scenarios import BY_ID

SCHEMA = "platform-run-1.0"
ScenarioId = Literal[tuple(BY_ID)]  # type: ignore[valid-type]


class RunSnapshot(Strict):
    schema_version: Literal["platform-run-1.0"]
    run_id: Label
    scenario_id: ScenarioId
    mode: Literal["live", "stub", "lab", "trust"]
    protocol: Literal["http", "https"]
    claim_mode: Literal["plausible", "false_not_executed"]
    source_hashes: dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_./-]{1,160}$")],
                        Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]]
    incidents: list[Incident] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def consistent(self):
        if len(self.incidents) != 1 and self.mode != "trust":
            raise ValueError("SNAPSHOT_RUN_DISAGREEMENT")
        if len({str(i.runtime.event_id) for i in self.incidents}) != len(self.incidents):
            raise ValueError("SNAPSHOT_DUPLICATE_INCIDENT")
        expected = {"live": "LLM run", "stub": "Deterministic replay"}.get(self.mode)
        for incident in self.incidents:
            if incident.run_id != self.run_id or incident.protocol != self.protocol \
                    or (expected and incident.origin != expected) \
                    or incident.scenario != BY_ID[self.scenario_id].lab_scenario:
                raise ValueError("SNAPSHOT_RUN_DISAGREEMENT")
        return self


def load_run_snapshot(export: Path) -> RunSnapshot:
    """Load ``export/snapshot.json`` only if its manifest hash and schema both hold."""
    if export.is_symlink() or not export.is_dir():
        raise ValueError("SNAPSHOT_UNAVAILABLE")
    manifest = json.loads(read_json(export / "manifest.json"))
    if set(manifest) != {"schema_version", "files"} or manifest["schema_version"] != SCHEMA \
            or set(manifest["files"]) - {"trust-audit.json"} != {"snapshot.json"}:
        raise ValueError("SNAPSHOT_MANIFEST_INVALID")
    data = read_json(export / "snapshot.json")
    if hashlib.sha256(data).hexdigest() != manifest["files"]["snapshot.json"]:
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    return RunSnapshot.model_validate_json(data)
