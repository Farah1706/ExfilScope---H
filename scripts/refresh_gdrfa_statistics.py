"""Stage a reviewed GDRFA Dubai statistics candidate from the publisher's XLSX workbooks.

Reads already-downloaded workbooks (one per year) with the standard library only, finds
rows by their exact text labels, never by position, and refuses any table whose
publisher arithmetic does not hold. Promotion to webapp/static is a separate human step.
"""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from webapp.gdrfa_statistics import (  # noqa: E402
    FIRST_YEAR, LANDING_URL, REUSE_URL, Statistics, source_url, validate)

LIMIT = 2_000_000
EXCLUDED = ["Two unlabeled rows per workbook whose labels are images; their meaning is not "
            "machine-readable, so they are not used."]


def read_rows(data: bytes) -> list[list[str]]:
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as book:
        names = book.namelist()
        sheets = [n for n in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)]
        if sheets != ["xl/worksheets/sheet1.xml"]:
            raise ValueError("Expected a single worksheet")
        strings = []
        if "xl/sharedStrings.xml" in names:
            for item in re.findall(r"<si>(.*?)</si>", book.read("xl/sharedStrings.xml").decode(), re.S):
                strings.append("".join(re.findall(r"<t[^>]*>([^<]*)</t>", item)).strip())
        rows = []
        for row in re.findall(r"<row[^>]*>(.*?)</row>", book.read(sheets[0]).decode(), re.S):
            cells = []
            for attrs, inner in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
                value = re.search(r"<v>([^<]*)</v>", inner or "")
                if value:
                    text = value.group(1)
                    cells.append(strings[int(text)] if 't="s"' in attrs else text.strip())
            if cells:
                rows.append(cells)
        return rows


def count(text: str) -> int:
    if not re.fullmatch(r"\d{1,10}", text):
        raise ValueError("Expected a whole count")
    return int(text)


def parse_workbook(data: bytes, year: int) -> dict:
    rows = read_rows(data)
    if [r[0] for r in rows[:1]] != [f"Transactions {year}"]:
        raise ValueError("Unexpected title row")
    single = {r[0]: r for r in rows if len(r) == 2}
    triple = [r for r in rows if len(r) == 4]
    labels = [r[0] for r in triple]
    expected = ["Ports Type", "Airport", "Land Border", "Seaport", "Total", "Smart gates",
                "Smart corridor", "Total"]
    if labels[:8] != expected or [r[1:] for r in triple[:1]] != [["Entry", "Exit", "Total"]]:
        raise ValueError("Port and smart channel table layout changed")

    def movement(row):
        entry, exit_, total = (count(v) for v in row[1:])
        return {"entry": entry, "exit": exit_, "total": total}

    checks = dict(zip(("airport", "land_border", "seaport", "ports_total", "smart_gates",
                       "smart_corridor", "smart_total"), (movement(r) for r in triple[1:8])))
    try:
        cells = {"entry_permit_transactions": count(single["Entry Permit Transactions"][1]),
                 "residence_transactions": count(single["RES Transactions"][1]),
                 "establishment_transactions": count(single["Establishments Transactions"][1])}
    except KeyError as exc:
        raise ValueError("Transaction row missing") from exc
    cells.update(port_movements_total=checks["ports_total"]["total"],
                 smart_gate_corridor_total=checks["smart_total"]["total"])
    return {"year": year, "source_url": source_url(year), "sha256": hashlib.sha256(data).hexdigest(),
            "cells": cells, "checks": checks}


def build(folder: Path, years: range, retrieved: date) -> Statistics:
    tables = []
    for year in years:
        data = (folder / f"GDRFAD-Statistics{year}-en.xlsx").read_bytes()
        if len(data) > LIMIT or not data.startswith(b"PK"):
            raise ValueError(f"{year}: not a plausible XLSX workbook")
        tables.append(parse_workbook(data, year))
    return validate(Statistics.model_validate_json(json.dumps({
        "publisher": "GDRFA Dubai", "dataset": "GDRFA Dubai Statistics (annual transactions tables)",
        "landing_url": LANDING_URL, "reuse_url": REUSE_URL, "classification": "OPEN_AGGREGATE",
        "retrieved": retrieved.isoformat(), "unit": "count", "years": tables, "excluded": EXCLUDED})))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Folder holding GDRFAD-Statistics{YEAR}-en.xlsx")
    parser.add_argument("--last-year", type=int, required=True)
    parser.add_argument("--retrieved", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidate = build(args.folder, range(FIRST_YEAR, args.last_year + 1), args.retrieved)
    with args.output.open("x", encoding="utf-8", newline="\n") as file:
        file.write(candidate.model_dump_json(indent=2) + "\n")
    for table in candidate.years:
        print(table.year, table.sha256, table.cells.model_dump())
    print(f"Review source hashes and values before promoting {args.output}")


if __name__ == "__main__":
    main()
