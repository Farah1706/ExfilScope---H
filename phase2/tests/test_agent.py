import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from phase2.agent import run_agent
from phase2.contracts import MODEL, MODEL_MANIFEST_DIGEST, parse_proposal
from phase2.fixtures import CASES, stub_response
from phase2.model import LocalModel
from phase2.paths import ROOT, embedding_cache
from phase2.rag import Retriever
from phase2.tool import GatewayTool, local_url

CACHE = embedding_cache()
needs_cache = unittest.skipUnless((CACHE / "onnx.tar.gz").is_file(),
                                  "embedding cache not installed; see docs/SETUP.md")
GOOD = {"endpoint_alias": "AUTHORIZED", "method": "POST", "body": {"text": "benign"}}


class FakeRetriever:
    def retrieve(self, query):
        return [{"source_ref": "DOC_PUBLIC", "text": "benign"}]


class FakeModel:
    def __init__(self, raw=None, failure=None):
        self.raw = json.dumps(GOOD) if raw is None else raw
        self.failure = failure
        self.calls = 0

    def generate(self, task, documents):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.raw


class FakeTool:
    def __init__(self, failure=False):
        self.attempts = 0
        self.failure = failure

    def submit(self, proposal):
        self.attempts += 1
        if self.failure:
            raise TimeoutError("synthetic")
        return {"event_id": "fixture-event"}


class AgentTests(unittest.TestCase):
    def run_graph(self, model=None, tool=None, retriever=None):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "restricted" / "attempt.json"
            result = run_agent(retriever or FakeRetriever(), model or FakeModel(),
                               tool or FakeTool(), "query", "task", path)
            return result, json.loads(path.read_text(encoding="utf-8"))

    def test_valid_proposal_preserves_explicit_fields(self):
        value = dict(GOOD, body={"text": "benign", "data": None})
        self.assertEqual(parse_proposal(json.dumps(value)), value)

    def test_privileged_fields_rejected(self):
        for key in ["trace_id", "policy", "allow_redaction", "proxy", "url", "key_id"]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                parse_proposal(json.dumps(dict(GOOD, **{key: "untrusted"})))

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            parse_proposal('{"method":"POST","method":"POST"}')

    def test_nonfinite_and_nonobject_rejected(self):
        for raw in ['{"body":NaN}', '[]', 'null']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_proposal(raw)

    def test_large_and_wrong_typed_values_rejected(self):
        for value in [dict(GOOD, body={"text": 12}), dict(GOOD, body={"text": "x" * 17000})]:
            with self.assertRaises(ValueError):
                parse_proposal(json.dumps(value))

    def test_graph_submits_once_then_stops(self):
        model, tool = FakeModel(), FakeTool()
        result, record = self.run_graph(model, tool)
        self.assertEqual((result["status"], tool.attempts, model.calls), ("SUBMITTED", 1, 1))
        self.assertEqual(record["raw_proposal"], model.raw)

    def test_invalid_output_retained_without_submission(self):
        tool = FakeTool()
        result, record = self.run_graph(FakeModel("not JSON"), tool)
        self.assertEqual(result["status"], "INVALID_PROPOSAL")
        self.assertEqual(tool.attempts, 0)
        self.assertEqual(record["raw_proposal"], "not JSON")

    def test_model_failure_has_no_substitute(self):
        tool = FakeTool()
        result, record = self.run_graph(FakeModel(failure=TimeoutError()), tool)
        self.assertEqual(result["status"], "MODEL_FAILED")
        self.assertEqual(tool.attempts, 0)
        self.assertIsNone(record["raw_proposal"])

    def test_partial_model_output_retained(self):
        error = RuntimeError()
        error.partial_output = '{"unfinished"'
        result, record = self.run_graph(FakeModel(failure=error))
        self.assertEqual(result["status"], "MODEL_FAILED")
        self.assertEqual(record["raw_proposal"], error.partial_output)

    def test_retrieval_failure_stops_before_model(self):
        class Broken:
            def retrieve(self, query):
                raise ValueError()
        model = FakeModel()
        result, _ = self.run_graph(model=model, retriever=Broken())
        self.assertEqual(result["status"], "RETRIEVAL_FAILED")
        self.assertEqual(model.calls, 0)

    def test_submission_timeout_not_retried(self):
        tool = FakeTool(failure=True)
        result, _ = self.run_graph(tool=tool)
        self.assertEqual(result["status"], "SUBMISSION_FAILED")
        self.assertEqual(tool.attempts, 1)

    def test_wrong_live_proposal_is_not_replaced_by_fixture(self):
        model = FakeModel(json.dumps(GOOD))
        result, record = self.run_graph(model=model)
        self.assertEqual(result["status"], "SUBMITTED")
        self.assertEqual(record["validated_proposal"], GOOD)

    def test_no_raw_errors_in_minimized_summary(self):
        result, _ = self.run_graph(FakeModel(failure=RuntimeError("SYNTHETIC_PRIVATE_TEXT")))
        self.assertNotIn("SYNTHETIC_PRIVATE_TEXT", json.dumps(result))

    def test_tool_sends_only_to_execute_and_supplies_session(self):
        session = str(uuid4())
        calls = []
        real_client = httpx.Client

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"schema_version": "1.1", "session_id": session,
                                            "event_id": "fixture", "decision": "ALLOW"})

        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        with patch("phase2.tool.httpx.Client", side_effect=client):
            tool = GatewayTool("http://127.0.0.1:8081/execute", "https://127.0.0.1:8801/collect", session)
            tool.submit(GOOD)
            with self.assertRaises(RuntimeError):
                tool.submit(GOOD)
        self.assertEqual(len(calls), 1)
        self.assertEqual(str(calls[0].url), "http://127.0.0.1:8081/execute")
        payload = json.loads(calls[0].content)
        self.assertEqual(payload["session_id"], session)
        self.assertNotIn("trace_id", payload)
        self.assertNotIn("allow_redaction", payload)

    def test_http_failure_consumes_action_budget(self):
        tool = GatewayTool("http://127.0.0.1:8081/execute", "http://127.0.0.1:8801/collect", str(uuid4()))
        with patch("phase2.tool.httpx.Client", side_effect=TimeoutError()):
            with self.assertRaises(TimeoutError):
                tool.submit(GOOD)
        with self.assertRaises(RuntimeError):
            tool.submit(GOOD)

    def test_nonlocal_or_unsafe_api_urls_rejected(self):
        for value in ["http://example.com:8081/execute", "http://127.0.0.1:8081/other",
                      "http://user@127.0.0.1:8081/execute", "http://127.0.0.1:8081/execute?x=1"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                local_url(value, "/execute")

    def test_missing_embedding_cache_does_not_download(self):
        with TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, "CACHE_REQUIRED"):
            Retriever(ROOT / "examples/phase2/documents.json", Path(directory))

    @needs_cache
    def test_real_chroma_retrieval_and_source_consistency(self):
        retriever = Retriever(ROOT / "examples/phase2/documents.json", CACHE)
        self.assertEqual(retriever.retrieve(CASES["allow"]["query"], 1)[0]["source_ref"],
                         "DOC_PUBLIC:chunk_1")
        self.assertEqual(retriever.retrieve(CASES["redact"]["query"], 1)[0]["source_ref"],
                         "DOC_001:chunk_1")
        registry = json.loads((ROOT / "examples/registry.json").read_text())
        for item in registry:
            doc = next(d for d in retriever.documents if d["source_ref"] == item["source_ref"])
            self.assertEqual(doc["synthetic_value"], item["value"])
        for case in CASES:
            parse_proposal(stub_response(case, retriever.documents))

    @needs_cache
    def test_retrieval_returns_chunk_content_without_ground_truth(self):
        retriever = Retriever(ROOT / "examples/phase2/documents.json", CACHE)
        for case in CASES.values():
            for doc in retriever.retrieve(case["query"]):
                self.assertEqual(set(doc), {"source_ref", "text"})

    @needs_cache
    def test_model_prompt_excludes_ground_truth_fields(self):
        retriever = Retriever(ROOT / "examples/phase2/documents.json", CACHE)
        leaked = dict(retriever.retrieve(CASES["redact"]["query"])[0],
                      synthetic_value="GROUND_TRUTH_ONLY", id="api_key", expected="REDACT")
        response = SimpleNamespace(done_reason="stop", message=SimpleNamespace(content=json.dumps(GOOD)))
        with patch("phase2.model.Client") as constructor:
            client = constructor.return_value
            client.list.return_value = SimpleNamespace(models=[SimpleNamespace(model=MODEL, digest=MODEL_MANIFEST_DIGEST)])
            client.chat.return_value = response
            LocalModel().generate(CASES["redact"]["instruction"], [leaked])
        prompt = json.dumps(client.chat.call_args.kwargs["messages"])
        for field in ("synthetic_value", "GROUND_TRUTH_ONLY", '\\"id\\"', '\\"expected\\"'):
            self.assertNotIn(field, prompt)
        # The retrieved text itself, including the registered value, still reaches the model.
        self.assertIn("DOC_001:chunk_1", prompt)
        self.assertIn(retriever.documents[1]["synthetic_value"], prompt)

    def test_local_model_rejects_unpinned_digest_before_generation(self):
        with patch("phase2.model.Client") as constructor:
            client = constructor.return_value
            client.list.return_value = SimpleNamespace(
                models=[SimpleNamespace(model=MODEL, digest="unexpected")]
            )
            with self.assertRaisesRegex(RuntimeError, "MODEL_MANIFEST_DIGEST_MISMATCH"):
                LocalModel().generate("task", [])
            client.chat.assert_not_called()

    def test_local_model_fixed_identity_and_schema_request(self):
        response = SimpleNamespace(done_reason="stop", message=SimpleNamespace(content=json.dumps(GOOD)))
        with patch("phase2.model.Client") as constructor:
            client = constructor.return_value
            client.list.return_value = SimpleNamespace(models=[SimpleNamespace(model=MODEL, digest=MODEL_MANIFEST_DIGEST)])
            client.chat.return_value = response
            self.assertEqual(LocalModel().generate("task", []), json.dumps(GOOD))
            kwargs = client.chat.call_args.kwargs
            self.assertEqual(kwargs["model"], MODEL)
            self.assertIn("properties", kwargs["format"])
            self.assertFalse(kwargs["stream"])
            self.assertNotIn("tools", kwargs)


if __name__ == "__main__":
    unittest.main()
