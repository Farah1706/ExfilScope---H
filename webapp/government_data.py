"""Validated local extract of GDRFA Dubai's annual residence transaction tables."""

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BASE = "https://www.gdrfad.gov.ae"
REUSE_URL = BASE + "/en/open-data-policy"
SNAPSHOT = Path(__file__).parent / "static" / "government-data.json"


def source_url(year: int) -> str:
    return f"{BASE}/sites/default/files/gdrfa_tables/statistics/GDRFAD-Statistics{year}-en.pdf"


class ResidenceRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    year: int = Field(ge=2000, le=2099)
    transactions: int = Field(gt=0, le=1_000_000_000)
    source_url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    publisher: Literal["GDRFA Dubai"]
    metric: Literal["RES Transactions"]
    unit: Literal["transactions"]
    retrieved: date
    reuse_url: Literal[REUSE_URL]
    rows: list[ResidenceRow] = Field(min_length=1)


def load_snapshot(path: Path = SNAPSHOT) -> Snapshot:
    snapshot = Snapshot.model_validate_json(path.read_bytes())
    years = [row.year for row in snapshot.rows]
    if years != sorted(set(years)) or snapshot.retrieved < date(years[-1] + 1, 1, 1):
        raise ValueError("Invalid annual coverage or retrieval date")
    if any(row.source_url != source_url(row.year) for row in snapshot.rows):
        raise ValueError("Unexpected GDRFA Dubai source URL")
    return snapshot
