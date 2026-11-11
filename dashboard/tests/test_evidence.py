import csv
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard.evidence import (SCHEMA, Bundle, DATA_ROOT, Incident, absence_explanation, comparison,
                                counts, export_csv, filter_records, load_catalog, select, utc)


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog, cls.issues = load_catalog()
        cls.live = cls.catalog["qwen3-live"].incidents
        cls.engineering = cls.catalog["engineering-faults"].incidents

    def record(self, case="allow"):
        return next(i for i in self.engineering if i.scenario == case)

    def test_actual_catalog_and_counts(self):
        self.assertEqual(self.issues, [])
        self.assertEqual(counts(self.live), {"total": 6, "decisions": {"ALLOW": 2, "REDACT": 2, "BLOCK": 2},
                                           "outcomes": {"MATCH": 6}, "protocols": {"HTTP": 3, "HTTPS": 3}})

    def test_recorded_fault_distribution(self):
        self.assertEqual(counts(self.engineering)["outcomes"], {"MATCH": 6, "MISMATCH": 6, "UNVERIFIED": 2})

    def test_filters_intersect_and_selection_uses_filtered_records(self):
        records = filter_records(self.engineering, protocols=["https"], decisions=["ALLOW"],
                                 outcomes=["MISMATCH"], scenarios=["destination_divergence"])
        self.assertEqual(len(records), 1)
        self.assertEqual(select(records, records[0].identifier), records[0])
        self.assertIsNone(select(records, self.live[0].identifier))

    def test_empty_filter_means_no_records(self):
        self.assertEqual(filter_records(self.live, protocols=[]), [])

    def test_search_trace_and_reason(self):
        row = self.live[0]
        self.assertEqual(filter_records(self.live, search=str(row.runtime.trace_id)), [row])
        self.assertEqual(len(filter_records(self.live, search="REDACTED_PROTECTED_VALUES")), 2)

    def test_run_and_time_filters(self):
        row = self.live[0]
        self.assertTrue(filter_records(self.live, runs=[row.run_id]))
        self.assertEqual(filter_records(self.live, start=row.runtime.decision_time,
                                       end=row.runtime.decision_time), [row])
        self.assertFalse(filter_records(self.live, runs=["unrelated"]))

    def test_all_three_results_preserved(self):
        self.assertEqual({i.verification.result for i in self.engineering}, {"MATCH", "MISMATCH", "UNVERIFIED"})

    def test_partial_mismatch_is_not_downgraded(self):
        data = self.record("payload_divergence").model_dump(mode="json")
        data["verification"]["evidence_status"] = "UNVERIFIED"
        data["verification"]["diagnostics"].append("COLLECTION_HEALTH_GAP")
        row = Incident.model_validate_json(json.dumps(data))
        self.assertEqual(row.verification.result, "MISMATCH")

    def test_exact_mismatch_labels(self):
        for case,label in [("block_bypass", "BLOCK_BYPASS"), ("payload_divergence", "PAYLOAD_DIVERGENCE"),
                           ("destination_divergence", "DESTINATION_DIVERGENCE")]:
            self.assertEqual(self.record(case).verification.labels, [label])

    def test_commitment_and_destination_comparison(self):
        self.assertEqual(comparison(self.record())["Payload commitment"], "Equal")
        self.assertEqual(comparison(self.record("payload_divergence"))["Payload commitment"], "Different")
        self.assertEqual(comparison(self.record("destination_divergence"))["Destination"], "Diverges")

    def test_incompatible_key_cannot_show_body_equality(self):
        data = self.record("payload_divergence").model_dump(mode="json")
        data["observation"]["key_id"] = "other-key"
        row = Incident.model_validate_json(json.dumps(data))
        self.assertEqual(comparison(row)["Payload commitment"], "Unavailable")

    def test_block_scope_and_null_permitted_body(self):
        row = self.record("block")
        self.assertIsNone(row.runtime.permitted)
        self.assertIn("does not prove absolute network absence", absence_explanation(row))
        self.assertIsNone(row.observation)

    def test_withheld_observation_never_restored(self):
        row = self.record("no_observation")
        self.assertIsNone(row.observation)
        self.assertTrue(row.observation_withheld)
        self.assertIn("withheld", absence_explanation(row))
        self.assertEqual(row.verification.result, "UNVERIFIED")

    def test_unknown_body_or_key_fields_rejected(self):
        for field in ["body", "hmac_key", "raw_headers"]:
            data = self.record().model_dump(mode="json")
            data["runtime"][field] = "unsafe"
            with self.assertRaises(ValueError):
                Incident.model_validate_json(json.dumps(data))

    def test_incompatible_event_schema_rejected(self):
        data = self.record().model_dump(mode="json")
        data["runtime"]["schema_version"] = "1.0"
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))

    def test_incompatible_result_schema_rejected(self):
        data = self.record().model_dump(mode="json")
        data["verification"]["schema_version"] = "1.0"
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))

    def test_bad_pair_rejected(self):
        data = self.record().model_dump(mode="json")
        data["observation"]["request_monotonic"] = data["runtime"]["decision_monotonic"] + 100
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))

    def test_missing_observation_cannot_be_allow_match(self):
        data = self.record().model_dump(mode="json")
        data["observation"] = None
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))

    def test_observation_must_be_the_verifier_paired_event(self):
        paired = self.record().model_dump(mode="json")
        cases = {"unpaired_observation_shown": ("network_event_id", None),
                 "other_network_event": ("network_event_id", "00000000-0000-4000-8000-000000000000"),
                 "other_runtime_event": ("runtime_event_id", "00000000-0000-4000-8000-000000000000")}
        for name, (field, value) in cases.items():
            data = json.loads(json.dumps(paired))
            data["verification"][field] = value
            with self.subTest(name), self.assertRaises(ValueError):
                Incident.model_validate_json(json.dumps(data))
        data = json.loads(json.dumps(paired))
        data["observation"] = None
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))

    def test_unpaired_verifier_results_need_no_network_event(self):
        for row in [self.record("block"), self.record("no_observation"), self.live[2]]:
            self.assertIsNone(row.verification.network_event_id)
            self.assertIsNone(row.observation)
            self.assertEqual(row.verification.runtime_event_id, row.runtime.event_id)

    def test_unverified_with_unpaired_observation_shows_none(self):
        data = self.record().model_dump(mode="json")
        data["observation"] = None
        data["verification"].update(network_event_id=None, result="UNVERIFIED",
                                    evidence_status="UNVERIFIED",
                                    diagnostics=["UNRECEIPTED_OBSERVATION"])
        row = Incident.model_validate_json(json.dumps(data))
        self.assertTrue(all(v == "Unavailable" for v in comparison(row).values()))

    def test_no_duplicate_incidents(self):
        data = self.catalog["qwen3-live"].model_dump(mode="json")
        data["incidents"].append(data["incidents"][0])
        with self.assertRaises(ValueError):
            Bundle.model_validate_json(json.dumps(data))

    def test_export_matches_filtered_records(self):
        rows = filter_records(self.engineering, outcomes=["UNVERIFIED"])
        result = list(csv.DictReader(io.StringIO(export_csv(rows).decode())))
        self.assertEqual(len(result), 2)
        self.assertEqual({r["trace_id"] for r in result}, {str(i.runtime.trace_id) for i in rows})
        self.assertTrue(all(r["result"] == "UNVERIFIED" for r in result))
        self.assertNotIn("body", result[0])
        self.assertNotIn("hmac_key", result[0])

    def test_counts_have_no_research_rate(self):
        self.assertNotIn("accuracy", counts(self.engineering))

    def test_missing_and_corrupt_catalog(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(load_catalog(root)[0], {})
            (root / "manifest.json").write_text("{broken")
            self.assertTrue(load_catalog(root)[1])

    def test_hash_mismatch_and_unknown_fields_reject_bundle(self):
        for update_hash in [False, True]:
            with TemporaryDirectory() as directory:
                root = Path(directory)
                data = self.catalog["qwen3-live"].model_dump(mode="json")
                data["secret"] = "unexpected"
                raw = json.dumps(data).encode()
                (root / "qwen3-live.json").write_bytes(raw)
                (root / "manifest.json").write_text(json.dumps({"schema_version": SCHEMA,
                    "files": {"qwen3-live": hashlib.sha256(raw).hexdigest() if update_hash else "0" * 64}}))
                self.assertFalse(load_catalog(root)[0])
                self.assertTrue(load_catalog(root)[1])

    def test_manifest_cannot_point_to_other_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(json.dumps({"schema_version": SCHEMA,
                                                           "files": {"../registry": "0" * 64}}))
            self.assertFalse(load_catalog(root)[0])

    def test_reading_filtering_export_does_not_write_snapshots(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA_ROOT.iterdir()}
        catalog, _ = load_catalog()
        export_csv(filter_records(catalog["qwen3-live"].incidents, protocols=["http"]))
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in DATA_ROOT.iterdir()}
        self.assertEqual(before, after)

    def test_snapshot_contains_no_known_synthetic_value(self):
        # Test-only access to registry; neither the UI nor its loader imports it.
        registry = json.loads((DATA_ROOT.parents[1] / "examples/registry.json").read_text())
        data = b"".join(p.read_bytes() for p in DATA_ROOT.iterdir())
        exports = export_csv(self.live + self.engineering)
        for item in registry:
            self.assertNotIn(item["value"].encode(), data + exports)

    def test_core_versions_and_time_display(self):
        self.assertEqual(self.live[0].runtime.schema_version, "1.1")
        self.assertEqual(self.live[0].runtime.proposed.schema_version, "1.0")
        self.assertIn("1970", utc(0))

    def test_unusable_timestamp_rejected(self):
        data = self.record().model_dump(mode="json")
        data["runtime"]["decision_time"] = 1e100
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))

    def test_match_requires_source_health(self):
        data = self.record("block").model_dump(mode="json")
        data["health_records"] = 0
        with self.assertRaises(ValueError):
            Incident.model_validate_json(json.dumps(data))


if __name__ == "__main__":
    unittest.main()
