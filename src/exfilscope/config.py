"""Trusted endpoint labels and environment configuration; no agent-selected networking."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import Metadata

TRACE_HEADER = "X-ExfilScope-Trace"
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class Catalog:
    def __init__(self, endpoints: dict[str, str], routes: dict[str, str]):
        self.endpoints = endpoints
        self.routes = routes
        for origin, label in endpoints.items():
            parts = urlsplit(origin)
            if (parts.scheme not in ("http", "https") or not parts.hostname
                    or parts.username or parts.password or parts.path or parts.query
                    or parts.fragment):
                raise ValueError("INVALID_CATALOG")
            self._label(label)
            normalized = f"{parts.scheme}://{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}"
            if origin != normalized:
                raise ValueError("CATALOG_ORIGINS_REQUIRE_EXPLICIT_NORMALIZED_PORT")
        if len(set(endpoints.values())) != len(endpoints):
            raise ValueError("DUPLICATE_ENDPOINT_LABEL")
        for route, label in routes.items():
            if not route.startswith("/") or any(c in route for c in "?#%"):
                raise ValueError("INVALID_ROUTE")
            self._label(label)
        if len(set(routes.values())) != len(routes):
            raise ValueError("DUPLICATE_ROUTE_LABEL")

    @staticmethod
    def _label(label: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", label):
            raise ValueError("INVALID_LABEL")

    def metadata(self, url: str, method: str) -> tuple[Metadata, tuple[str, ...]]:
        anomalies = []
        try:
            parts = urlsplit(url)
            port = parts.port or (443 if parts.scheme == "https" else 80)
            host = parts.hostname
            origin = f"{parts.scheme}://{host}:{port}"
            endpoint = self.endpoints.get(origin, "UNREGISTERED")
            route = self.routes.get(parts.path, "UNREGISTERED")
            if parts.username or parts.password or parts.query or parts.fragment:
                anomalies.append("UNSUPPORTED_URL_COMPONENT")
        except ValueError:
            endpoint = route = "UNREGISTERED"
            anomalies.append("INVALID_URL")
        if endpoint == "UNREGISTERED":
            anomalies.append("UNKNOWN_ENDPOINT")
        if route == "UNREGISTERED":
            anomalies.append("UNKNOWN_ROUTE")
        method_label = method if method in METHODS else "UNSUPPORTED"
        if method_label == "UNSUPPORTED":
            anomalies.append("UNSUPPORTED_METHOD")
        return Metadata(endpoint_id=endpoint, route_id=route, method=method_label), tuple(anomalies)

    @classmethod
    def from_env(cls) -> "Catalog":
        return cls(json.loads(os.environ["EXFILSCOPE_ENDPOINTS"]),
                   json.loads(os.environ["EXFILSCOPE_ROUTES"]))


def load_key(path: Path) -> bytes:
    key = path.read_bytes()
    if len(key) != 32:
        raise ValueError("KEY_MUST_BE_256_BITS")
    return key
