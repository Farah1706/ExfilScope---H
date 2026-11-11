"""Isolated hook tests use fake flows; these never count as network observations."""

import sqlite3
from uuid import uuid4

import pytest
from mitmproxy import connection, http

from exfilscope.config import TRACE_HEADER
from exfilscope.contracts import ObservedEvent
from exfilscope.ledger import MonitorWriter, read_events, read_monitor_snapshot
from exfilscope.monitor import Monitor, authority_matches


def flow(gateway):
    item = http.HTTPFlow(connection.Client(peername=("127.0.0.1", 1234),
                                           sockname=("127.0.0.1", 8080)),
                         connection.Server(address=("127.0.0.1", 8801)))
    item.request = http.Request.make("POST", "http://127.0.0.1:8801/collect", b'{}',
                                     {"Content-Type": "application/json",
                                      TRACE_HEADER: str(uuid4())})
    return item


@pytest.mark.parametrize("header,expected", [
    (None, True), ("127.0.0.1:8801", True), ("127.0.0.1:8802", False),
    ("other.example:8801", False), ("127.0.0.1", False), ("user@127.0.0.1:8801", False),
    ("127.0.0.1:notaport", False),
])
def test_authority_matches_only_the_forwarding_target(header, expected):
    assert authority_matches(header, "http", "127.0.0.1", 8801) is expected


def test_default_port_authority_is_normalized():
    assert authority_matches("127.0.0.1", "https", "127.0.0.1", 443)
    assert not authority_matches("127.0.0.1", "https", "127.0.0.1", 8443)


def test_spoofed_host_header_does_not_change_observed_endpoint(gateway, tmp_path):
    writer = MonitorWriter(tmp_path / "b" / "network.sqlite")
    monitor = Monitor(gateway.catalog, gateway.key, gateway.key_id, writer)
    item = flow(gateway)
    item.request.url = "http://127.0.0.1:8802/collect"
    item.request.headers["Host"] = "127.0.0.1:8801"
    assert item.request.pretty_url.startswith("http://127.0.0.1:8801")
    monitor.request(item)
    event = read_events(writer.path, ObservedEvent, "B")[0]
    assert event.observed.endpoint_id == "UNAUTHORIZED"
    assert "HOST_HEADER_MISMATCH" in event.anomalies


def test_hook_write_failure_prevents_normal_forwarding(gateway, tmp_path, monkeypatch):
    writer = MonitorWriter(tmp_path / "b" / "network.sqlite")
    monitor = Monitor(gateway.catalog, gateway.key, gateway.key_id, writer)
    item = flow(gateway)
    def fail(*_):
        raise sqlite3.OperationalError("controlled disk failure")
    monkeypatch.setattr(writer, "record_observation", fail)
    monitor.request(item)
    assert item.response.status_code == 503
    assert TRACE_HEADER not in item.request.headers
    assert read_events(writer.path, ObservedEvent, "B") == []
    assert monitor.failed
    assert read_monitor_snapshot(writer.path)[1][-1].kind == "FAILURE"


def test_response_update_failure_retains_request_evidence(gateway, tmp_path, monkeypatch):
    writer = MonitorWriter(tmp_path / "b" / "network.sqlite")
    monitor = Monitor(gateway.catalog, gateway.key, gateway.key_id, writer)
    item = flow(gateway)
    monitor.request(item)
    def fail(_):
        raise sqlite3.OperationalError("controlled disk failure")
    monkeypatch.setattr(writer, "update", fail)
    item.response = http.Response.make(200, b'{}')
    monitor.response(item)
    events = read_events(writer.path, ObservedEvent, "B")
    assert len(events) == 1 and events[0].payload_hmac
    assert events[0].response_status is None
    assert read_monitor_snapshot(writer.path)[1][-1].state == "FAILED"
