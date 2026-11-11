"""Validated, hash-pinned extract of GDRFA Dubai's annual statistics workbooks (2018-2025).

The approved data version is pinned by ``APPROVED_DIGEST``. Changing any value requires a
reviewed code change, so an altered or substituted snapshot fails before a model is called.
"""

from datetime import date
import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
import rfc8785

from webapp.government_data import load_snapshot

BASE = "https://www.gdrfad.gov.ae"
LANDING_URL = "https://gdrfad.gov.ae/en/open-data"
REUSE_URL = BASE + "/en/open-data-policy"
SNAPSHOT = Path(__file__).parent / "static" / "gdrfa-statistics.json"
APPROVED_DIGEST = "350da4ca9c0397db17efcc2a98610d8e522207b3939625de1204eb75521db46f"
FIRST_YEAR = 2018
METRICS = ("entry_permit_transactions", "residence_transactions", "establishment_transactions",
           "port_movements_total", "smart_gate_corridor_total")
LABELS = {"entry_permit_transactions": "Entry Permit Transactions",
          "residence_transactions": "RES Transactions",
          "establishment_transactions": "Establishments Transactions",
          "port_movements_total": "Port movements (total)",
          "smart_gate_corridor_total": "Smart gate and corridor movements (total)"}
PORTS = ("airport", "land_border", "seaport")
SMART = ("smart_gates", "smart_corridor")

Count = Field(gt=0, le=1_000_000_000, strict=True)


def source_url(year: int) -> str:
    return f"{BASE}/sites/default/files/gdrfa_tables/statistics/GDRFAD-Statistics{year}-en.xlsx"


class Movement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entry: int = Field(ge=0, le=1_000_000_000)
    exit: int = Field(ge=0, le=1_000_000_000)
    total: int = Field(ge=0, le=1_000_000_000)


class Cells(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    entry_permit_transactions: int = Count
    residence_transactions: int = Count
    establishment_transactions: int = Count
    port_movements_total: int = Count
    smart_gate_corridor_total: int = Count


class YearTable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    year: int = Field(ge=2000, le=2099)
    source_url: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cells: Cells
    checks: dict[Literal["airport", "land_border", "seaport", "ports_total", "smart_gates",
                         "smart_corridor", "smart_total"], Movement]


class Statistics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    publisher: Literal["GDRFA Dubai"]
    dataset: Literal["GDRFA Dubai Statistics (annual transactions tables)"]
    landing_url: Literal[LANDING_URL]
    reuse_url: Literal[REUSE_URL]
    classification: Literal["OPEN_AGGREGATE"]
    retrieved: date
    unit: Literal["count"]
    years: list[YearTable] = Field(min_length=1)
    excluded: list[str]

    @property
    def latest_year(self) -> int:
        return self.years[-1].year

    def cell(self, year: int, metric: str) -> int:
        return getattr(next(t for t in self.years if t.year == year).cells, metric)


def check_table(table: YearTable) -> None:
    """Publisher arithmetic: each row sums, ports and smart channels add up."""
    c = table.checks
    if set(c) != {*PORTS, "ports_total", *SMART, "smart_total"}:
        raise ValueError("Incomplete validation rows")
    if any(m.entry + m.exit != m.total for m in c.values()):
        raise ValueError("Entry and exit do not sum to total")
    for parts, total in ((PORTS, "ports_total"), (SMART, "smart_total")):
        for field in ("entry", "exit", "total"):
            if sum(getattr(c[p], field) for p in parts) != getattr(c[total], field):
                raise ValueError("Channel rows do not sum to their total")
    if (table.cells.port_movements_total, table.cells.smart_gate_corridor_total) != (
            c["ports_total"].total, c["smart_total"].total):
        raise ValueError("Mandate cells disagree with validation rows")


def mandate_digest(stats: Statistics) -> str:
    return hashlib.sha256(rfc8785.dumps(stats.model_dump(mode="json"))).hexdigest()


def validate(stats: Statistics) -> Statistics:
    years = [t.year for t in stats.years]
    if years != list(range(FIRST_YEAR, years[-1] + 1)) or stats.retrieved < date(years[-1] + 1, 1, 1):
        raise ValueError("Invalid annual coverage or retrieval date")
    if stats.retrieved.year - stats.latest_year > 2:
        raise ValueError("SOURCE_STALE")
    for table in stats.years:
        if table.source_url != source_url(table.year):
            raise ValueError("Unexpected GDRFA Dubai source URL")
        check_table(table)
    # The PDF-derived planner snapshot and the workbooks must agree where they overlap.
    for row in load_snapshot().rows:
        if stats.cell(row.year, "residence_transactions") != row.transactions:
            raise ValueError("PDF and XLSX residence transactions disagree")
    return stats


def load_statistics(path: Path = SNAPSHOT, approved: str | None = APPROVED_DIGEST) -> Statistics:
    stats = validate(Statistics.model_validate_json(path.read_bytes()))
    if approved is not None and mandate_digest(stats) != approved:
        raise ValueError("SOURCE_INTEGRITY_FAILED")
    return stats
