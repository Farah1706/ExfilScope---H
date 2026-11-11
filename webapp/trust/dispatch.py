"""Opt-in protected dispatch for a single residency notice task."""

import json

import rfc8785

from exfilscope.contracts import ProposedAction, RuntimeEvent

from .capability import Rejected, Scope, Validator


class ProtectedDispatch:
    """Bind one task to a server-owned receiver and dispatch the validated snapshot."""

    def __init__(self, lab, validator: Validator, scope: Scope, body_check=None):
        self._gateway = lab.gateway
        self._runtime = lab.runtime
        self._target = lab.allowed_url
        self._validator = validator
        self._scope = scope
        self._body_check = body_check  # optional official-data mandate; raises Rejected

    def execute(self, capability: str, proof: str, action: dict) -> tuple[dict, RuntimeEvent]:
        try:
            submitted = json.loads(rfc8785.dumps(action))
        except (ValueError, TypeError) as exc:
            raise Rejected("ACTION_MALFORMED") from exc
        if (not isinstance(submitted, dict)
                or submitted.keys() != {"task", "tool", "endpoint_id", "method", "route_id", "body"}
                or not isinstance(submitted["body"], dict)):
            raise Rejected("ACTION_MALFORMED")
        if submitted["task"] != self._scope.task:
            raise Rejected("OUT_OF_SCOPE_TASK")
        grant = self._validator.check(capability, proof, submitted)
        if grant["task"] != self._scope.task:
            raise Rejected("OUT_OF_SCOPE_TASK")
        if any(submitted[field] != getattr(self._scope, field)
               for field in ("tool", "endpoint_id", "method", "route_id")):
            raise Rejected("DISPATCH_SCOPE_MISMATCH")
        if self._body_check is not None:
            self._body_check(submitted["body"])
        proposed = ProposedAction(url=self._target, method=submitted["method"],
                                  body=rfc8785.dumps(submitted["body"]).decode("utf-8"))
        authorization = self._gateway.authorize(proposed)
        permitted = authorization.permitted_action
        if self._body_check is not None and permitted is not None and permitted.body != proposed.body:
            raise RuntimeError("GROUNDING_PAYLOAD_CHANGED")
        return grant, self._runtime.execute(authorization)