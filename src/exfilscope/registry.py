"""Synthetic registry: exact substring matching in JSON strings, including object keys."""

import json
from pathlib import Path
from typing import Any

from pydantic import Field

from .contracts import Contract, Label, ProtectedHit

PLACEHOLDER = "[REDACTED]"


class ProtectedItem(Contract):
    protected_id: Label
    value: str = Field(min_length=8, repr=False)
    source_ref: Label
    data_type: Label


class Registry:
    def __init__(self, items: list[ProtectedItem]):
        ids = [i.protected_id for i in items]
        if len(ids) != len(set(ids)) or not items:
            raise ValueError("INVALID_REGISTRY")
        for i, item in enumerate(items):
            try:
                item.value.encode("utf-8")
            except UnicodeError:
                raise ValueError("INVALID_MARKER_UNICODE") from None
            labels = " ".join([item.protected_id, item.source_ref, item.data_type, PLACEHOLDER])
            if item.value in labels or PLACEHOLDER in item.value:
                raise ValueError("AMBIGUOUS_REGISTRY")
            for other in items[i + 1:]:
                if item.value in other.value or other.value in item.value:
                    raise ValueError("OVERLAPPING_MARKERS")
            if any(other.value in labels for other in items):
                raise ValueError("UNSAFE_REGISTRY_LABEL")
        self.items = tuple(items)

    @classmethod
    def load(cls, path: Path) -> "Registry":
        return cls([ProtectedItem.model_validate(i) for i in json.loads(path.read_text())])

    def contains(self, text: str) -> bool:
        return any(i.value in text for i in self.items)

    def scan(self, value: Any, location: str = "$") -> tuple[ProtectedHit, ...]:
        hits = []
        if isinstance(value, str):
            for item in self.items:
                if item.value in value:
                    hits.append(ProtectedHit(protected_id=item.protected_id,
                                             source_ref=item.source_ref,
                                             data_type=item.data_type, location=location))
        elif isinstance(value, dict):
            for index, (key, item) in enumerate(value.items()):
                child = f"{location}/o{index}"
                hits.extend(self.scan(key, child + "/key"))
                hits.extend(self.scan(item, child))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                hits.extend(self.scan(item, f"{location}/a{index}"))
        return tuple(hits)

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            for item in self.items:
                value = value.replace(item.value, PLACEHOLDER)
            return value
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value
