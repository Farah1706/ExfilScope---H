"""Project-local lab lifecycle: real receiver servers and a separate mitmdump process.

Only loopback endpoints are created. TLS trust is local to client/proxy contexts.
"""

import ipaddress
import json
import os
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from uuid import uuid4
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .config import Catalog, TRACE_HEADER
from .gateway import Gateway
from .ledger import RuntimeWriter, read_monitor_snapshot
from .health import boundary_fingerprint
from .registry import ProtectedItem, Registry
from .runtime import Runtime
from .clock import ClockContext
from .policy import GatewayPolicy, PolicyRule


HOSTS = ("127.0.0.1", "127.0.0.2")  # the second loopback host serves host-change faults


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def make_certificate(directory: Path) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ExfilScope laboratory")])
    now = datetime.now(UTC)
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=5))
                   .not_valid_after(now + timedelta(days=2))
                   .add_extension(x509.SubjectAlternativeName([
                       x509.IPAddress(ipaddress.ip_address(host)) for host in HOSTS]), critical=False)
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "receiver.pem", directory / "receiver.key"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                          serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    return cert_path, key_path


class Receiver:
    def __init__(self, tls: tuple[Path, Path] | None, label: str, host: str = HOSTS[0],
                 port: int = 0, *, keep_alive: bool = False):
        self.label = label
        self.delay = 0.0  # seconds to hold the response; set only by timeout diagnostics
        self.requests: list[dict] = []  # restricted ephemeral ground truth, never ledger evidence
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1" if keep_alive else "HTTP/1.0"
            def log_message(self, *_: object) -> None:
                pass

            def receive(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                receiver.requests.append({"body": raw, "method": self.command,
                                          "path": self.path,
                                          "trace_present": TRACE_HEADER in self.headers,
                                          "received_monotonic": time.monotonic()})
                if self.path == "/timeout":
                    time.sleep(1)
                time.sleep(receiver.delay)
                status = 307 if self.path == "/redirect" else 200
                self.send_response(status)
                if status == 307:
                    self.send_header("Location", "/collect")
                body = b'{"accepted":true}'
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ssl.SSLError):
                    pass

            do_POST = do_GET = do_PUT = do_PATCH = do_DELETE = receive

        self.server = ThreadingHTTPServer((host, port), Handler)
        if tls:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(*tls)
            self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class Lab:
    def __init__(self, directory: Path, protocol: str = "http", *,
                 check_permissions: bool = False, trust_upstream: bool = True,
                 registry: Registry | None = None, policy: GatewayPolicy | None = None,
                 fas_content: Path | None = None, measurement: Path | None = None):
        if protocol not in ("http", "https"):
            raise ValueError("INVALID_LAB_PROTOCOL")
        self.directory, self.protocol = directory.resolve(), protocol
        self.check_permissions, self.trust_upstream = check_permissions, trust_upstream
        self.fail_request_write_once = False
        self._registry, self._policy = registry, policy
        self.fas_content = fas_content
        self.measurement = measurement
        if fas_content is not None and measurement is not None:
            raise ValueError("SEPARATE_FAS_AND_TIMING_RUNS")
        self.receivers: list[Receiver] = []
        self.process: subprocess.Popen | None = None
        self.log = None

    def __enter__(self) -> "Lab":
        self.directory.mkdir(parents=True, exist_ok=False)
        try:
            tls = make_certificate(self.directory) if self.protocol == "https" else None
            self.receivers = [Receiver(tls, "AUTHORIZED", keep_alive=self.measurement is not None)]
            self.receivers.append(Receiver(tls, "UNAUTHORIZED"))
            # Same port as the authorized receiver on another host: a pure host change.
            self.receivers.append(Receiver(tls, "ALTERNATE_HOST", HOSTS[1], self.receivers[0].port))
            self.allowed_url = f"{self.protocol}://127.0.0.1:{self.receivers[0].port}/collect"
            self.forbidden_url = f"{self.protocol}://127.0.0.1:{self.receivers[1].port}/collect"
            self.alternate_url = f"{self.protocol}://127.0.0.2:{self.receivers[0].port}/collect"
            self.catalog = Catalog({
                self.allowed_url.removesuffix("/collect"): "AUTHORIZED",
                self.forbidden_url.removesuffix("/collect"): "UNAUTHORIZED",
                self.alternate_url.removesuffix("/collect"): "ALTERNATE_HOST",
            }, {"/collect": "COLLECT", "/alternate": "ALTERNATE", "/timeout": "TIMEOUT",
                "/redirect": "REDIRECT"})
            self.key = secrets.token_bytes(32)
            key_path = self.directory / "hmac.key"
            key_path.write_bytes(self.key)
            key_path.chmod(0o600)
            self.registry = self._registry or Registry([
                ProtectedItem(protected_id="SECRET_001", value="SYNTHETIC_API_KEY_A71X9Q",
                              source_ref="DOC_001:chunk_1", data_type="API_KEY"),
                ProtectedItem(protected_id="SECRET_002", value="SYNTHETIC_CONFIDENTIAL_TEXT_B82Y6R",
                              source_ref="DOC_002:chunk_2", data_type="CONFIDENTIAL_TEXT"),
                ProtectedItem(protected_id="SECRET_003", value="SYNTHETIC_ACCOUNT_ID_C93Z4T",
                              source_ref="DOC_003:chunk_1", data_type="ACCOUNT_ID"),
            ])
            self.a_path = self.directory / "ledger_a" / "runtime.sqlite"
            self.b_path = self.directory / "ledger_b" / "network.sqlite"
            self.writer = RuntimeWriter(self.a_path)
            self.clock = ClockContext(host_id="LAB_HOST", clock_domain_id=str(uuid4()))
            self.policy = self._policy or GatewayPolicy(version="lab-policy-2", rules=tuple(
                PolicyRule(endpoint_id="AUTHORIZED", method="POST", route_id=route,
                           approved_fields=("/case", "/data", "/data/*/text", "/text",
                                            "/changed", "/a", "/b"),
                           redaction_paths=("/data/*/text", "/data/*"))
                for route in self.catalog.routes.values()))
            self.gateway = Gateway(self.registry, self.catalog, {"AUTHORIZED"}, self.key,
                                   "lab-key-1", self.writer, policy=self.policy, clock=self.clock)
            self.proxy = f"http://127.0.0.1:{free_port()}"
            env = os.environ.copy()
            env.update(EXFILSCOPE_ENDPOINTS=json.dumps(self.catalog.endpoints),
                       EXFILSCOPE_ROUTES=json.dumps(self.catalog.routes),
                       EXFILSCOPE_KEY_FILE=str(key_path), EXFILSCOPE_LEDGER_B=str(self.b_path),
                       EXFILSCOPE_PROXY_IDENTITY=self.proxy,
                       EXFILSCOPE_HOST_ID=self.clock.host_id,
                       EXFILSCOPE_CLOCK_DOMAIN_ID=self.clock.clock_domain_id,
                       EXFILSCOPE_KEY_ID="lab-key-1")
            if self.check_permissions:
                env.update(EXFILSCOPE_LAB_TEST_CONTROLS="1",
                           EXFILSCOPE_TEST_PERMISSION_PROBE_A=str(self.a_path))
            if self.fail_request_write_once:
                env.update(EXFILSCOPE_LAB_TEST_CONTROLS="1",
                           EXFILSCOPE_TEST_REQUEST_WRITE_FAILURE="1")
            executable = Path(sys.executable).parent / (
                "mitmdump.exe" if os.name == "nt" else "mitmdump")
            addon = Path(__file__).with_name("proxy_addon.py")
            if self.measurement is not None:
                self.measurement.parent.mkdir(parents=True, exist_ok=True)
                self.measurement.touch(exist_ok=False)
                env["EXFILSCOPE_MEASUREMENT_JOURNAL"] = str(self.measurement.resolve())
                addon = Path(__file__).parent / "research" / "measurement_addon.py"
            command = [str(executable), "-q", "--listen-host", "127.0.0.1", "--listen-port",
                       self.proxy.rsplit(":", 1)[1], "-s", str(addon),
                       "--set", f"confdir={self.directory / 'proxy_ca'}",
                       "--set", "flow_detail=0", "--set", "termlog_verbosity=error",
                       "--set", "connection_strategy=lazy", "--set", "body_size_limit=64k"]
            if tls and self.trust_upstream:
                command += ["--set", f"ssl_verify_upstream_trusted_ca={tls[0]}"]
            if self.fas_content is not None:
                self.fas_content.parent.mkdir(parents=True, exist_ok=True)
                self.fas_content.touch(exist_ok=False)
                env["EXFILSCOPE_FAS_CONTENT"] = str(self.fas_content.resolve())
                # Capture the incoming trace before the monitor removes it for forwarding.
                command[6:6] = ["-s", str(Path(__file__).parent / "research" / "content_addon.py")]
            self.log = (self.directory / "proxy.log").open("wb")
            self._monitor_command, self._monitor_env = command, env
            self._launch_monitor()
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("PROXY_START_FAILED_INSPECT_PROJECT_LOG")
                if self.b_path.exists():
                    try:
                        _, health = read_monitor_snapshot(self.b_path)
                        if health and health[-1].kind == "PULSE":
                            break
                    except sqlite3.OperationalError:
                        pass  # startup schema has not committed yet
                time.sleep(0.1)
            else:
                raise RuntimeError("PROXY_START_TIMEOUT")
            self.tls_context = None
            if tls:
                self.tls_context = ssl.create_default_context(
                    cafile=str(self.directory / "proxy_ca" / "mitmproxy-ca-cert.pem"))
            self.runtime = Runtime(self.writer, self.proxy, self.tls_context)
            self.wait_for_health(time.monotonic(), startup=True)
            return self
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        for receiver in self.receivers:
            receiver.close()

    def _launch_monitor(self) -> None:
        self.process = subprocess.Popen(self._monitor_command, env=self._monitor_env,
                                        stdout=self.log, stderr=self.log,
                                        creationflags=subprocess.CREATE_NO_WINDOW
                                        if os.name == "nt" else 0)

    def restart_monitor(self, test_controls: dict[str, str] | None = None) -> None:
        """Explicit lab-only restart; never join separate runs into continuous coverage.

        `test_controls` arms the monitor's lab-only fault controls for this generation only.
        """
        if self.process.poll() is None:
            raise ValueError("STOP_MONITOR_BEFORE_RESTART")
        environment = self._monitor_env
        if test_controls:
            self._monitor_env = dict(environment, EXFILSCOPE_LAB_TEST_CONTROLS="1", **test_controls)
        try:
            self._launch_monitor()
        finally:
            self._monitor_env = environment
        self.wait_for_health(time.monotonic(), timeout=20, startup=True)

    def wait_for_health(self, end: float, timeout: float = 1.0, *, startup: bool = False) -> None:
        """Wait until a durable monotonic barrier or drain deadline; never fabricate one."""
        deadline = time.monotonic() + max(0, end - time.monotonic()) + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return
            try:
                _, health = read_monitor_snapshot(self.b_path)
            except sqlite3.OperationalError:
                if not startup:
                    raise
                # A file/listening socket is not proof that addon schema initialization
                # has committed. Retry only during initial readiness, never fabricate health.
                time.sleep(0.05)
                continue
            if len(health) >= 2 and health[-2].processed_through is not None \
                    and health[-2].processed_through >= end:
                return
            time.sleep(0.05)

    def snapshot(self):
        return read_monitor_snapshot(self.b_path)

    @property
    def boundary_id(self) -> str:
        return boundary_fingerprint(self.catalog, self.proxy)

    def __exit__(self, *_: object) -> None:
        self.close()
