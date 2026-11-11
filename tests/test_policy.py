import json
import sqlite3

import pytest

from exfilscope.canonical import InvalidJSON, canonical_bytes, commitment, parse_body
from exfilscope.contracts import Decision, ProposedAction, RuntimeEvent
from exfilscope.ledger import MonitorWriter, read_events
from exfilscope.privacy import routine_paths, scan_routine_files
from exfilscope.registry import PLACEHOLDER, ProtectedItem, Registry

URL = "http://127.0.0.1:8801/collect"


def action(body="{}", **changes):
    return ProposedAction(url=changes.pop("url", URL), body=body, **changes)


@pytest.mark.parametrize("redaction,decision", [(False, Decision.REDACT), (True, Decision.REDACT)])
def test_nested_multiple_protected_values(gateway, redaction, decision):
    values = [i.value for i in gateway.registry.items]
    body = {"nested": [values[0] + values[0], {"text": values[1]}]}
    result = gateway.authorize(action(json.dumps(body), allow_redaction=redaction))
    assert result.event.decision == decision
    assert {h.protected_id for h in result.event.hits} == {"SECRET_001", "SECRET_002"}
    assert [h.location for h in result.event.hits] == ["$/o0/a0", "$/o0/a1/o0"]
    if decision == Decision.REDACT:
        assert all(v not in result.permitted_action.body for v in values)
        assert result.permitted_action.body.count(PLACEHOLDER) == 3
    else:
        assert result.permitted_action is None


def test_allow_keeps_original_distinct(gateway):
    original = action('{ "b": 2, "a": 1 }')
    result = gateway.authorize(original)
    assert result.event.decision == Decision.ALLOW
    assert original.body == '{ "b": 2, "a": 1 }'
    assert result.permitted_action.body == '{"a":1,"b":2}'


def test_forbidden_destination(gateway):
    result = gateway.authorize(action(url="http://127.0.0.1:8802/collect"))
    assert result.event.reason == "FORBIDDEN_DESTINATION"
    assert result.event.decision == Decision.BLOCK
    assert result.event.permitted is None and result.event.payload_hmac is None


@pytest.mark.parametrize("body", ["", "not json", '{"a":1,"a":2}', '{"a":NaN}',
                                  '{"a":Infinity}', '{"a":1e400}', "null", "42", '"text"',
                                  '{"a":9007199254740992}', '{"a":"\\ud800"}',
                                  "[" * 40 + "]" * 40, '{"x":"' + "x" * 65536 + '"}'],
                         ids=lambda body: f"invalid-length-{len(body)}")
def test_unsupported_json_fails_closed(gateway, body):
    result = gateway.authorize(action(body))
    assert result.event.decision == Decision.BLOCK
    assert result.event.reason == "INVALID_JSON"
    with pytest.raises(InvalidJSON):
        parse_body(body)


@pytest.mark.parametrize("change", [
    {"url": "http://127.0.0.1:8801/collect?q=SYNTHETIC_API_KEY_A71X9Q"},
    {"url": "http://SYNTHETIC_API_KEY_A71X9Q@127.0.0.1:8801/collect"},
    {"url": "http://127.0.0.1:8801/SYNTHETIC_API_KEY_A71X9Q"},
    {"url": "http://127.0.0.1:8801/collect#SYNTHETIC_API_KEY_A71X9Q"},
    {"headers": {"X-data": "SYNTHETIC_API_KEY_A71X9Q"}},
    {"url": "http://127.0.0.1:8801/collect?q=harmless"},
    {"url": "ftp://127.0.0.1:8801/collect"},
    {"url": "http://127.0.0.1:invalid/collect"},
    {"url": "http://127.0.0.1:8801/unknown"},
    {"headers": {"Authorization": "harmless"}},
    {"headers": {"Content-Type": "application/json", "content-type": "application/json"}},
    {"method": "TRACE"}, {"tool": "OTHER_TOOL"},
])
def test_unsafe_metadata_blocked_and_sanitized(gateway, change):
    result = gateway.authorize(action(**change))
    assert result.event.decision == Decision.BLOCK
    assert not gateway.registry.contains(result.event.model_dump_json())


def test_protected_json_key_blocked_even_with_redaction(gateway):
    secret = gateway.registry.items[0].value
    result = gateway.authorize(action(json.dumps({secret: "safe"}), allow_redaction=True))
    assert result.event.reason == "PROTECTED_JSON_KEY"
    assert result.event.hits[0].location == "$/o0/key"
    assert secret not in result.event.model_dump_json()


def test_malformed_tool_schema_has_unique_trace(gateway):
    one = gateway.authorize_input({"url": URL, "body": 22})
    two = gateway.authorize_input({"unexpected": "SYNTHETIC_API_KEY_A71X9Q"})
    assert one.event.reason == two.event.reason == "INVALID_SCHEMA"
    assert one.event.trace_id != two.event.trace_id
    assert not gateway.registry.contains(two.event.model_dump_json())


def test_hmac_equivalence_and_divergence():
    key = b"a" * 32
    a = parse_body('{"a":1,"b":[2,3]}')
    b = parse_body('{ "b": [2.0, 3], "a": 1.0 }')
    assert commitment(a, key) == commitment(b, key)
    assert commitment(a, key) != commitment({"a": 1, "b": [3, 2]}, key)
    assert commitment(a, key) != commitment(a, b"b" * 32)
    with pytest.raises(ValueError):
        commitment(a, b"short")


def test_rfc8785_numeric_and_utf16_order_vector():
    assert canonical_bytes({"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 1e-27]}) == \
        b'{"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27]}'
    assert canonical_bytes({"\ufffd": 1, "\U0001f600": 2}) == \
        '{"\U0001f600":2,"\ufffd":1}'.encode()


@pytest.mark.parametrize("value", [{1: "bad"}, {"bad": (1, 2)}, {"bad": float("nan")}])
def test_canonical_python_types_rejected(value):
    with pytest.raises(InvalidJSON):
        canonical_bytes(value)


@pytest.mark.parametrize("values", [("ABCDEFGH", "ABCDEFGH"), ("ABCDEFGH", "ABCDEFGH-more")])
def test_registry_rejects_overlaps(values):
    items = [ProtectedItem(protected_id=f"SECRET_{i}", value=value,
                           source_ref=f"DOC_{i}", data_type="API_KEY")
             for i, value in enumerate(values)]
    with pytest.raises(ValueError):
        Registry(items)


def test_ledgers_and_wal_have_no_protected_plaintext(gateway):
    # Keep a reader open while writing so WAL exists during the exposure scan.
    db = sqlite3.connect(gateway.writer.path)
    db.execute("BEGIN")
    db.execute("SELECT * FROM events").fetchall()
    try:
        for item in gateway.registry.items:
            gateway.authorize(action(json.dumps({item.value: [item.value]}), allow_redaction=True))
            gateway.authorize(action(json.dumps({"text": item.value}), allow_redaction=True))
        paths = routine_paths(gateway.writer.path.parent)
        assert any(p.name.endswith("-wal") for p in paths)
        assert scan_routine_files(paths, gateway.registry) == {}
    finally:
        db.close()
    assert len(read_events(gateway.writer.path, RuntimeEvent, "A")) == 2 * len(gateway.registry.items)
    with pytest.raises(ValueError):
        MonitorWriter(gateway.writer.path)


def test_privacy_scanner_finds_escaped_exposure(gateway, tmp_path):
    path = tmp_path / "unsafe.log"
    path.write_text("".join(f"\\u{ord(c):04x}" for c in gateway.registry.items[0].value))
    assert scan_routine_files([path], gateway.registry) == {"unsafe.log": ["SECRET_001"]}


def test_failed_ledger_write_never_returns_permission(gateway, monkeypatch):
    def fail(_):
        raise sqlite3.OperationalError("controlled failure")
    monkeypatch.setattr(gateway.writer, "insert", fail)
    with pytest.raises(sqlite3.OperationalError):
        gateway.authorize(action())
