from pathlib import Path

import pytest

from exfilscope.config import Catalog
from exfilscope.gateway import Gateway
from exfilscope.ledger import RuntimeWriter
from exfilscope.registry import Registry
from exfilscope.policy import GatewayPolicy, PolicyRule


@pytest.fixture
def gateway(tmp_path):
    registry = Registry.load(Path(__file__).parents[1] / "examples" / "registry.json")
    catalog = Catalog({"http://127.0.0.1:8801": "AUTHORIZED",
                       "http://127.0.0.1:8802": "UNAUTHORIZED"},
                      {"/collect": "COLLECT", "/alternate": "ALTERNATE"})
    return Gateway(registry, catalog, {"AUTHORIZED"}, b"a" * 32, "test-key-1",
                   RuntimeWriter(tmp_path / "a" / "runtime.sqlite"),
                   policy=GatewayPolicy(version="test-policy-2", rules=tuple(
                       PolicyRule(endpoint_id="AUTHORIZED", method="POST", route_id=route,
                                  approved_fields=("/nested", "/nested/*/text", "/text", "/a",
                                                   "/b", "/x"),
                                  redaction_paths=("/nested/*", "/nested/*/text"))
                       for route in ("COLLECT", "ALTERNATE"))))
