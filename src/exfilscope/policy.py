"""Trusted, versioned request rules. Never construct these from a tool proposal."""

from pathlib import Path
from typing import Any

from pydantic import model_validator

from .contracts import Contract, Label, Metadata


def tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/") or any(
        "~" in part.replace("~0", "").replace("~1", "") for part in pointer.split("/")[1:]
    ):
        raise ValueError("INVALID_POLICY_POINTER")
    return tuple(p.replace("~1", "/").replace("~0", "~") for p in pointer.split("/")[1:])


def matches(pointer: str, path: tuple[str | int, ...]) -> bool:
    parts = tokens(pointer)
    return len(parts) == len(path) and all(
        (p == "*" or p == str(actual)) if isinstance(actual, int) else p == actual
        for p, actual in zip(parts, path)
    )


class PolicyRule(Contract):
    endpoint_id: Label
    method: Label
    route_id: Label
    approved_fields: tuple[str, ...]
    redaction_paths: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_paths(self):
        for pointer in (*self.approved_fields, *self.redaction_paths):
            tokens(pointer)
        return self

    def accepts(self, value: Any, path: tuple[str | int, ...] = ()) -> bool:
        if isinstance(value, dict):
            return all(any(matches(p, (*path, key)) for p in self.approved_fields)
                       and self.accepts(child, (*path, key)) for key, child in value.items())
        if isinstance(value, list):
            return all(self.accepts(child, (*path, i)) for i, child in enumerate(value))
        return True

    def permits_protected(self, value: Any, registry, path: tuple[str | int, ...] = ()) -> bool:
        if isinstance(value, str):
            return not registry.contains(value) or any(matches(p, path) for p in self.redaction_paths)
        if isinstance(value, dict):
            return all(not registry.contains(key) and self.permits_protected(child, registry,
                       (*path, key)) for key, child in value.items())
        if isinstance(value, list):
            return all(self.permits_protected(child, registry, (*path, i))
                       for i, child in enumerate(value))
        return True


class GatewayPolicy(Contract):
    version: Label
    rules: tuple[PolicyRule, ...]

    @model_validator(mode="after")
    def unique_contexts(self):
        contexts = [(r.endpoint_id, r.method, r.route_id) for r in self.rules]
        if len(set(contexts)) != len(contexts):
            raise ValueError("DUPLICATE_POLICY_CONTEXT")
        return self

    def rule_for(self, metadata: Metadata) -> PolicyRule | None:
        return next((r for r in self.rules if (r.endpoint_id, r.method, r.route_id) ==
                     (metadata.endpoint_id, metadata.method, metadata.route_id)), None)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_bytes())
