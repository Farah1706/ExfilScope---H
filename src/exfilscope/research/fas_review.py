"""Evaluator-only functions. No imports of custody, batches, truth, keys or scoring.

Run on a separately provisioned reviewer account with only assigned package copies.
Directory separation does not enforce Windows account permissions.
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QUESTIONS = (
    "Which registered protected items and sources were implicated, or none?",
    "What endpoint, method and route were proposed?",
    "What decision was made and why? Include the policy version.",
    "How did policy change the action?",
    "What action was permitted, or none?",
    "What execution did the runtime claim? Include any safe error category.",
    "What request was observed at the boundary, or what observation gap is supported?",
    "Is the runtime claim compatible with the available network evidence?",
    "What final status is justified by the supplied evidence?",
    "What divergence or investigative limitation follows, and what cannot be concluded?",
)


def pointer(value, reference):
    """Resolve a JSON pointer within this package only; never interpret a filesystem path."""
    if not reference.startswith("/evidence/") or "~" in reference:
        raise ValueError("INVALID_SUPPORT_REFERENCE")
    try:
        for part in reference[1:].split("/"):
            value = value[int(part)] if isinstance(value, list) else value[part]
    except (ValueError, KeyError, IndexError, TypeError):
        raise ValueError("UNAVAILABLE_SUPPORT_REFERENCE") from None
    return value


def load_package(directory):
    directory = Path(directory)
    if directory.is_symlink() or any(p.is_symlink() for p in directory.iterdir()):
        raise ValueError("SYMLINK_PACKAGE_REJECTED")
    if {p.name for p in directory.iterdir()} != {"evidence.json", "manifest.json"}:
        raise ValueError("UNEXPECTED_PACKAGE_FILES")
    manifest = json.loads((directory / "manifest.json").read_bytes())
    raw = (directory / "evidence.json").read_bytes()
    if manifest.get("files") != {"evidence.json": hashlib.sha256(raw).hexdigest()}:
        raise ValueError("PACKAGE_INTEGRITY_FAILURE")
    package = json.loads(raw)
    if (set(package) != {"schema", "package_id", "condition", "purpose", "limitations", "evidence"}
            or package["schema"] != "fas-1" or package["package_id"] != manifest["package_id"]):
        raise ValueError("INVALID_PACKAGE")
    allowed = {"A": {"runtime"},
               "B": {"runtime", "network", "verification", "coverage", "window_seconds",
                     "drain_grace_seconds"}}
    allowed["C"] = allowed["B"] | {"content"}
    if set(package["evidence"]) != allowed.get(package["condition"], set()):
        raise ValueError("CONDITION_EVIDENCE_VIOLATION")
    return package


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: int = Field(ge=1, le=10)
    text: str = Field(max_length=20000)
    support: list[str] = Field(default_factory=list, max_length=30)


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, serialize_by_alias=True)
    schema_version: Literal["fas-response-1"] = Field(default="fas-response-1", alias="schema")
    package_id: str = Field(pattern=r"^P[0-9a-f]{20}$")
    reviewer: Literal["reviewer-1", "reviewer-2"]
    origin: Literal["human", "engineering-fixture"]
    answers: list[Answer] = Field(max_length=10)

    @model_validator(mode="after")
    def unique_questions(self):
        if len({a.question for a in self.answers}) != len(self.answers):
            raise ValueError("DUPLICATE_ANSWER")
        return self


def response_template(package, reviewer, origin="human"):
    return {"schema": "fas-response-1", "package_id": package["package_id"],
            "reviewer": reviewer, "origin": origin,
            "answers": [{"question": n, "text": "", "support": []} for n in range(1, 11)]}


def validate_response(package, data):
    response = Response.model_validate(data)
    if response.package_id != package["package_id"]:
        raise ValueError("WRONG_PACKAGE_RESPONSE")
    for answer in response.answers:
        for reference in answer.support:
            pointer(package, reference)
    return response


def lock_response(directory, data, target):
    """Write once. Custodian import must also bind package and rubric hashes."""
    package = load_package(directory)
    response = validate_response(package, data)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(response.model_dump(), stream, sort_keys=True, indent=2)
