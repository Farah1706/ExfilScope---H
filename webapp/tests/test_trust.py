"""Government Trust extension: signed, task-scoped, short-lived capabilities."""

import pytest

from webapp.trust.capability import (AgentIdentity, Issuer, Rejected, Scope, Validator, b64,
                                     unb64)

SCOPE = Scope(task="notice", tool="http_post", endpoint_id="AUTHORIZED", method="POST",
              route_id="COLLECT")
ACTION = {"tool": "http_post", "endpoint_id": "AUTHORIZED", "method": "POST",
          "route_id": "COLLECT", "body": {"text": "status"}}


@pytest.fixture
def setup():
    issuer = Issuer()
    validator = Validator(issuer.public_key)
    agent = AgentIdentity("agent-1")
    validator.register(agent.agent_id, agent.public_key)
    return issuer, validator, agent


def code(validator, capability, proof, action=ACTION):
    with pytest.raises(Rejected) as caught:
        validator.check(capability, proof, action)
    return caught.value.code


def test_valid_capability_is_accepted_once(setup):
    issuer, validator, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    grant = validator.check(capability, agent.prove(capability, ACTION), ACTION)
    assert grant["agent_id"] == "agent-1" and grant["task"] == "notice"
    assert code(validator, capability, agent.prove(capability, ACTION)) == "CAPABILITY_REPLAYED"


def test_expired_capability_is_rejected(setup):
    issuer, validator, agent = setup
    old = Issuer(clock=lambda: 1_000_000)
    old._key = issuer._key  # same trusted key, issued long ago
    capability = old.issue(agent.agent_id, agent.public_key, SCOPE, lifetime=60)
    assert code(validator, capability, agent.prove(capability, ACTION)) == "CAPABILITY_EXPIRED"


def test_lifetime_is_bounded(setup):
    issuer, _, agent = setup
    with pytest.raises(ValueError):
        issuer.issue(agent.agent_id, agent.public_key, SCOPE, lifetime=3600)


def test_untrusted_issuer_and_tampering_are_rejected(setup):
    issuer, validator, agent = setup
    forged = Issuer().issue(agent.agent_id, agent.public_key, SCOPE)
    assert code(validator, forged, agent.prove(forged, ACTION)) == "ISSUER_SIGNATURE_INVALID"
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    payload, signature = capability.split(".")
    widened = unb64(payload).replace(b'"COLLECT"', b'"ALTERNATE"')
    tampered = b64(widened) + "." + signature
    assert code(validator, tampered, agent.prove(capability, ACTION)) == "ISSUER_SIGNATURE_INVALID"
    assert code(validator, "not-a-token", "x.y") == "ISSUER_SIGNATURE_INVALID"


def test_identity_requires_the_registered_key(setup):
    issuer, validator, agent = setup
    impostor = AgentIdentity("agent-1")
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    assert code(validator, capability, impostor.prove(capability, ACTION)) == "PROOF_OF_POSSESSION_INVALID"
    # A capability bound to the impostor's key does not match the registered identity.
    rebound = issuer.issue(agent.agent_id, impostor.public_key, SCOPE)
    assert code(validator, rebound, impostor.prove(rebound, ACTION)) == "IDENTITY_KEY_MISMATCH"
    unknown = AgentIdentity("agent-unknown")
    other = issuer.issue(unknown.agent_id, unknown.public_key, SCOPE)
    assert code(validator, other, unknown.prove(other, ACTION)) == "AGENT_NOT_REGISTERED"


def test_scope_and_binding_are_enforced(setup):
    issuer, validator, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    outside = {**ACTION, "endpoint_id": "UNAUTHORIZED"}
    assert code(validator, capability, agent.prove(capability, outside), outside) == "OUT_OF_SCOPE_ENDPOINT_ID"
    other_method = {**ACTION, "method": "DELETE"}
    assert code(validator, capability, agent.prove(capability, other_method), other_method) == "OUT_OF_SCOPE_METHOD"
    # A proof made for one action cannot be reused for another.
    changed = {**ACTION, "body": {"text": "other"}}
    assert code(validator, capability, agent.prove(capability, ACTION), changed) == "PROOF_NOT_BOUND_TO_ACTION"


def test_revoked_agent_is_rejected(setup):
    issuer, validator, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    validator.revoke(agent.agent_id)
    assert code(validator, capability, agent.prove(capability, ACTION)) == "AGENT_REVOKED"


def test_stale_proof_is_rejected(setup):
    issuer, validator, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    proof = agent.prove(capability, ACTION, clock=lambda: 0)
    assert code(validator, capability, proof) == "PROOF_STALE"


def test_issuer_key_is_never_serialised(setup):
    issuer, _, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    assert "private" not in capability.lower() and len(capability.split(".")) == 2


def test_boolean_proof_cannot_authorize_numeric_body(setup):
    issuer, validator, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    signed = {**ACTION, "body": {"flag": True}}
    submitted = {**ACTION, "body": {"flag": 1}}
    assert code(validator, capability, agent.prove(capability, signed),
                submitted) == "PROOF_NOT_BOUND_TO_ACTION"


def test_concurrent_replay_accepts_once(setup):
    from concurrent.futures import ThreadPoolExecutor

    issuer, validator, agent = setup
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    proof = agent.prove(capability, ACTION)

    def attempt(_):
        try:
            validator.check(capability, proof, ACTION)
        except Rejected as exc:
            return exc.code
        return "ACCEPTED"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert results.count("ACCEPTED") == 1
    assert results.count("CAPABILITY_REPLAYED") == 15


def test_dispatch_uses_signed_body_and_rejects_before_gateway(setup):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock

    from webapp.trust.dispatch import ProtectedDispatch

    issuer, validator, agent = setup
    gateway = Mock()
    runtime = Mock()
    target = "https://127.0.0.1:8443/collect"
    dispatch = ProtectedDispatch(SimpleNamespace(gateway=gateway, runtime=runtime,
                                                  allowed_url=target), validator, SCOPE)
    action = {**ACTION, "task": SCOPE.task}
    capability = issuer.issue(agent.agent_id, agent.public_key, SCOPE)
    proof = agent.prove(capability, action)
    with pytest.raises(Rejected, match="PROOF_NOT_BOUND_TO_ACTION"):
        dispatch.execute(capability, proof, {**action, "body": {"text": "changed"}})
    gateway.authorize.assert_not_called()
    runtime.execute.assert_not_called()

    dispatch.execute(capability, proof, action)
    proposal = gateway.authorize.call_args.args[0]
    assert proposal.url == target and proposal.method == "POST"
    assert json.loads(proposal.body) == action["body"]
    runtime.execute.assert_called_once_with(gateway.authorize.return_value)
