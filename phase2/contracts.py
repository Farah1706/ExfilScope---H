"""Untrusted model proposal schema, deliberately without security authority."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MODEL = "qwen3:4b-instruct-2507-q4_K_M"
MODEL_MANIFEST_DIGEST = "6214d088d3846e16c9fe00adcbabdbfddc61ce4a70daacc46cb2310c38603054"
OLLAMA_URL = "http://127.0.0.1:11435"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TextItem(StrictModel):
    text: str = Field(max_length=4096)


class Body(StrictModel):
    text: str | None = Field(default=None, max_length=4096)
    data: list[TextItem] | None = Field(default=None, max_length=8)


class Proposal(StrictModel):
    endpoint_alias: Literal["AUTHORIZED"]
    method: Literal["POST"]
    body: Body


def parse_proposal(raw: str) -> dict:
    """Reject duplicate keys/nonfinite JSON; preserve actual explicitly supplied fields."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def invalid_constant(_):
        raise ValueError("NONFINITE_JSON")

    if len(raw.encode("utf-8")) > 16384:
        raise ValueError("PROPOSAL_TOO_LARGE")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    Proposal.model_validate(value)
    return value
