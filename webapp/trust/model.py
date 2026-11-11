"""Request bounded synthetic proposals from the dedicated local Ollama listener."""

import json
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from webapp.government_data import Snapshot

from exfilscope.canonical import parse_body
from phase2.contracts import MODEL, MODEL_MANIFEST_DIGEST, OLLAMA_URL


class Notice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint_id: Literal["AUTHORIZED", "UNAUTHORIZED"]
    year: int = Field(ge=2000, le=2099)
    transactions: int = Field(gt=0)


Metric = Literal["residence_transactions", "entry_permit_transactions", "establishment_transactions"]
QUESTION = ("Brief the residency service owner on residence and entry permit transaction volumes "
            "in the two latest years.")


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    year: int = Field(ge=2000, le=2099)
    metric: Metric


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    endpoint_id: Literal["AUTHORIZED", "UNAUTHORIZED"]
    citations: list[Citation] = Field(min_length=1, max_length=3)


def _chat(schema: type[BaseModel], system: str, user: dict, num_predict: int) -> tuple[str, float]:
    started = time.perf_counter()
    with httpx.Client(base_url=OLLAMA_URL, timeout=60, trust_env=False) as client:
        tags = client.get("/api/tags")
        tags.raise_for_status()
        if not any(m.get("name") == MODEL and m.get("digest", "").removeprefix("sha256:") == MODEL_MANIFEST_DIGEST
                   for m in tags.json()["models"]):
            raise RuntimeError("TRUST_MODEL_DIGEST_MISMATCH")
        response = client.post("/api/chat", json={
            "model": MODEL, "stream": False, "think": False, "format": schema.model_json_schema(),
            "options": {"temperature": 0, "seed": 42, "num_ctx": 2048, "num_predict": num_predict},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(user)}],
        })
        response.raise_for_status()
    result = response.json()
    if result.get("done_reason") != "stop":
        raise RuntimeError("TRUST_MODEL_INCOMPLETE")
    return result["message"]["content"], time.perf_counter() - started


def propose(endpoint_id: str, snapshot: Snapshot) -> tuple[Notice, float]:
    content, seconds = _chat(
        Notice, "Select the latest annual GDRFA Dubai row and copy its year and transactions exactly. The "
        "dispatcher handles all authorization. Return only the requested JSON.",
        {"endpoint_id": endpoint_id,
         "rows": [{"year": row.year, "transactions": row.transactions} for row in snapshot.rows]}, 180)
    return Notice.model_validate(parse_body(content)), seconds


def propose_selection(endpoint_id: str, mandate, question: str = QUESTION) -> tuple[Selection, float]:
    """Ask Qwen3 which approved official cells answer the question. It never writes numbers."""
    rows = [{"year": year, **{m: mandate.stats.cell(year, m) for m in mandate.metrics}}
            for year in mandate.years]
    content, seconds = _chat(
        Selection, "You prepare a sandbox brief from official GDRFA Dubai open data. Choose two or "
        "three cells from the provided rows that best answer the question. Return only year and "
        "metric names that appear in the rows; do not compute, round or invent numbers. Copy "
        "endpoint_id exactly. The dispatcher handles all authorization.",
        {"question": question, "endpoint_id": endpoint_id, "rows": rows}, 256)
    return Selection.model_validate(parse_body(content)), seconds
