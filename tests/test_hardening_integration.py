"""Actual health, permission, egress and certificate probes in the controlled local lab."""

import json
import socket
import sqlite3
import ssl
import time

import httpx
import pytest

from exfilscope.contracts import ProposedAction
from exfilscope.isolation import probe_write_access
from exfilscope.lab import Lab
from exfilscope.scenarios import run_fault_scenario
from exfilscope.verifier import verify

pytestmark = pytest.mark.integration


def check(lab, event, window=1.5, view=None, health_view=None):
    bb, hh = lab.snapshot()
    return verify([event], bb if view is None else view, health=hh if health_view is None else health_view,
                  expected_boundary_id=lab.boundary_id, window=window, clock=lab.clock)[0]


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_actual_cross_writer_access_is_detected_not_claimed_separate(tmp_path, protocol):
    with Lab(tmp_path / protocol, protocol, check_permissions=True) as lab:
        result = json.loads((lab.b_path.parent / "monitor-permission-probe.json").read_text())
        assert result["monitor_write_A"] == "WRITABLE"
        assert probe_write_access(lab.b_path) == "WRITABLE"
        # Both actual identities can write the other ledger; evidence rows are untouched.
        for path in (lab.a_path, lab.b_path):
            with sqlite3.connect(path) as db:
                assert db.execute("SELECT count(*) FROM events").fetchone()[0] == 0
                assert db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'permission_probe_%'") \
                    .fetchall() == []


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_wrapper_never_falls_back_to_direct_egress_when_proxy_dies(tmp_path, protocol):
    with Lab(tmp_path / protocol, protocol) as lab:
        authorization = lab.gateway.authorize(ProposedAction(url=lab.allowed_url, body="{}"))
        lab.process.terminate()
        lab.process.wait(timeout=5)
        event = lab.runtime.execute(authorization)
        assert event.claim.value == "EXECUTED_FAILED"
        assert not any(receiver.requests for receiver in lab.receivers)
        time.sleep(1.5)
        result = check(lab, event)
        assert result.evidence_status == "UNVERIFIED"
        assert "NO_UNIQUE_MONITOR_COVERAGE" in result.diagnostics


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_monitor_killed_during_block_window_is_unverified(tmp_path, protocol):
    with Lab(tmp_path / protocol, protocol) as lab:
        event = lab.runtime.execute(lab.gateway.authorize(ProposedAction(
            url=lab.allowed_url, body=json.dumps({"data": lab.registry.items[0].value}))))
        time.sleep(0.3)
        lab.process.terminate()
        lab.process.wait(timeout=5)
        time.sleep(max(0, event.decision_monotonic + 1.5 - time.monotonic()))
        result = check(lab, event)
        assert result.result != "MATCH" and result.evidence_status == "UNVERIFIED"


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_live_sqlite_collection_stall_invalidates_window(tmp_path, protocol):
    with Lab(tmp_path / protocol, protocol) as lab:
        blocker = sqlite3.connect(lab.b_path)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            event = lab.runtime.execute(lab.gateway.authorize(ProposedAction(
                url=lab.allowed_url, body=json.dumps({"data": lab.registry.items[0].value}))))
            time.sleep(1.5)
        finally:
            blocker.rollback()
            blocker.close()
        lab.wait_for_health(event.decision_monotonic + 1.5)
        result = check(lab, event)
        assert result.evidence_status == "UNVERIFIED"
        assert "COLLECTION_HEALTH_GAP" in result.diagnostics


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_missing_record_and_receipt_and_unattributed_traffic_are_unverified(tmp_path, protocol):
    with Lab(tmp_path / protocol, protocol) as lab:
        event = lab.runtime.execute(lab.gateway.authorize(ProposedAction(
            url=lab.allowed_url, body=json.dumps({"data": lab.registry.items[0].value}))))
        with httpx.Client(proxy=lab.proxy, trust_env=False, verify=lab.tls_context or True) as client:
            client.post(lab.allowed_url, content=b'{}', headers={"Content-Type": "application/json"})
        lab.wait_for_health(event.decision_monotonic + 1.5)
        bb, hh = lab.snapshot()
        assert check(lab, event).evidence_status == "UNVERIFIED"
        missing_record = check(lab, event, view=[])
        assert "MISSING_OR_DUPLICATE_REQUEST_EVIDENCE" in missing_record.diagnostics
        missing_both = check(lab, event, view=[], health_view=[h for h in hh if h.kind != "REQUEST"])
        assert "HEALTH_SEQUENCE_GAP_OR_DUPLICATE" in missing_both.diagnostics
        assert len(lab.snapshot()[0]) == len(bb)  # original B is unchanged by reader-view faults


def test_partial_http_ingress_cannot_support_block_absence(tmp_path):
    with Lab(tmp_path / "http") as lab:
        event = lab.runtime.execute(lab.gateway.authorize(ProposedAction(
            url=lab.allowed_url, body=json.dumps({"data": lab.registry.items[0].value}))))
        with socket.create_connection(("127.0.0.1", int(lab.proxy.rsplit(":", 1)[1]))) as client:
            request = (f"POST {lab.allowed_url} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                       "Content-Type: application/json\r\nContent-Length: 100\r\n\r\n{")
            client.sendall(request.encode())
            time.sleep(1.8)
            result = check(lab, event)
            assert "UNRESOLVED_INGRESS_AT_WINDOW_BOUNDARY" in result.diagnostics
            assert result.evidence_status == "UNVERIFIED"


def test_https_client_rejects_untrusted_proxy_certificate(tmp_path):
    with Lab(tmp_path / "https", "https") as lab:
        assert lab.tls_context.verify_mode == ssl.CERT_REQUIRED and lab.tls_context.check_hostname
        with httpx.Client(proxy=lab.proxy, trust_env=False, verify=True) as client:
            with pytest.raises(httpx.HTTPError):
                client.post(lab.allowed_url, json={"harmless": True})
        assert not lab.receivers[0].requests
        assert lab.snapshot()[0] == []


def test_https_proxy_rejects_untrusted_receiver_certificate(tmp_path):
    with Lab(tmp_path / "https", "https", trust_upstream=False) as lab:
        trial = run_fault_scenario(lab, "allow", window=1.5)
        assert trial.event.response_status == 502
        assert not lab.receivers[0].requests
        # The request still crossed the proxy's request hook: boundary proof != receiver delivery.
        assert trial.verification.result == "MATCH"
        assert len(lab.snapshot()[0]) == 1


def test_direct_local_receiver_access_is_detected_as_unenforced_egress(tmp_path):
    with Lab(tmp_path / "http") as lab:
        with httpx.Client(trust_env=False) as client:
            assert client.post(lab.allowed_url, json={"isolation_probe": True}).status_code == 200
        assert len(lab.receivers[0].requests) == 1
        assert lab.snapshot()[0] == []  # out-of-scope isolation probe, not fabricated network evidence


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_actual_monitor_write_failure_is_sticky_and_does_not_forward(tmp_path, protocol):
    instance = Lab(tmp_path / protocol, protocol)
    instance.fail_request_write_once = True  # explicit test-only collector I/O fault
    with instance as lab:
        failed = run_fault_scenario(lab, "allow", window=1.5)
        assert failed.event.claim.value == "EXECUTED_SUCCESS" and failed.event.response_status == 503
        assert failed.verification.evidence_status == "UNVERIFIED"
        assert not lab.snapshot()[0] and not lab.receivers[0].requests
        assert any(h.kind == "FAILURE" and h.reason == "REQUEST_COLLECTION_FAILED"
                   for h in lab.snapshot()[1])
        blocked = run_fault_scenario(lab, "block", window=1.5)
        assert blocked.verification.result != "MATCH"
        assert "MONITOR_COLLECTION_FAILED_OR_STOPPED" in blocked.verification.diagnostics


@pytest.mark.parametrize("protocol", ["http", "https"])
def test_monitor_restart_does_not_bridge_interrupted_window(tmp_path, protocol):
    with Lab(tmp_path / protocol, protocol) as lab:
        event = lab.runtime.execute(lab.gateway.authorize(ProposedAction(
            url=lab.allowed_url, body=json.dumps({"data": lab.registry.items[0].value}))))
        time.sleep(0.3)
        lab.process.terminate()
        lab.process.wait(timeout=5)
        lab.restart_monitor()
        lab.wait_for_health(event.decision_monotonic + 1.5)
        assert len({h.run_id for h in lab.snapshot()[1]}) == 2
        assert check(lab, event).evidence_status == "UNVERIFIED"
        # A later complete fresh-run window can qualify without hiding the interrupted one.
        assert run_fault_scenario(lab, "block", window=1.5).verification.result == "MATCH"
