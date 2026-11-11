import csv
from pathlib import Path
import shutil
import time
import unittest
from uuid import uuid4

from dashboard.evidence import load_catalog
from dashboard.prepare import DEFAULT_SOURCES, ROOT, prepare


def copy_run(source, destination, edit):
    """Copy a retained run's CSV and ledgers, then apply `edit` to its result rows."""
    for path in source.rglob("*"):
        if path.is_file() and (path.name == "results.csv" or ".sqlite" in path.name):
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    results = destination / "results.csv"
    with results.open(encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    rows, fields = edit(rows)
    with results.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


sources_retained = unittest.skipUnless(
    all(path.is_dir() for path in DEFAULT_SOURCES.values()),
    "snapshot source runs are local evidence and not part of a source checkout")


@sources_retained
class PreparationTests(unittest.TestCase):
    def scratch(self):
        return ROOT / "artifacts" / f"dashboard-test-export-{time.time_ns()}"

    def test_safe_export_preserves_original_sources(self):
        destination = self.scratch() / "minimized"
        report = prepare(destination)
        self.assertTrue(report["originals_unchanged"])
        self.assertEqual(report["known_value_recoveries"], {})
        self.assertEqual(report["incidents"], {"qwen3-live": 6, "engineering-faults": 14})
        catalog, issues = load_catalog(destination)
        self.assertEqual(issues, [])
        self.assertEqual(len(catalog["engineering-faults"].incidents), 14)

    def test_existing_destination_never_overwritten(self):
        destination = Path(__file__).resolve().parents[1] / "data"
        with self.assertRaises(FileExistsError):
            prepare(destination)

    def export_edited_faults(self, edit):
        root = self.scratch()
        copy_run(DEFAULT_SOURCES["engineering-faults"], root / "faults", edit)
        return prepare(root / "minimized", {"engineering-faults": root / "faults"})

    def test_results_without_verifier_pairing_are_rejected(self):
        def drop(rows):
            for row in rows:
                row.pop("network_event_id")
            return rows, list(rows[0])
        with self.assertRaisesRegex(ValueError, "LACKS_VERIFIER_PAIRING"):
            self.export_edited_faults(drop)

    def test_unknown_or_ambiguous_network_event_is_rejected(self):
        def unknown(rows):
            row = next(r for r in rows if r["scenario"] == "allow")
            row["network_event_id"] = str(uuid4())
            return rows, list(rows[0])
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS_NETWORK_SOURCE"):
            self.export_edited_faults(unknown)

    def test_unpaired_result_is_not_given_a_guessed_observation(self):
        def unpair(rows):
            row = next(r for r in rows if r["scenario"] == "allow" and r["protocol"] == "http")
            row.update(network_event_id="", result="UNVERIFIED", evidence_status="UNVERIFIED",
                       diagnostics="UNRECEIPTED_OBSERVATION")
            return rows, list(rows[0])
        root = self.scratch()
        copy_run(DEFAULT_SOURCES["engineering-faults"], root / "faults", unpair)
        prepare(root / "minimized", {"engineering-faults": root / "faults"})
        catalog, issues = load_catalog(root / "minimized")
        self.assertEqual(issues, [])
        row = next(i for i in catalog["engineering-faults"].incidents
                   if i.scenario == "allow" and i.protocol == "http")
        self.assertIsNone(row.observation)
        self.assertEqual(row.verification.result, "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
