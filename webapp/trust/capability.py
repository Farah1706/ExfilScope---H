"""Signed, short-lived, task-scoped agent capabilities (Government Trust extension).

An issuer key signs a capability binding a registered agent identity (its Ed25519 public
key) to one task scope: tool, endpoint label, method, route and expiry. Each request
carries the capability and a proof-of-possession signature made with the agent's private
key over the exact requested action. The validator checks all of it before anything is
passed to the unchanged research gateway. The model never sees or creates capabilities.

Schema ``trust-cap-1`` is versioned separately from every research schema.
"""

import base64
from dataclasses import dataclass
import hashlib
import json
import secrets
from threading import Lock
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import rfc8785

SCHEMA = "trust-cap-1"
ISSUER = "exfilscope-trust-issuer"
MAX_LIFETIME = 300
POP_SKEW = 30


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def public_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def fingerprint(key: Ed25519PublicKey) -> str:
    return hashlib.sha256(public_bytes(key)).hexdigest()[:16]


class Rejected(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Scope:
    task: str
    tool: str
    endpoint_id: str
    method: str
    route_id: str


class Issuer:
    """Holds the signing key in memory only; it is never written, logged or returned."""

    def __init__(self, clock=time.time):
        self._key = Ed25519PrivateKey.generate()
        self.public_key = self._key.public_key()
        self.clock = clock

    def issue(self, agent_id: str, agent_key: Ed25519PublicKey, scope: Scope,
              lifetime: int = 120) -> str:
        if not 0 < lifetime <= MAX_LIFETIME:
            raise ValueError("LIFETIME_OUT_OF_RANGE")
        now = int(self.clock())
        claims = {"v": SCHEMA, "iss": ISSUER, "sub": agent_id, "cnf": b64(public_bytes(agent_key)),
                  "task": scope.task, "tool": scope.tool, "endpoint_id": scope.endpoint_id,
                  "method": scope.method, "route_id": scope.route_id, "iat": now,
                  "exp": now + lifetime, "jti": secrets.token_hex(16)}
        payload = rfc8785.dumps(claims)
        return b64(payload) + "." + b64(self._key.sign(payload))


class AgentIdentity:
    """An agent's own key pair; the private key stays inside this object."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self._key = Ed25519PrivateKey.generate()
        self.public_key = self._key.public_key()

    def prove(self, capability: str, action: dict, clock=time.time) -> str:
        jti = claims_of(capability)["jti"]
        message = rfc8785.dumps({"jti": jti, "action": action, "ts": int(clock())})
        return b64(message) + "." + b64(self._key.sign(message))


def claims_of(capability: str) -> dict:
    try:
        payload, _ = capability.split(".")
        return json.loads(unb64(payload))
    except (ValueError, TypeError) as exc:
        raise Rejected("CAPABILITY_MALFORMED") from exc


def action_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def signed_object(data: bytes, code: str) -> dict:
    try:
        value = json.loads(data)
        if isinstance(value, dict) and rfc8785.dumps(value) == data:
            return value
    except (ValueError, TypeError) as exc:
        raise Rejected(code) from exc
    raise Rejected(code)


class Validator:
    """Server-side checks; registrations are a custodian operation, never agent-supplied."""

    def __init__(self, issuer_key: Ed25519PublicKey, clock=time.time):
        self.issuer_key = issuer_key
        self.clock = clock
        self.registered: dict[str, Ed25519PublicKey] = {}
        self.revoked: set[str] = set()
        self.used: set[str] = set()
        self._lock = Lock()

    def register(self, agent_id: str, key: Ed25519PublicKey) -> None:
        with self._lock:
            self.registered[agent_id] = key

    def revoke(self, agent_id: str) -> None:
        with self._lock:
            self.revoked.add(agent_id)

    def check(self, capability: str, proof: str, action: dict) -> dict:
        with self._lock:
            return self._check(capability, proof, action)

    def _check(self, capability: str, proof: str, action: dict) -> dict:
        try:
            payload_text, signature = capability.split(".")
            payload = unb64(payload_text)
            self.issuer_key.verify(unb64(signature), payload)
        except (AttributeError, ValueError, TypeError, InvalidSignature) as exc:
            raise Rejected("ISSUER_SIGNATURE_INVALID") from exc
        claims = signed_object(payload, "CAPABILITY_SCHEMA_INVALID")
        text_fields = ("v", "iss", "sub", "cnf", "task", "tool", "endpoint_id",
                       "method", "route_id", "jti")
        if (any(not isinstance(claims.get(field), str) for field in text_fields)
                or any(type(claims.get(field)) is not int for field in ("iat", "exp"))
                or not 0 < claims["exp"] - claims["iat"] <= MAX_LIFETIME):
            raise Rejected("CAPABILITY_SCHEMA_INVALID")
        if claims.get("v") != SCHEMA or claims.get("iss") != ISSUER:
            raise Rejected("CAPABILITY_SCHEMA_INVALID")
        now = self.clock()
        if not claims["iat"] - POP_SKEW <= now < claims["exp"]:
            raise Rejected("CAPABILITY_EXPIRED")
        agent = claims["sub"]
        if agent not in self.registered:
            raise Rejected("AGENT_NOT_REGISTERED")
        if agent in self.revoked:
            raise Rejected("AGENT_REVOKED")
        key = self.registered[agent]
        if claims["cnf"] != b64(public_bytes(key)):
            raise Rejected("IDENTITY_KEY_MISMATCH")
        try:
            message_text, pop_signature = proof.split(".")
            message = unb64(message_text)
            key.verify(unb64(pop_signature), message)
        except (AttributeError, ValueError, TypeError, InvalidSignature) as exc:
            raise Rejected("PROOF_OF_POSSESSION_INVALID") from exc
        bound = signed_object(message, "PROOF_OF_POSSESSION_INVALID")
        try:
            same_action = rfc8785.dumps(bound.get("action")) == rfc8785.dumps(action)
        except (ValueError, TypeError) as exc:
            raise Rejected("PROOF_NOT_BOUND_TO_ACTION") from exc
        if bound.get("jti") != claims["jti"] or not same_action:
            raise Rejected("PROOF_NOT_BOUND_TO_ACTION")
        if type(bound.get("ts")) is not int or abs(now - bound["ts"]) > POP_SKEW:
            raise Rejected("PROOF_STALE")
        for field in ("tool", "endpoint_id", "method", "route_id"):
            if action.get(field) != claims[field]:
                raise Rejected("OUT_OF_SCOPE_" + field.upper())
        if claims["jti"] in self.used:
            raise Rejected("CAPABILITY_REPLAYED")
        self.used.add(claims["jti"])
        return {"agent_id": agent, "task": claims["task"], "jti": claims["jti"][:8],
                "expires_in_s": round(claims["exp"] - now, 1)}
