"""Deterministic authorization occurs and is durably logged before network execution."""

import time
from urllib.parse import unquote
from uuid import uuid4

from pydantic import ValidationError

from .canonical import InvalidJSON, canonical_bytes, commitment, parse_body
from .config import Catalog
from .contracts import (Authorization, Decision, Metadata, PermittedAction, ProposedAction,
                        RuntimeEvent)
from .ledger import RuntimeWriter
from .registry import Registry
from .policy import GatewayPolicy
from .clock import ClockContext


class Gateway:
    def __init__(self, registry: Registry, catalog: Catalog, approved: set[str], key: bytes,
                 key_id: str, writer: RuntimeWriter, *, policy: GatewayPolicy,
                 clock: ClockContext | None = None):
        if len(key) != 32 or not approved or not approved <= set(catalog.endpoints.values()):
            raise ValueError("INVALID_GATEWAY_CONFIG")
        for label in (*catalog.endpoints.values(), *catalog.routes.values(), key_id):
            if registry.contains(label):
                raise ValueError("UNSAFE_CONFIG_LABEL")
        self.registry, self.catalog, self.approved = registry, catalog, approved
        self.key, self.key_id, self.writer = key, key_id, writer
        if not isinstance(policy, GatewayPolicy):
            raise ValueError("EXPLICIT_GATEWAY_POLICY_REQUIRED")
        self.policy = policy
        self.clock = clock or ClockContext.local()
        for rule in self.policy.rules:
            if rule.endpoint_id not in approved or rule.route_id not in catalog.routes.values() \
                    or rule.method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValueError("INVALID_POLICY_CONTEXT")
        if registry.contains(self.policy.model_dump_json()) or registry.contains(
            self.clock.model_dump_json()
        ):
            raise ValueError("UNSAFE_POLICY_OR_CLOCK_LABEL")

    def authorize(self, action: ProposedAction) -> Authorization:
        proposed, anomalies = self.catalog.metadata(action.url, action.method)
        decision, reason = Decision.BLOCK, "INVALID_REQUEST"
        permitted = None
        digest = None
        hits = ()
        rule = self.policy.rule_for(proposed)
        metadata_secret = self.registry.contains(unquote(action.url)) or any(
            self.registry.contains(unquote(k + v)) for k, v in action.headers.items())
        if metadata_secret:
            reason = "PROTECTED_METADATA"
        elif anomalies:
            reason = "UNSUPPORTED_METADATA"
        elif proposed.endpoint_id not in self.approved:
            reason = "FORBIDDEN_DESTINATION"
        elif rule is None:
            reason = "UNAPPROVED_METHOD_ROUTE"
        elif action.tool != "http_json" or any(
            k.lower() != "content-type" or v.lower() != "application/json"
            for k, v in action.headers.items()
        ) or len({k.lower() for k in action.headers}) != len(action.headers):
            reason = "UNSUPPORTED_TOOL_OR_HEADERS"
        else:
            try:
                value = parse_body(action.body)
                hits = self.registry.scan(value)
                if any(h.location.endswith("/key") for h in hits):
                    reason = "PROTECTED_JSON_KEY"
                elif not rule.accepts(value):
                    reason = "UNAPPROVED_JSON_FIELD"
                elif hits and not rule.permits_protected(value, self.registry):
                    reason = "PROTECTED_DISCLOSURE"
                else:
                    decision = Decision.REDACT if hits else Decision.ALLOW
                    reason = "REDACTED_PROTECTED_VALUES" if hits else "APPROVED_HARMLESS_JSON"
                    safe_value = self.registry.redact(value) if hits else value
                    if self.registry.scan(safe_value) or not rule.accepts(safe_value):
                        raise InvalidJSON("UNSAFE_TRANSFORMED_BODY")
                    safe_bytes = canonical_bytes(safe_value)
                    digest = commitment(safe_value, self.key)
                    permitted = PermittedAction(url=action.url, method=action.method,
                                                body=safe_bytes.decode("utf-8"),
                                                endpoint_id=proposed.endpoint_id,
                                                route_id=proposed.route_id)
            except InvalidJSON:
                decision, reason = Decision.BLOCK, "INVALID_JSON"
                permitted, digest = None, None
        event = RuntimeEvent(session_id=action.session_id, proposed=proposed, hits=hits,
                             decision=decision, reason=reason,
                             permitted=proposed if permitted else None, payload_hmac=digest,
                             policy_version=self.policy.version,
                             key_id=self.key_id, decision_time=time.time(),
                             decision_monotonic=time.monotonic(), host_id=self.clock.host_id,
                             clock_domain_id=self.clock.clock_domain_id)
        # A write failure raises; the caller receives no authorization to emit.
        self.writer.insert(event)
        return Authorization(event=event, permitted_action=permitted)

    def reject_invalid_schema(self) -> RuntimeEvent:
        """Record malformed tool input without copying attacker-controlled fields."""
        event = RuntimeEvent(session_id=uuid4(),
                             proposed=Metadata(endpoint_id="INVALID", route_id="INVALID",
                                               method="UNSUPPORTED"),
                             decision=Decision.BLOCK, reason="INVALID_SCHEMA",
                             policy_version=self.policy.version,
                             key_id=self.key_id, decision_time=time.time(),
                             decision_monotonic=time.monotonic(), host_id=self.clock.host_id,
                             clock_domain_id=self.clock.clock_domain_id)
        self.writer.insert(event)
        return event

    def authorize_input(self, data: dict) -> Authorization:
        try:
            action = ProposedAction.model_validate(data)
        except ValidationError:
            return Authorization(event=self.reject_invalid_schema())
        return self.authorize(action)
