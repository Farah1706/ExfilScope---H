"""Network wrapper: fixed proxy, no redirects, no retries, no raw error logging."""

import ssl
import time
from contextlib import nullcontext

import httpx

from .config import TRACE_HEADER
from .contracts import Authorization, Claim, RuntimeEvent
from .ledger import RuntimeWriter


class Runtime:
    def __init__(self, writer: RuntimeWriter, proxy: str, tls_context: ssl.SSLContext | None = None,
                 timeout: float = 2.0, *, persistent: bool = False):
        if not proxy.startswith("http://"):
            raise ValueError("HTTP_PROXY_REQUIRED")
        if tls_context and (tls_context.verify_mode != ssl.CERT_REQUIRED
                            or not tls_context.check_hostname):
            raise ValueError("TLS_CERTIFICATE_AND_HOSTNAME_VERIFICATION_REQUIRED")
        self.writer, self.proxy, self.tls_context = writer, proxy, tls_context
        self.timeout = timeout
        self.client = self.new_client() if persistent else None

    def new_client(self) -> httpx.Client:
        return httpx.Client(proxy=self.proxy, trust_env=False, follow_redirects=False,
                            verify=self.tls_context or True, timeout=self.timeout)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()

    def execute(self, authorization: Authorization) -> RuntimeEvent:
        event, permitted = authorization.event, authorization.permitted_action
        if permitted is None:
            event = event.model_copy(update={"completion_time": time.time(),
                                             "completion_monotonic": time.monotonic()})
            self.writer.update(event)
            return event
        try:
            with nullcontext(self.client) if self.client is not None else self.new_client() as client:
                response = client.request(permitted.method, permitted.url,
                                          content=permitted.body.encode("utf-8"),
                                          headers={"Content-Type": "application/json",
                                                   TRACE_HEADER: str(event.trace_id)})
            event = event.model_copy(update={"claim": Claim.EXECUTED_SUCCESS,
                                             "response_status": response.status_code})
        except httpx.HTTPError:
            event = event.model_copy(update={"claim": Claim.EXECUTED_FAILED,
                                             "error_category": "TRANSPORT_ERROR"})
        except (OSError, ValueError):
            event = event.model_copy(update={"claim": Claim.EXECUTED_FAILED,
                                             "error_category": "CLIENT_ERROR"})
        event = event.model_copy(update={"completion_time": time.time(),
                                         "completion_monotonic": time.monotonic()})
        # Update failures propagate: investigators retain a NOT_EXECUTED claim and
        # will diagnose its inconsistency if a request was independently observed.
        self.writer.update(event)
        return event
