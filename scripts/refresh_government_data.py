"""Stage a reviewed GDRFA Dubai snapshot candidate. Requires pypdf in a separate tooling environment."""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import httpx
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from webapp.government_data import ResidenceRow, load_snapshot, source_url  # noqa: E402

LIMIT = 2_000_000


def parse_transactions(text: str, year: int) -> int:
    headers = re.findall(r"^\s*Transactions (\d{4})[ \t]*$", text, re.M)
    rows = re.findall(r"^[ \t]*(\d{1,3}(?:,\d{3})+)[ \t]+RES Transactions[ \t]*$", text, re.M)
    if headers != [str(year)] or len(rows) != 1:
        raise ValueError("Expected a single matching annual heading and RES Transactions row")
    return int(rows[0].replace(",", ""))


def retrieve(year: int) -> ResidenceRow:
    from pypdf import PdfReader

    url = source_url(year)
    data = bytearray()
    with httpx.stream("GET", url, follow_redirects=False, timeout=20, trust_env=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > LIMIT:
                raise ValueError("Publisher report exceeds download limit")
    if not data.startswith(b"%PDF-"):
        raise ValueError("Publisher response is not a PDF")
    reader = PdfReader(BytesIO(data))
    if len(reader.pages) != 1:
        raise ValueError("Publisher table layout changed")
    return ResidenceRow(year=year, transactions=parse_transactions(
        reader.pages[0].extract_text(extraction_mode="layout"), year),
        source_url=url, sha256=hashlib.sha256(data).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("years", nargs="+", type=int)
    args = parser.parse_args()
    today = datetime.now(timezone(timedelta(hours=4))).date()
    if any(not 2000 <= year < today.year for year in args.years):
        parser.error("Choose completed report years starting in 2000")
    current = load_snapshot()
    rows = {row.year: row for row in current.rows}
    for year in sorted(set(args.years)):
        rows[year] = retrieve(year)
    candidate = current.model_copy(update={"rows": [rows[y] for y in sorted(rows)], "retrieved": today})
    folder = ROOT / "artifacts" / "hackathon-build" / "government-data"
    if not folder.resolve().is_relative_to(ROOT):
        raise ValueError("Candidate directory must stay inside the Hackathon workspace")
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / "government-data-candidate.json"
    with destination.open("x", encoding="utf-8", newline="\n") as file:
        file.write(candidate.model_dump_json(indent=2) + "\n")
    print(f"Review source hashes, counts and comparability before promoting {destination}")


if __name__ == "__main__":
    main()
