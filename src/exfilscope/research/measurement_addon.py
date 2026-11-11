"""Lab-only timing monitor. Never loaded by production deployment.

The B arm omits policy/body commitments and Ledger B event writes. Both arms
retain identical transport and health journaling. Baseline transport receipts
are measurement controls, not ordinary ExfilScope network evidence.
"""

import json
import os
from pathlib import Path
import time
from uuid import UUID

from exfilscope.config import TRACE_HEADER
from exfilscope.contracts import ObservedEvent
from exfilscope.ledger import MonitorWriter
from exfilscope.monitor import Monitor, from_env

ARM_HEADER = "X-ExfilScope-Measurement"


class MeasurementWriter(MonitorWriter):
    def __init__(self, path, journal):
        super().__init__(path)
        self.journal = journal
        self.arm = "E"
        self.connection = None

    def log(self, row):
        with self.journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def append_health(self, record):
        super().append_health(record)
        self.log({"kind": "health", "run_id": str(record.run_id), "sequence": record.sequence,
                  "prepared": record.monotonic_time, "committed": time.monotonic(),
                  "host_id": record.host_id, "clock_domain_id": record.clock_domain_id})

    def record_observation(self, event, record):
        start = time.monotonic()
        if self.arm == "B":
            # Same durable health receipt; baseline has no B event processing/write.
            super().append_health(record)
        else:
            super().record_observation(event, record)
        committed = time.monotonic()
        transport = event.model_dump(mode="json")
        transport["payload_hmac"] = None
        self.log({"kind": "request", "arm": self.arm, "connection": self.connection,
                  "transport": transport, "observed": event.request_monotonic,
                  "commit_started": start, "committed": committed,
                  "run_id": str(record.run_id), "sequence": record.sequence})


class MeasurementMonitor(Monitor):
    name = "monitor"  # Preserve the production monitor's identity/configuration check.

    def _observe_request(self, flow, observed_wall, observed_mono):
        arm = flow.request.headers.pop(ARM_HEADER, "E")
        if arm not in ("E", "B"):
            raise ValueError("INVALID_LAB_MEASUREMENT_ARM")
        self.writer.arm = arm
        self.writer.connection = str(flow.client_conn.id)
        if arm == "E":
            return super()._observe_request(flow, observed_wall, observed_mono)
        traces = flow.request.headers.get_all(TRACE_HEADER)
        del flow.request.headers[TRACE_HEADER]
        if len(traces) != 1:
            raise ValueError("INVALID_BASELINE_TRACE")
        metadata, anomalies = self.catalog.metadata(flow.request.url, flow.request.method)
        event = ObservedEvent(trace_id=UUID(traces[0]), observed=metadata, payload_hmac=None,
                              key_id=self.key_id, request_time=observed_wall,
                              request_monotonic=observed_mono,
                              request_size=len(flow.request.raw_content or b""),
                              anomalies=tuple(anomalies), host_id=self.clock.host_id,
                              clock_domain_id=self.clock.clock_domain_id)
        self.pending.discard(flow.id)
        self.clients[flow.client_conn.id] += 1
        self._record("REQUEST", event=event)
        flow.metadata["exfilscope_event"] = event
        flow.metadata["measurement_baseline"] = True

    def response(self, flow):
        if not flow.metadata.get("measurement_baseline"):
            super().response(flow)
        event = flow.metadata.get("exfilscope_event")
        if event and flow.response:
            # Lazy upstream establishment happens after the request hook. Observe
            # the actual server connection on response, identically in both arms.
            self.writer.log({"kind": "connection", "trace_id": str(event.trace_id),
                             "upstream": [str(flow.server_conn.id),
                                          flow.server_conn.timestamp_start]})


base = from_env()
addons = [MeasurementMonitor(base.catalog, base.key, base.key_id,
          MeasurementWriter(base.writer.path, Path(os.environ["EXFILSCOPE_MEASUREMENT_JOURNAL"])),
          proxy_identity=base.proxy_identity, clock=base.clock,
          fail_request_write_once=base.fail_request_write_once,
          delay_request_write_once=base.delay_request_write_once)]
