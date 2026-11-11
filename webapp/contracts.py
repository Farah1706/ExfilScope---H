"""Validated run requests and lifecycle records shared by the service and the runner."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .scenarios import BY_ID, CLAIM_MODES, PROTECTED_ITEMS

RUN_ID = re.compile(r"^run-[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
STAGES = (
    ("environment", "Environment validation"),
    ("preparation", "Synthetic source and task preparation"),
    ("proposal", "Agent proposal or deterministic case setup"),
    ("gateway", "Gateway policy evaluation"),
    ("execution", "Authorized action and runtime execution"),
    ("observation", "Independent proxy observation"),
    ("drain", "Evidence drain and monitoring-window completion"),
    ("verification", "Correlation and verification"),
    ("export", "Privacy audit and validated evidence export"),
)
STAGE_IDS = tuple(s for s, _ in STAGES)
STAGE_STATES = ("pending", "running", "complete", "failed", "unavailable")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    scenario_id: str
    mode: Literal["live", "stub", "lab", "trust"]
    protocol: Literal["http", "https"]
    trust_driver: Literal["scripted", "qwen3"] = "scripted"
    operator_lifecycle: bool = False
    protected_item: str | None = None
    claim_mode: Literal["plausible", "false_not_executed"] = "plausible"

    @model_validator(mode="after")
    def supported(self):
        if self.trust_driver != "scripted" and self.mode != "trust":
            raise ValueError("TRUST_DRIVER_REQUIRES_TRUST_MODE")
        if self.operator_lifecycle and (self.mode != "trust" or self.trust_driver != "qwen3"):
            raise ValueError("OPERATOR_LIFECYCLE_REQUIRES_QWEN3_TRUST")
        scenario = BY_ID.get(self.scenario_id)
        if scenario is None:
            raise ValueError("UNKNOWN_SCENARIO")
        if self.mode not in scenario.modes():
            raise ValueError("MODE_NOT_SUPPORTED_FOR_SCENARIO")
        if self.protected_item is not None and (
                not scenario.uses_protected_item or self.mode != "lab"
                or self.protected_item not in PROTECTED_ITEMS):
            raise ValueError("PROTECTED_ITEM_NOT_SELECTABLE")
        if self.claim_mode != "plausible" and (
                not scenario.claim_mode_supported or self.mode != "lab"
                or self.claim_mode not in CLAIM_MODES):
            raise ValueError("CLAIM_MODE_NOT_SUPPORTED")
        return self
