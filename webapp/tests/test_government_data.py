import json

import pytest

from scripts.refresh_government_data import parse_transactions
from webapp.government_data import load_snapshot


def test_official_reference():
    data = load_snapshot()
    assert [(row.year, row.transactions) for row in data.rows] == [(2024, 5989840), (2025, 6998414)]
    assert data.publisher == "GDRFA Dubai"
    assert data.reuse_url.endswith("/en/open-data-policy")


@pytest.mark.parametrize("change", ["bool", "float", "source", "unit", "duplicate", "empty"])
def test_snapshot_rejects_invalid_input(tmp_path, change):
    data = load_snapshot().model_dump(mode="json")
    if change == "empty":
        data["rows"] = []
    elif change == "duplicate":
        data["rows"].append(data["rows"][0])
    elif change == "unit":
        data["unit"] = "residents"
    elif change == "source":
        data["rows"][0]["source_url"] = "https://example.org/report"
    else:
        data["rows"][0]["transactions"] = True if change == "bool" else 1000.0
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_snapshot(path)


def test_missing_snapshot(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot(tmp_path / "missing.json")


@pytest.mark.parametrize("year", [2024, 2025])
def test_extract_annual_report_row(year):
    report = f"    Transactions {year}\n    12,116,843  Entry Permit Transactions\n    6,998,414  RES Transactions\n"
    assert parse_transactions(report, year) == 6998414
    for malformed in (report.replace("RES ", ""), report + report, report.replace(str(year), "2020")):
        with pytest.raises(ValueError):
            parse_transactions(malformed, year)
