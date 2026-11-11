"""Real loopback integration using an independently implemented Node signer."""

import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import httpx
import pytest

from exfilscope.contracts import RuntimeEvent
from exfilscope.lab import Lab
from exfilscope.ledger import read_events
from exfilscope.verifier import verify
from webapp.trust.capability import Issuer, Scope, Validator, unb64
from webapp.trust.dispatch import ProtectedDispatch
from webapp.trust.http_api import serve

CLIENT = Path(__file__).resolve().parents[1] / "trust/client.cjs"


@pytest.mark.integration
def test_node_client_protected_http_and_forensic_https(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the independent HTTP caller")
    scope = Scope("external-notice", "http_post", "AUTHORIZED", "POST", "COLLECT")
    with Lab(tmp_path / "lab", "https") as lab, subprocess.Popen(
        [node, str(CLIENT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, encoding="utf-8",
    ) as child:
        lines = queue.Queue()

        def read_lines():
            for line in child.stdout:
                lines.put(line)

        threading.Thread(target=read_lines, daemon=True).start()

        def receive():
            return json.loads(lines.get(timeout=15))

        try:
            key = Ed25519PublicKey.from_public_bytes(unb64(receive()["public_key"]))
            issuer = Issuer()
            validator = Validator(issuer.public_key)
            validator.register("node-client", key)
            with serve(ProtectedDispatch(lab, validator, scope)) as url:
                approved = issuer.issue("node-client", key, scope)

                def attempt(kind, token=None):
                    capability = token or issuer.issue("node-client", key, scope)
                    child.stdin.write(json.dumps({"url": url, "scope": scope.__dict__,
                                                  "capability": capability, "kind": kind}) + "\n")
                    child.stdin.flush()
                    return receive()

                with httpx.Client(trust_env=False) as http:
                    invalid = http.post(url, content='{"action":{},"action":{}}',
                                        headers={"Content-Type": "application/json"})
                    assert invalid.status_code == 400
                    assert invalid.json() == {"code": "INVALID_ENVELOPE"}
                    assert http.post(url, content="anything").status_code == 415
                    assert http.post(url, content=b"x" * 32_769,
                                     headers={"Content-Type": "application/json"}).status_code == 413

                for kind, code in (("invalid", "ISSUER_SIGNATURE_INVALID"),
                                   ("altered", "PROOF_NOT_BOUND_TO_ACTION"),
                                   ("destination", "OUT_OF_SCOPE_ENDPOINT_ID")):
                    assert attempt(kind) == {"status": 403, "result": {"code": code}}
                assert not sum(len(r.requests) for r in lab.receivers)
                assert not read_events(lab.a_path, RuntimeEvent, "A")
                accepted = attempt("valid", approved)
                assert accepted["status"] == 200
                assert accepted["result"]["decision"] == "ALLOW"
                assert accepted["result"]["receiver_status"] == 200
                assert attempt("valid", approved) == {
                    "status": 403, "result": {"code": "CAPABILITY_REPLAYED"},
                }
                event, = read_events(lab.a_path, RuntimeEvent, "A")
                assert accepted["result"]["event_id"] == str(event.event_id)
                lab.wait_for_health(event.decision_monotonic + 5)
                observed, health = lab.snapshot()
                verdict, = verify([event], observed, window=5, health=health,
                                  expected_boundary_id=lab.boundary_id, clock=lab.clock)
                assert verdict.result == "MATCH"
                assert verdict.network_event_id
                assert sum(len(r.requests) for r in lab.receivers) == 1

                lab.receivers[0].close()
                failed = attempt("valid")
                assert failed["status"] == 502
                assert failed["result"]["decision"] == "ALLOW"
                assert failed["result"]["event_id"] != str(event.event_id)
                assert sum(len(r.requests) for r in lab.receivers) == 1
            child.stdin.close()
            assert child.wait(timeout=10) == 0
        finally:
            if child.poll() is None:
                child.kill()
