"""Authenticated operator lifecycle and real protected-boundary regression tests."""

import json
import sys

from fastapi.testclient import TestClient
import pytest

from exfilscope.lab import Lab
from webapp import readiness, server
from webapp.contracts import RunRequest, STAGE_IDS
from webapp.runs import Busy, RunManager
from webapp.trust.audit import TrustAudit
from webapp.trust.lifecycle import run_lifecycle, wait_command
from webapp.trust.model import Citation, Selection

ACTOR = "local-session-0123456789abcdef"
BODY = {"scenario_id": "government-trust", "mode": "trust", "protocol": "https",
        "trust_driver": "qwen3", "operator_lifecycle": True}
BASE = "http://127.0.0.1:8600"
HEADERS = {"Origin": BASE, "X-ExfilScope": "1"}


@pytest.fixture
def manager(tmp_path):
    manager = RunManager(tmp_path / "runs", command=[
        sys.executable, "-c", "import sys,time; sys.stdin.read(); time.sleep(30)"])
    yield manager
    manager.shutdown()


def waiting(manager, state):
    manager.active["record"]["stages"][STAGE_IDS.index("gateway")]["facts"]["operator_state"] = state


def test_requires_qwen3_trust():
    for field, value in (("mode", "lab"), ("trust_driver", "scripted"), ("operator_lifecycle", 1)):
        with pytest.raises(ValueError):
            RunRequest.model_validate({**BODY, field: value})


def test_operator_commands_are_ordered_bound_and_single_use(manager):
    with pytest.raises(ValueError, match="OPERATOR_SESSION_REQUIRED"):
        manager.start(RunRequest.model_validate(BODY))
    record = manager.start(RunRequest.model_validate(BODY), ACTOR)
    run_id = record["run_id"]
    waiting(manager, "WAITING_AUTHORIZATION")
    with pytest.raises(PermissionError):
        manager.authority_command(run_id, "authorize", "local-session-0000000000000000")
    with pytest.raises(Busy):
        manager.authority_command(run_id, "recover", ACTOR)
    assert manager.authority_command(run_id, "authorize", ACTOR)["status"] == "queued"
    path = manager.path(run_id) / "operator-authorize.json"
    content = path.read_bytes()
    assert json.loads(content)["actor"] == ACTOR
    with pytest.raises(Busy):
        manager.authority_command(run_id, "authorize", ACTOR)
    assert path.read_bytes() == content
    manager.shutdown()
    with pytest.raises(Busy):
        manager.authority_command(run_id, "recover", ACTOR)


def test_operator_api_auth_and_payload_guards(manager, monkeypatch):
    monkeypatch.setattr(readiness, "check", lambda: {
        "items": [{"id": "ollama", "state": "healthy"}],
        "modes": {"trust": {"ready": True, "blocking": []}}})
    app = server.create_app(token="test-operator-launch-token", port=8600, manager=manager)
    with TestClient(app, base_url=BASE) as client:
        assert client.post("/api/runs", json=BODY, headers=HEADERS).status_code == 401
        client.post("/api/session", json={"token": "test-operator-launch-token"}, headers=HEADERS).raise_for_status()
        record = client.post("/api/runs", json=BODY, headers=HEADERS).json()
        run_id = record["run_id"]
        waiting(manager, "WAITING_AUTHORIZATION")
        url = f"/api/runs/{run_id}/authority"
        assert client.post(url, json={"operation": "authorize"}).status_code == 403
        for payload in ({"operation": True}, {"operation": "unknown"},
                        {"operation": "authorize", "actor": ACTOR}, []):
            assert client.post(url, json=payload, headers=HEADERS).status_code == 422
        assert client.post(url, json={"operation": "recover"}, headers=HEADERS).status_code == 409
        assert client.post(url, json={"operation": "authorize"}, headers=HEADERS).status_code == 202


def test_pending_authority_is_not_resumed_after_restart(tmp_path):
    first = RunManager(tmp_path / "runs")
    run_id = "run-20261105-000000-01234567"
    path = first.path(run_id)
    path.mkdir()
    record = {**BODY, "run_id": run_id, "status": "running", "finished": None}
    (path / "lifecycle.json").write_text(json.dumps(record))
    first.ownership.release()
    successor = RunManager(tmp_path / "runs")
    try:
        successor.recover()
        assert successor.get(run_id)["status"] == "interrupted"
        with pytest.raises(Busy):
            successor.authority_command(run_id, "recover", ACTOR)
    finally:
        successor.shutdown()


@pytest.mark.parametrize("operation", ["authorize", "revoke", "recover"])
def test_corrupt_or_misattributed_command_fails_closed(tmp_path, operation):
    path = tmp_path / ("operator-" + operation + ".json")
    path.write_text(json.dumps({"operation": operation, "actor": "other-session", "at": 1.0}))
    with pytest.raises(RuntimeError, match="OPERATOR_COMMAND_INVALID"):
        wait_command(tmp_path, operation, ACTOR, lambda *args, **kwargs: None)


@pytest.mark.integration
@pytest.mark.parametrize("protocol", ["http", "https"])
def test_real_receiver_withdrawal_and_new_identity_recovery(tmp_path, monkeypatch, protocol):
    import webapp.trust.lifecycle as lifecycle
    import webapp.trust.model as model

    def approve(run, operation, actor, stage, **facts):
        return {"operation": operation, "actor": actor, "at": 1.0}

    monkeypatch.setattr(lifecycle, "wait_command", approve)
    monkeypatch.setattr(model, "propose_selection", lambda endpoint, mandate: (
        Selection(endpoint_id=endpoint, citations=[Citation(year=2025, metric="residence_transactions")]), 0.1))
    with Lab(tmp_path / "lab", protocol) as lab:
        audit, rows = run_lifecycle(lab, 5, lambda *args, **kwargs: None, tmp_path, ACTOR)
        assert [a["receiver_requests"] for a in audit["attempts"]] == [1, 0, 0, 1, 0]
        assert [a["code"] for a in audit["attempts"]] == [
            "CAPABILITY_VALID", "AGENT_REVOKED", "AGENT_REVOKED", "CAPABILITY_VALID", "AGENT_REVOKED"]
        assert len(rows) == 2 and all(r["result"] == "MATCH" for r in rows)
        assert rows[0]["runtime_event_id"] != rows[1]["runtime_event_id"]
        assert audit["operator_events"][0]["agent_key_fingerprint"] != audit["operator_events"][2]["agent_key_fingerprint"]
        assert len({r["network_event_id"] for r in rows}) == 2
        assert sum(len(r.requests) for r in lab.receivers) == 2
    TrustAudit.model_validate_json(json.dumps(audit))


@pytest.mark.parametrize("mutation", ["claim", "selection", "event", "rejection"])
def test_audit_cannot_claim_unsupported_selection_or_pairing(tmp_path, mutation):
    import hashlib
    import shutil
    from webapp.paths import ROOT
    from webapp.trust.audit import load_trust_audit

    source = ROOT / "webapp/public_samples/run-20261105-153504-68a5eba2/export"
    target = tmp_path / "export"
    shutil.copytree(source, target)
    audit = json.loads((target / "trust-audit.json").read_bytes())
    if mutation == "claim":
        audit["attempts"][0]["runtime_claim"] = "NOT_EXECUTED"
    elif mutation == "selection":
        audit["attempts"][0]["model_selection"]["transactions"] += 1
    elif mutation == "event":
        audit["attempts"][0]["runtime_event_id"] = "00000000-0000-0000-0000-000000000000"
    else:
        audit["attempts"][1]["receiver_requests"] = 1
    data = json.dumps(audit).encode()
    (target / "trust-audit.json").write_bytes(data)
    manifest = json.loads((target / "manifest.json").read_bytes())
    manifest["files"]["trust-audit.json"] = hashlib.sha256(data).hexdigest()
    (target / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="TRUST_.*DISAGREEMENT"):
        load_trust_audit(target)
