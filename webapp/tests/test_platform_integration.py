"""Real HTTP/HTTPS runs through the platform service: the fixed runner, the lab harness,
a separate mitmdump, both ledgers, the verifier and the validated export.

Agent runs need the agent environment and embedding cache (stub) and Ollama with the
pinned model (live, opt-in with EXFILSCOPE_PLATFORM_LIVE=1). They skip with a reason.
"""

import os
import time

from fastapi.testclient import TestClient
import pytest

from exfilscope.registry import Registry
from webapp import readiness, server
from webapp.paths import ROOT
from webapp.runs import RunManager

pytestmark = pytest.mark.integration
TOKEN = "integration-launch-token-0123456789"
BASE = "http://127.0.0.1:8600"
HEADERS = {"Origin": BASE, "X-ExfilScope": "1"}
REGISTRY = Registry.load(ROOT / "examples/registry.json")


@pytest.fixture
def client(tmp_path):
    manager = RunManager(runs=tmp_path / "runs")
    app = server.create_app(token=TOKEN, port=8600, manager=manager)
    with TestClient(app, base_url=BASE) as c:
        assert c.post("/api/session", json={"token": TOKEN}, headers=HEADERS).status_code == 200
        yield c
    manager.shutdown()


def run(client, payload, timeout=200):
    response = client.post("/api/runs", json=payload, headers=HEADERS)
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = client.get(f"/api/runs/{run_id}").json()
        if record["status"] != "running":
            break
        time.sleep(0.5)
    assert record["status"] == "succeeded", record
    assert all(s["status"] == "complete" for s in record["stages"]), record["stages"]
    view = client.get(f"/api/investigations/run:{run_id}")
    assert view.status_code == 200
    # Nothing the browser receives about a real run carries a registered value.
    for text in (client.get(f"/api/runs/{run_id}").text, view.text,
                 client.get(f"/api/investigations/run:{run_id}/export.csv").text):
        assert not REGISTRY.contains(text)
    return record, view.json()["incidents"][0]


@pytest.mark.parametrize("scenario,protocol,decision,result,labels", [
    ("transmission-after-rejection", "http", "BLOCK", "MISMATCH", ["BLOCK_BYPASS"]),
    ("redaction-reversed", "https", "REDACT", "MISMATCH", ["PAYLOAD_DIVERGENCE"]),
    ("prohibited-transfer", "https", "BLOCK", "MATCH", []),
    ("missing-observation", "http", "ALLOW", "UNVERIFIED", ["NO_CORRELATED_OBSERVATION"]),
    ("unexpected-destination", "https", "ALLOW", "MISMATCH", ["DESTINATION_DIVERGENCE"]),
])
def test_lab_scenarios_end_to_end(client, scenario, protocol, decision, result, labels):
    _, incident = run(client, {"scenario_id": scenario, "mode": "lab", "protocol": protocol})
    assert incident["runtime"]["decision"] == decision
    assert incident["verification"]["result"] == result
    assert incident["verification"]["labels"] == labels
    if decision == "BLOCK" and result == "MATCH":
        assert incident["observation"] is None and incident["scoped_absence"]
        assert "SCOPED_PROXY_ABSENCE" in incident["verification"]["diagnostics"]
    if scenario == "missing-observation":
        assert incident["observation"] is None and incident["observation_withheld"]
    if result == "MISMATCH" and decision != "BLOCK":
        assert incident["observation"] is not None


def test_false_claim_adds_claim_inconsistency(client):
    _, incident = run(client, {"scenario_id": "modified-after-approval", "mode": "lab",
                               "protocol": "http", "claim_mode": "false_not_executed"})
    assert incident["runtime"]["claim"] == "NOT_EXECUTED"
    assert set(incident["verification"]["labels"]) == {"PAYLOAD_DIVERGENCE", "CLAIM_INCONSISTENCY"}


def test_government_trust_extension_end_to_end(client):
    record, incident = run(client, {"scenario_id": "government-trust", "mode": "trust",
                                    "protocol": "https"})
    audit = client.get(f"/api/trust/{record['run_id']}").json()
    accepted = [a for a in audit["attempts"] if a["trust"] == "ACCEPTED"]
    rejected = [a for a in audit["attempts"] if a["trust"] == "REJECTED"]
    assert len(accepted) == 1 and accepted[0]["receiver_requests"] == 1
    assert {a["code"] for a in rejected} == {
        "CAPABILITY_REPLAYED", "OUT_OF_SCOPE_ENDPOINT_ID", "CAPABILITY_EXPIRED",
        "ISSUER_SIGNATURE_INVALID", "PROOF_OF_POSSESSION_INVALID", "AGENT_REVOKED"}
    assert all(a["gateway"] == "NOT_CALLED" and a["receiver_requests"] == 0 for a in rejected)
    assert incident["verification"]["result"] == "MATCH"
    assert incident["display_origin"] == "Government Trust extension"
    assert accepted[0]["observation_paired"] is True
    assert accepted[0]["runtime_claim"] == "EXECUTED_SUCCESS"
    assert all(a["observation_paired"] is False and a["runtime_claim"] is None for a in rejected)
    by_code = {a["code"]: a for a in rejected}
    proposed = accepted[0]["proposed_action_hmac"]
    assert proposed == by_code["CAPABILITY_REPLAYED"]["proposed_action_hmac"]
    assert proposed != by_code["OUT_OF_SCOPE_ENDPOINT_ID"]["proposed_action_hmac"]


def _agent_ready(mode):
    state = readiness.check()["modes"][mode]
    return state["ready"], ", ".join(state["blocking"])


def test_stub_agent_pipeline_end_to_end(client):
    ready, blocking = _agent_ready("stub")
    if not ready:
        pytest.skip(f"agent resources unavailable: {blocking}")
    _, incident = run(client, {"scenario_id": "confidential-request", "mode": "stub",
                               "protocol": "http"}, timeout=420)
    assert incident["origin"] == "Deterministic replay"
    assert incident["runtime"]["decision"] == "REDACT" and incident["verification"]["result"] == "MATCH"


def test_live_qwen3_end_to_end(client):
    if os.environ.get("EXFILSCOPE_PLATFORM_LIVE") != "1":
        pytest.skip("live model run is opt-in: set EXFILSCOPE_PLATFORM_LIVE=1")
    ready, blocking = _agent_ready("live")
    if not ready:
        pytest.skip(f"live agent unavailable: {blocking}")
    _, incident = run(client, {"scenario_id": "prohibited-transfer", "mode": "live",
                               "protocol": "https"}, timeout=600)
    # The model's proposal decides the gateway outcome; report what happened, never assume.
    assert incident["origin"] == "LLM run"
    assert incident["verification"]["result"] in ("MATCH", "MISMATCH", "UNVERIFIED")


# ---- separate service processes sharing one runs folder ------------------------------------

def _free_port():
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _service(runs, token):
    import subprocess

    import httpx

    from webapp.paths import core_python

    port = _free_port()
    env = {**os.environ, "EXFILSCOPE_PLATFORM_RUNS": str(runs), "EXFILSCOPE_UI_TOKEN": token,
           "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "src")])}
    process = subprocess.Popen(
        [str(core_python()), "-B", "-m", "webapp.server", "--port", str(port)], cwd=ROOT,
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base = f"http://127.0.0.1:{port}"
    client = httpx.Client(base_url=base, trust_env=False, timeout=10)
    deadline = time.time() + 30
    while True:
        try:
            health = client.get("/healthz").json()
            break
        except httpx.HTTPError:
            assert process.poll() is None and time.time() < deadline, "service did not start"
            time.sleep(0.2)
    headers = {"Origin": base, "X-ExfilScope": "1"}
    assert client.post("/api/session", json={"token": token}, headers=headers).status_code == 200
    return process, client, headers, health


def _stop(process):
    import subprocess

    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True,
                           check=False)
        else:
            process.kill()
    process.wait(timeout=30)


def _wait(client, run_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = client.get(f"/api/runs/{run_id}").json()
        if record["status"] != "running":
            return record
        time.sleep(0.5)
    raise AssertionError("run did not finish")


def test_two_service_processes_share_runs_safely(tmp_path):
    runs = tmp_path / "runs"
    payload = {"scenario_id": "unexpected-destination", "mode": "lab", "protocol": "http"}
    services = []
    try:
        a = _service(runs, "owner-service-token-0000000001")
        services.append(a)
        b = _service(runs, "second-service-token-000000002")
        services.append(b)
        assert a[3]["run_owner"] is True and b[3]["run_owner"] is False
        refused = b[1].post("/api/runs", json=payload, headers=b[2])
        assert refused.status_code == 409 and refused.json()["error"] == "RUNS_OWNED_BY_OTHER_SERVICE"

        started = a[1].post("/api/runs", json=payload, headers=a[2])
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        # A third service starting while the owner is mid-run must not touch the run.
        c = _service(runs, "third-service-token-0000000003")
        services.append(c)
        assert c[3]["run_owner"] is False
        assert b[1].get(f"/api/runs/{run_id}").json()["status"] == "running"
        assert c[1].get(f"/api/runs/{run_id}").json()["status"] == "running"
        final = _wait(a[1], run_id)
        assert final["status"] == "succeeded"
        assert b[1].get(f"/api/runs/{run_id}").json()["status"] == "succeeded"
        assert b[1].get(f"/api/investigations/run:{run_id}").status_code == 200

        # Crash: kill the owner's whole process tree during a run. Its OS lock goes with it,
        # so the next service becomes owner and records the run as interrupted.
        second = a[1].post("/api/runs", json=payload, headers=a[2]).json()["run_id"]
        time.sleep(2)
        _stop(a[0])
        _stop(b[0])
        _stop(c[0])
        d = _service(runs, "recovery-service-token-000004")
        services.append(d)
        assert d[3]["run_owner"] is True
        recovered = d[1].get(f"/api/runs/{second}").json()
        assert recovered["status"] == "interrupted"
        assert recovered["error"] == "SERVICE_STOPPED_DURING_RUN"
        assert d[1].get(f"/api/runs/{run_id}").json()["status"] == "succeeded"
    finally:
        for process, client, _, _ in services:
            client.close()
            _stop(process)


def test_live_trust_driver_end_to_end(client):
    if not any(item["id"] == "ollama" and item["state"] == "healthy"
               for item in readiness.check()["items"]):
        pytest.skip("Dedicated pinned Ollama listener unavailable")
    record, incident = run(client, {"scenario_id": "government-trust", "mode": "trust",
                                    "protocol": "https", "trust_driver": "qwen3"})
    audit = client.get(f"/api/trust/{record['run_id']}").json()
    assert audit["driver"] == "qwen3"
    assert audit["task"]["task"] == "residence-pilot-workload-brief"
    assert (audit["official_reference"]["year"], audit["official_reference"]["transactions"]) == (2025, 6998414)
    assert len(audit["model_seconds"]) == 2 and all(x > 0 for x in audit["model_seconds"])
    accepted, rejected, altered = audit["attempts"]
    assert (accepted["gateway"], accepted["receiver_requests"]) == ("ALLOW", 1)
    assert len(accepted["grounding_checks"]) == 3 and accepted["citations"]
    assert (rejected["code"], rejected["gateway"], rejected["receiver_requests"]) == (
        "OUT_OF_SCOPE_ENDPOINT_ID", "NOT_CALLED", 0)
    assert (altered["code"], altered["gateway"], altered["receiver_requests"], altered["fixture"]) == (
        "UNGROUNDED_PUBLIC_DATA", "NOT_CALLED", 0, "ALTERED_FIGURE")
    assert incident["observation"] is not None
    assert incident["verification"]["result"] == "MATCH"
