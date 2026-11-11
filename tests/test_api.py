import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from exfilscope.api import app_from_env, create_app
from exfilscope.contracts import RuntimeEvent
from exfilscope.ledger import read_events
from exfilscope.runtime import Runtime


def test_gateway_api_rejects_without_echoing_plaintext(gateway):
    client = TestClient(create_app(gateway, Runtime(gateway.writer, "http://127.0.0.1:1")))
    secret = gateway.registry.items[0].value
    response = client.post("/execute", content=json.dumps({"bad": secret}))
    assert response.status_code == 400 and secret not in response.text
    assert response.json()["reason"] == "INVALID_SCHEMA"
    assert len(read_events(gateway.writer.path, RuntimeEvent, "A")) == 1


def production_env(monkeypatch, tmp_path):
    examples = Path(__file__).parents[1] / "examples"
    key = tmp_path / "hmac.key"
    key.write_bytes(b"k" * 32)
    for name, value in {"EXFILSCOPE_LEDGER_A": str(tmp_path / "a" / "runtime.sqlite"),
                        "EXFILSCOPE_REGISTRY": str(examples / "registry.json"),
                        "EXFILSCOPE_ENDPOINTS": '{"http://127.0.0.1:8801":"AUTHORIZED"}',
                        "EXFILSCOPE_ROUTES": '{"/collect":"COLLECT"}',
                        "EXFILSCOPE_APPROVED": "AUTHORIZED",
                        "EXFILSCOPE_KEY_FILE": str(key),
                        "EXFILSCOPE_PROXY": "http://127.0.0.1:1"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("EXFILSCOPE_PROXY_CA", raising=False)
    return examples


def test_production_api_refuses_to_start_without_policy(monkeypatch, tmp_path):
    production_env(monkeypatch, tmp_path)
    monkeypatch.delenv("EXFILSCOPE_POLICY_FILE", raising=False)
    with pytest.raises(ValueError, match="EXFILSCOPE_POLICY_FILE_REQUIRED"):
        app_from_env()
    assert not (tmp_path / "a" / "runtime.sqlite").exists()


def test_production_api_uses_configured_policy(monkeypatch, tmp_path):
    examples = production_env(monkeypatch, tmp_path)
    monkeypatch.setenv("EXFILSCOPE_POLICY_FILE", str(examples / "policy.json"))
    client = TestClient(app_from_env())
    response = client.post("/execute", json={"url": "http://127.0.0.1:8801/collect",
                                            "body": json.dumps({"unapproved": "x"})})
    assert response.json()["policy_version"] == "example-policy-2"
    assert response.json()["reason"] == "UNAPPROVED_JSON_FIELD"


def test_gateway_api_valid_json_contract_and_protected_block(gateway):
    client = TestClient(create_app(gateway, Runtime(gateway.writer, "http://127.0.0.1:1")))
    secret = gateway.registry.items[0].value
    response = client.post("/execute", json={"url": "http://127.0.0.1:8801/collect",
                                            "body": json.dumps({"text": secret})})
    assert response.status_code == 200 and secret not in response.text
    assert response.json()["decision"] == "BLOCK"
    assert response.json()["claim"] == "NOT_EXECUTED"
