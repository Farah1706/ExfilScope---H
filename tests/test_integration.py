import json
import time
from uuid import uuid4

import httpx
import pytest

from exfilscope.canonical import commitment, parse_body
from exfilscope.config import TRACE_HEADER
from exfilscope.contracts import Claim, ObservedEvent, ProposedAction, RuntimeEvent
from exfilscope.lab import Lab, free_port
from exfilscope.ledger import read_events
from exfilscope.privacy import routine_paths, scan_routine_files
from exfilscope.runtime import Runtime
from exfilscope.scenarios import SCENARIOS, run_fault_scenario
from exfilscope.verifier import verify

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=["http", "https"])
def lab(request, tmp_path_factory):
    parent = tmp_path_factory.mktemp("lab")
    with Lab(parent / request.param, request.param) as instance:
        observed, health = instance.snapshot()
        assert observed == [] and health
        assert all(h.kind in ("START", "PULSE") for h in health)
        yield instance


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_seven_scenarios_real_proxy(lab, scenario):
    trial = run_fault_scenario(lab, scenario, case=1, window=1.5)
    events_b = read_events(lab.b_path, ObservedEvent, "B")
    correlated = [b for b in events_b if b.trace_id == trial.event.trace_id]
    result = trial.verification
    if scenario in ("allow", "redact"):
        assert result.result == "MATCH" and result.evidence_status == "VERIFIED"
        assert len(correlated) == 1
        assert trial.event.claim == Claim.EXECUTED_SUCCESS
        # Proxy computed its commitment independently; no digest supplied in request.
        actual = lab.receivers[0].requests[-1]
        assert not actual["trace_present"]
        assert correlated[0].payload_hmac == commitment(parse_body(actual["body"]), lab.key)
        if scenario == "redact":
            assert all(i.value.encode() not in actual["body"] for i in lab.registry.items)
    elif scenario == "block":
        assert not correlated and trial.receiver_count == 0
        assert result.result == "MATCH" and result.evidence_status == "VERIFIED"
        assert result.diagnostics == ("SCOPED_PROXY_ABSENCE",)
    elif scenario == "no_observation":
        assert len(correlated) == 1 and trial.receiver_count == 1
        assert result.evidence_status == "UNVERIFIED"
    else:
        expected = {"block_bypass": "BLOCK_BYPASS", "payload_divergence": "PAYLOAD_DIVERGENCE",
                    "destination_divergence": "DESTINATION_DIVERGENCE"}[scenario]
        assert result.result == "MISMATCH" and result.evidence_status == "VERIFIED"
        assert expected in result.labels and len(correlated) == 1
        assert result.labels == (expected,)
        assert trial.event.claim == Claim.EXECUTED_SUCCESS
        assert trial.receiver_count == 1
    # The verifier's own pairing is the association exported for investigation.
    assert result.runtime_event_id == trial.event.event_id
    if scenario in ("block", "no_observation"):
        assert result.network_event_id is None
    else:
        assert result.network_event_id == correlated[0].event_id
    assert scan_routine_files(routine_paths(lab.directory), lab.registry) == {}


@pytest.mark.parametrize("scenario", ["block_bypass", "payload_divergence", "destination_divergence"])
def test_false_runtime_claim_is_a_separate_diagnostic(lab, scenario):
    trial = run_fault_scenario(lab, scenario, case=1, window=1.5, claim_mode="false_not_executed")
    expected = {"block_bypass": "BLOCK_BYPASS", "payload_divergence": "PAYLOAD_DIVERGENCE",
                "destination_divergence": "DESTINATION_DIVERGENCE"}[scenario]
    assert trial.event.claim == Claim.NOT_EXECUTED
    assert trial.verification.labels == (expected, "CLAIM_INCONSISTENCY")
    assert trial.verification.evidence_status == "VERIFIED"


def test_payload_divergence_after_allow_with_success(lab):
    trial = run_fault_scenario(lab, "payload_divergence", case=0, window=1.5)
    assert trial.event.decision.value == "ALLOW" and trial.event.claim == Claim.EXECUTED_SUCCESS
    assert trial.verification.labels == ("PAYLOAD_DIVERGENCE",)


def test_monitor_ignores_caller_supplied_payload_fingerprint(lab):
    fake = "f" * 64
    body = '{ "b":2, "a":1 }'
    send(lab, body, headers={"Content-Type": "application/json", TRACE_HEADER: str(uuid4()),
                             "X-ExfilScope-Payload-HMAC": fake})
    event = read_events(lab.b_path, ObservedEvent, "B")[-1]
    assert event.payload_hmac == commitment(parse_body(body), lab.key)
    assert event.payload_hmac != fake


def send(lab, body, *, headers=None, path="/collect"):
    with httpx.Client(proxy=lab.proxy, trust_env=False, verify=lab.tls_context or True,
                      follow_redirects=False) as client:
        return client.post(lab.allowed_url.removesuffix("/collect") + path,
                           content=body, headers=headers or {"Content-Type": "application/json"})


@pytest.mark.parametrize("target,host,endpoint,result,labels,anomaly", [
    ("forbidden", "allowed", "UNAUTHORIZED", "MISMATCH", ("DESTINATION_DIVERGENCE",), True),
    ("allowed", "forbidden", "AUTHORIZED", "UNVERIFIED", (), True),
    ("allowed", "allowed", "AUTHORIZED", "MATCH", (), False),
    ("alternate", "allowed", "ALTERNATE_HOST", "MISMATCH", ("DESTINATION_DIVERGENCE",), True),
    ("allowed", "alternate", "AUTHORIZED", "UNVERIFIED", (), True),
])
def test_destination_is_forwarding_target_not_host_header(lab, target, host, endpoint, result,
                                                          labels, anomaly):
    urls = {"allowed": lab.allowed_url, "forbidden": lab.forbidden_url, "alternate": lab.alternate_url}
    auth = lab.gateway.authorize(ProposedAction(url=lab.allowed_url, body=json.dumps(
        {"case": 7, "data": [{"text": "harmless"}]})))
    before = [len(r.requests) for r in lab.receivers]
    with httpx.Client(proxy=lab.proxy, trust_env=False, verify=lab.tls_context or True,
                      follow_redirects=False) as client:
        response = client.post(urls[target], content=auth.permitted_action.body.encode(), headers={
            "Content-Type": "application/json", TRACE_HEADER: str(auth.event.trace_id),
            "Host": httpx.URL(urls[host]).netloc.decode()})
    event = auth.event.model_copy(update={"claim": Claim.EXECUTED_SUCCESS,
                                          "response_status": response.status_code,
                                          "completion_time": time.time(),
                                          "completion_monotonic": time.monotonic()})
    lab.writer.update(event)
    time.sleep(max(0, event.decision_monotonic + 1.5 - time.monotonic()))
    lab.wait_for_health(event.decision_monotonic + 1.5)
    events_b, health = lab.snapshot()
    observed = [b for b in events_b if b.trace_id == event.trace_id]
    delivered = [i for i, r in enumerate(lab.receivers) if len(r.requests) > before[i]]
    assert delivered == [list(urls).index(target)]
    assert [b.observed.endpoint_id for b in observed] == [endpoint]
    assert ("HOST_HEADER_MISMATCH" in observed[0].anomalies) is anomaly
    verdict = next(r for r in verify(read_events(lab.a_path, RuntimeEvent, "A"), events_b,
                                     window=1.5, health=health,
                                     expected_boundary_id=lab.boundary_id, clock=lab.clock)
                   if r.runtime_event_id == event.event_id)
    assert verdict.result == result and verdict.labels == labels


def test_missing_and_duplicate_trace_stay_unattributed(lab):
    secret = lab.registry.items[0].value
    send(lab, json.dumps({"data": secret}))
    send(lab, "{}", headers=[("Content-Type", "application/json"),
                             (TRACE_HEADER, str(uuid4())), (TRACE_HEADER, str(uuid4()))])
    events = read_events(lab.b_path, ObservedEvent, "B")[-2:]
    assert all(e.trace_id is None for e in events)
    assert all("MISSING_OR_DUPLICATE_TRACE" in e.anomalies for e in events)
    assert all(not r["trace_present"] for r in lab.receivers[0].requests[-2:])
    assert scan_routine_files(routine_paths(lab.directory), lab.registry) == {}


def test_malformed_network_json_and_secret_metadata_are_minimized(lab):
    secret = lab.registry.items[0].value
    send(lab, '{"x":1,"x":2}', path=f"/collect?data={secret}",
         headers={"Content-Type": "application/json", TRACE_HEADER: secret, "X-secret": secret})
    event = read_events(lab.b_path, ObservedEvent, "B")[-1]
    assert event.payload_hmac is None and event.trace_id is None
    assert {"INVALID_TRACE", "UNSUPPORTED_URL_COMPONENT", "UNSUPPORTED_BODY"} <= set(event.anomalies)
    assert secret not in event.model_dump_json()
    assert not lab.receivers[0].requests[-1]["trace_present"]


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_timeout_keeps_independent_request_evidence(tmp_path, protocol):
    # MATCH requires an idle opening boundary. The module-scoped lab can still be
    # processing the preceding malformed-request test's CLIENT_CLOSE callback.
    # Isolate this positive case rather than changing coverage rules or deadlines.
    with Lab(tmp_path / protocol, protocol) as lab:
        initial_observations, initial_health = lab.snapshot()
        assert initial_observations == []
        assert initial_health and not initial_health[-1].open_clients
        assert not initial_health[-1].pending_requests
        auth = lab.gateway.authorize(ProposedAction(
            url=lab.allowed_url.replace("/collect", "/timeout"), body="{}"))
        runtime = Runtime(lab.writer, lab.proxy, lab.tls_context, timeout=0.2)
        event = runtime.execute(auth)
        assert event.claim == Claim.EXECUTED_FAILED
        time.sleep(1.5)
        observations = read_events(lab.b_path, ObservedEvent, "B")
        lab.wait_for_health(event.decision_monotonic + 1.5)
        _, health = lab.snapshot()
        result = verify([event], observations, window=1.5, health=health,
                        expected_boundary_id=lab.boundary_id, clock=lab.clock)[0]
        assert result.result == "MATCH"
        assert result.network_event_id is not None


def test_redirects_are_not_followed(lab):
    before = len(lab.receivers[0].requests)
    auth = lab.gateway.authorize(ProposedAction(url=lab.allowed_url.replace("/collect", "/redirect"),
                                                body="{}"))
    event = lab.runtime.execute(auth)
    assert event.claim == Claim.EXECUTED_SUCCESS and event.response_status == 307
    assert len(lab.receivers[0].requests) == before + 1
    assert len([b for b in read_events(lab.b_path, ObservedEvent, "B")
                if b.trace_id == event.trace_id]) == 1


def test_pre_send_proxy_failure_is_unverified(lab):
    auth = lab.gateway.authorize(ProposedAction(url=lab.allowed_url, body="{}"))
    event = Runtime(lab.writer, f"http://127.0.0.1:{free_port()}", lab.tls_context).execute(auth)
    assert event.claim == Claim.EXECUTED_FAILED
    time.sleep(1.5)
    result = verify([event], read_events(lab.b_path, ObservedEvent, "B"), window=1.5)[0]
    assert result.result == "UNVERIFIED" and result.evidence_status == "UNVERIFIED"


def test_runtime_and_monitor_ledgers_are_separate(lab):
    assert lab.a_path != lab.b_path
    events_a = read_events(lab.a_path, RuntimeEvent, "A")
    events_b = read_events(lab.b_path, ObservedEvent, "B")
    assert events_a and events_b
    with pytest.raises(ValueError):
        read_events(lab.a_path, ObservedEvent, "B")
