"""Strict JSON acceptance and standards-based, body-only keyed commitments."""

import hashlib
import hmac
import json
import math
from typing import Any

import rfc8785

MAX_BODY = 65536
MAX_DEPTH = 32


class InvalidJSON(ValueError):
    """Exception messages never embed input."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out = {}
    for key, value in pairs:
        if key in out:
            raise InvalidJSON("DUPLICATE_KEYS")
        out[key] = value
    return out


def _constant(_: str) -> None:
    raise InvalidJSON("NONFINITE_NUMBER")


def _validate(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise InvalidJSON("EXCESSIVE_DEPTH")
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise InvalidJSON("INVALID_KEY")
            _validate(key, depth + 1)
            _validate(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _validate(item, depth + 1)
    elif type(value) is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise InvalidJSON("INVALID_UNICODE") from None
    elif type(value) is float:
        if not math.isfinite(value):
            raise InvalidJSON("NONFINITE_NUMBER")
    elif value is not None and type(value) not in (bool, int):
        raise InvalidJSON("UNSUPPORTED_TYPE")


def parse_body(raw: str | bytes) -> dict | list:
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
        if len(encoded) > MAX_BODY:
            raise InvalidJSON("BODY_TOO_LARGE")
        value = json.loads(encoded.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_constant)
        if not isinstance(value, (dict, list)):
            raise InvalidJSON("UNSUPPORTED_ROOT")
        canonical_bytes(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidJSON("INVALID_JSON") from None


def canonical_bytes(value: Any) -> bytes:
    try:
        _validate(value)
        return rfc8785.dumps(value)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidJSON("INVALID_JSON") from None


def commitment(value: Any, key: bytes) -> str:
    if len(key) != 32:
        raise ValueError("KEY_MUST_BE_256_BITS")
    return hmac.new(key, canonical_bytes(value), hashlib.sha256).hexdigest()
