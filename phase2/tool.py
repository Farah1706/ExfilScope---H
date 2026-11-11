"""The only outbound task-action capability: one call to a trusted local API."""

import json
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .contracts import parse_proposal


def local_url(value: str, path: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or parts.hostname != "127.0.0.1"
            or parts.username or parts.password or parts.query or parts.fragment
            or parts.path != path or not parts.port):
        raise ValueError("TRUSTED_LOOPBACK_URL_REQUIRED")
    return value


class GatewayTool:
    def __init__(self, gateway_url: str, target_url: str, session_id: str):
        self.gateway_url = local_url(gateway_url, "/execute")
        self.target_url = local_url(target_url, "/collect")
        self.session_id = str(UUID(session_id))
        self.attempts = 0

    def submit(self, proposal: dict) -> dict:
        if self.attempts:
            raise RuntimeError("ACTION_LIMIT_REACHED")
        parse_proposal(json.dumps(proposal, allow_nan=False))
        # Charge before I/O: ambiguous failures must never trigger automatic replay.
        self.attempts += 1
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=15) as client:
            response = client.post(self.gateway_url, json={
                "schema_version": "1.0", "session_id": self.session_id,
                "tool": "http_json", "url": self.target_url, "method": proposal["method"],
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(proposal["body"], ensure_ascii=False, allow_nan=False),
            })
        response.raise_for_status()
        result = response.json()
        if result.get("session_id") != self.session_id or result.get("schema_version") != "1.1":
            raise ValueError("INVALID_GATEWAY_RESPONSE")
        return {"event_id": result["event_id"], "decision": result["decision"]}
