import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from exfilscope.registry import Registry
from phase2.demo import ROOT, run_demo, validate_sources, worker_environment
from phase2.paths import agent_python, embedding_cache

needs_agent = unittest.skipUnless(
    (embedding_cache() / "onnx.tar.gz").is_file() and agent_python().is_file(),
    "agent environment or embedding cache not installed; see docs/SETUP.md")


class SupervisorTests(unittest.TestCase):
    def test_worker_does_not_inherit_privileged_configuration(self):
        with patch.dict(os.environ, {"EXFILSCOPE_KEY_FILE": "private", "EXFILSCOPE_PROXY": "private",
                                     "EXFILSCOPE_POLICY_FILE": "private", "OPENAI_API_KEY": "private"}):
            env = worker_environment()
        self.assertFalse(any(k.startswith("EXFILSCOPE_") for k in env))
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_windows_system_root_is_preserved(self):
        with patch.dict(os.environ, {"SYSTEMROOT": "C:\\Windows"}):
            env = worker_environment()
        self.assertEqual(env["SYSTEMROOT"], "C:\\Windows")

    def test_windows_system_drive_is_preserved(self):
        with patch.dict(os.environ, {"SYSTEMDRIVE": "C:"}):
            env = worker_environment()
        self.assertEqual(env["SYSTEMDRIVE"], "C:")

    def test_registry_disagreement_rejected(self):
        registry = Registry.load(ROOT / "examples/registry.json")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "documents.json"
            path.write_text(json.dumps([]))
            with self.assertRaisesRegex(ValueError, "SOURCE_DISAGREEMENT"):
                validate_sources(path, registry)

    def test_existing_run_directory_not_overwritten(self):
        with TemporaryDirectory() as directory, self.assertRaises(FileExistsError):
            run_demo(Path(directory))

    def run_protocol(self, protocol):
        # New retained project-local evidence; no temporary deletion of forensic records.
        import time
        output = ROOT / "artifacts" / f"phase2-stub-test-{protocol}-{time.time_ns()}"
        rows = run_demo(output, mode="stub", protocols=(protocol,))
        self.assertEqual(len(rows), 3)
        for row in rows:
            with self.subTest(protocol=protocol, case=row["case"]):
                self.assertEqual(row["worker_status"], "SUBMITTED")
                self.assertTrue(row["expected_decision_met"])
                self.assertEqual(row["api_calls"], 1)
                self.assertEqual(row["runtime_events"], 1)
                self.assertEqual(row["result"], "MATCH")
                expected_count = 0 if row["case"] == "block" else 1
                self.assertEqual(row["observed_events"], expected_count)
                self.assertEqual(row["receiver_requests"], expected_count)
                self.assertFalse(row["receiver_protected_value_present"])
                self.assertFalse(row["receiver_trace_header_present"])
        audit = json.loads((output / "routine/privacy-audit.json").read_text())
        self.assertEqual(audit["known_value_recoveries"], {})
        self.assertTrue(audit["all_action_limits_respected"])
        if protocol == "https":
            from exfilscope.canonical import parse_body
            # The receiver's raw content is transient; independently observed HMACs are
            # verified by MATCH. The retained transcript shows protected input, not B.
            transcript = json.loads((output / "restricted/https/redact/attempt.json").read_text())
            self.assertTrue(parse_body(json.dumps(transcript["validated_proposal"]["body"])))

    @needs_agent
    def test_http_real_api_proxy_evidence(self):
        self.run_protocol("http")

    @needs_agent
    def test_https_real_api_proxy_evidence(self):
        self.run_protocol("https")


if __name__ == "__main__":
    unittest.main()
