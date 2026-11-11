"""Independent mitmproxy addon; it writes only Ledger B and its collection-health journal."""

import os
import asyncio
import logging
import time
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit

from mitmproxy import ctx, http

from .canonical import InvalidJSON, commitment, parse_body
from .config import TRACE_HEADER, Catalog, load_key
from .contracts import ObservedEvent
from .ledger import MonitorWriter
from .health import HealthSequence, boundary_fingerprint
from .clock import ClockContext


def authority_matches(header: str | None, scheme: str, host: str, port: int) -> bool:
    """True when the Host/:authority value names the forwarding target (absent is allowed)."""
    if header is None:
        return True
    try:
        parts = urlsplit("//" + header)
        header_port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        return False
    return (not parts.username and not parts.password and not parts.path
            and (parts.hostname or "").lower() == host.lower() and header_port == port)


class Monitor:
    def __init__(self, catalog: Catalog, key: bytes, key_id: str, writer: MonitorWriter, *,
                 proxy_identity: str | None = None, fail_request_write_once: bool = False,
                 delay_request_write_once: float = 0.0, clock: ClockContext | None = None):
        self.catalog, self.key, self.key_id, self.writer = catalog, key, key_id, writer
        self.proxy_identity = proxy_identity
        self.clock = clock or ClockContext.local()
        self.health = HealthSequence(boundary_fingerprint(catalog, proxy_identity), key_id, self.clock)
        self.failed = False
        self.fail_request_write_once = fail_request_write_once
        self.delay_request_write_once = delay_request_write_once
        self.clients = {}
        self.pending = set()
        self.pulse_task = None

    def _record(self, kind: str, reason: str | None = None,
                event: ObservedEvent | None = None) -> None:
        record = self.health.prepare(wall=time.time(), mono=time.monotonic(), kind=kind,
                                     state="STOPPED" if kind == "STOP" else
                                     "FAILED" if self.failed else "HEALTHY",
                                     open_clients=len(self.clients), pending_requests=len(self.pending),
                                     reason=reason, event=event,
                                     acknowledge=kind == "PULSE" and not self.failed
                                     and not self.clients and not self.pending)
        if event:
            if self.fail_request_write_once:
                self.fail_request_write_once = False
                raise OSError("TEST_ONLY_REQUEST_LEDGER_WRITE_FAILURE")
            if self.delay_request_write_once:
                # Test-only: the observation is already timestamped; only its commit is late.
                delay, self.delay_request_write_once = self.delay_request_write_once, 0.0
                time.sleep(delay)
            self.writer.record_observation(event, record)
        else:
            self.writer.append_health(record)
        self.health.committed(record)

    def _safe_record(self, kind: str, reason: str | None = None) -> None:
        try:
            self._ensure_started()
            self._record(kind, reason)
        except Exception:
            self.failed = True
            logging.error('{"event":"COLLECTION_WRITE_FAILURE"}')

    def _failure(self, reason: str) -> None:
        self.failed = True  # sticky until a fresh monitor run, including transient write failures
        self._safe_record("FAILURE", reason)

    def _ensure_started(self) -> None:
        if self.health.sequence == 0:
            self._record("START")

    def _configuration_ok(self) -> bool:
        proxy = ctx.master.addons.get("proxyserver")
        listeners = list(proxy.servers) if proxy else []
        identity = urlsplit(self.proxy_identity or "")
        port = identity.port or 80
        return (ctx.options.stream_large_bodies is None and not ctx.options.ssl_insecure
                and ctx.options.connection_strategy == "lazy"
                and ctx.master.addons.get("monitor") is self and len(listeners) == 1
                and listeners[0].mode.type_name == "regular" and listeners[0].is_running
                and any(address[1] == port for address in listeners[0].listen_addrs)
                and not proxy.servers.is_updating and identity.scheme == "http"
                and bool(identity.hostname) and not identity.username and not identity.password
                and not identity.path and not identity.query and not identity.fragment)

    def running(self) -> None:
        if not self._configuration_ok():
            self.failed = True
        self._ensure_started()
        self.pulse_task = asyncio.create_task(self._pulse())
        if os.environ.get("EXFILSCOPE_LAB_TEST_CONTROLS") == "1" \
                and os.environ.get("EXFILSCOPE_TEST_PERMISSION_PROBE_A"):
            from .isolation import probe_write_access
            import json

            result = probe_write_access(Path(os.environ["EXFILSCOPE_TEST_PERMISSION_PROBE_A"]))
            (self.writer.path.parent / "monitor-permission-probe.json").write_text(
                json.dumps({"monitor_write_A": result}) + "\n")

    async def _pulse(self) -> None:
        while True:
            try:
                if not self._configuration_ok():
                    self.failed = True
            except Exception:
                self.failed = True
            self._safe_record("PULSE")
            await asyncio.sleep(0.1)

    def done(self) -> None:
        if self.pulse_task:
            self.pulse_task.cancel()
        self._safe_record("STOP")

    def client_connected(self, client) -> None:
        self.clients[client.id] = 0
        self._safe_record("CLIENT_OPEN")

    def client_disconnected(self, client) -> None:
        seen = self.clients.pop(client.id, None)
        if seen == 0:
            self._safe_record("INCIDENT", "CLIENT_CLOSED_WITHOUT_REQUEST_EVIDENCE")
        self._safe_record("CLIENT_CLOSE")

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        flow.request.stream = False
        self.pending.add(flow.id)
        self._safe_record("HEADERS")

    def error(self, flow: http.HTTPFlow) -> None:
        self.pending.discard(flow.id)
        if "exfilscope_event" not in flow.metadata:
            self._safe_record("INCIDENT", "HTTP_FLOW_WITHOUT_REQUEST_EVIDENCE")

    def tls_failed_client(self, data) -> None:
        self._safe_record("INCIDENT", "CLIENT_TLS_HANDSHAKE_FAILED")

    def request(self, flow: http.HTTPFlow) -> None:
        observed_wall, observed_mono = time.time(), time.monotonic()
        try:
            self._ensure_started()
            if self.pulse_task is not None and not self._configuration_ok():
                self.failed = True
            self._observe_request(flow, observed_wall, observed_mono)
        except Exception:
            if TRACE_HEADER in flow.request.headers:
                del flow.request.headers[TRACE_HEADER]
            self._failure("REQUEST_COLLECTION_FAILED")
            flow.response = http.Response.make(503, b"observation unavailable")

    def _observe_request(self, flow: http.HTTPFlow, observed_wall: float,
                         observed_mono: float) -> None:
        # The full body is present here; request streaming is disabled by launch config.
        values = flow.request.headers.get_all(TRACE_HEADER)
        if TRACE_HEADER in flow.request.headers:
            del flow.request.headers[TRACE_HEADER]
        trace = None
        anomalies = []
        if len(values) != 1:
            anomalies.append("MISSING_OR_DUPLICATE_TRACE")
        else:
            try:
                trace = UUID(values[0])
            except ValueError:
                anomalies.append("INVALID_TRACE")
        # Identify the endpoint mitmproxy forwards to (request.url). pretty_url prefers the
        # client-supplied Host header, which can name a different endpoint than the target.
        metadata, metadata_anomalies = self.catalog.metadata(flow.request.url,
                                                            flow.request.method)
        anomalies.extend(metadata_anomalies)
        if not authority_matches(flow.request.host_header, flow.request.scheme,
                                 flow.request.host, flow.request.port):
            anomalies.append("HOST_HEADER_MISMATCH")
        digest = None
        raw = flow.request.raw_content or b""
        try:
            if (flow.request.headers.get("content-type", "").lower() != "application/json"
                    or "content-encoding" in flow.request.headers):
                raise InvalidJSON("UNSUPPORTED_CONTENT")
            digest = commitment(parse_body(raw), self.key)
        except InvalidJSON:
            anomalies.append("UNSUPPORTED_BODY")
        event = ObservedEvent(trace_id=trace, observed=metadata, payload_hmac=digest,
                              key_id=self.key_id, request_time=observed_wall, request_size=len(raw),
                              anomalies=tuple(anomalies), request_monotonic=observed_mono,
                              host_id=self.clock.host_id,
                              clock_domain_id=self.clock.clock_domain_id)
        self.pending.discard(flow.id)
        if flow.client_conn.id in self.clients:
            self.clients[flow.client_conn.id] += 1
        # Request evidence and its completeness receipt share one transaction.
        self._record("REQUEST", event=event)
        flow.metadata["exfilscope_event"] = event
        if self.failed:
            flow.response = http.Response.make(503, b"collector unavailable")

    def response(self, flow: http.HTTPFlow) -> None:
        event = flow.metadata.get("exfilscope_event")
        if event and flow.response:
            try:
                self.writer.update(event.model_copy(update={
                    "response_status": flow.response.status_code}))
            except Exception:
                self._failure("RESPONSE_STATUS_WRITE_FAILED")


def from_env() -> Monitor:
    controls = os.environ.get("EXFILSCOPE_LAB_TEST_CONTROLS") == "1"
    return Monitor(Catalog.from_env(), load_key(Path(os.environ["EXFILSCOPE_KEY_FILE"])),
                   os.environ.get("EXFILSCOPE_KEY_ID", "lab-key-1"),
                   MonitorWriter(Path(os.environ["EXFILSCOPE_LEDGER_B"])),
                   proxy_identity=os.environ.get("EXFILSCOPE_PROXY_IDENTITY"),
                   fail_request_write_once=controls
                   and os.environ.get("EXFILSCOPE_TEST_REQUEST_WRITE_FAILURE") == "1",
                   delay_request_write_once=float(os.environ.get("EXFILSCOPE_TEST_REQUEST_WRITE_DELAY", 0))
                   if controls else 0.0)
