import shutil
import ssl
from pathlib import Path

import pytest

from exfilscope.isolation import probe_write_access
from exfilscope.runtime import Runtime


def test_compose_static_boundaries_do_not_grant_cross_writer_mounts():
    from ruamel.yaml import YAML
    model = YAML(typ="safe").load((Path(__file__).parents[1] / "compose.yaml").read_text())
    runtime, proxy, reader = (model["services"][name] for name in ("runtime", "proxy", "verifier"))
    assert set(runtime["networks"]) == {"agent", "tool"} and set(proxy["networks"]) == {"tool", "receivers"}
    assert all("ledger_b" not in mount for mount in runtime["volumes"])
    assert all("ledger_a" not in mount for mount in proxy["volumes"])
    assert all(mount.endswith(":ro") for mount in reader["volumes"])
    assert runtime["user"] != proxy["user"]
    assert all(net["internal"] for net in model["networks"].values())
    assert model['services']['agent']['networks']==['agent']
    assert 'volumes' not in model['services']['agent']


def test_write_probe_detects_real_capability_and_rolls_back(gateway):
    assert probe_write_access(gateway.writer.path) == "WRITABLE"
    assert probe_write_access(gateway.writer.path.parent / "not_mounted.sqlite") == "UNMOUNTED_OR_MISSING"


@pytest.mark.parametrize("fault", ["no_certificate_check", "no_hostname_check"])
def test_runtime_rejects_disabled_tls_verification(gateway, fault):
    context = ssl.create_default_context()
    context.check_hostname = False
    if fault == "no_certificate_check":
        context.verify_mode = ssl.CERT_NONE
    with pytest.raises(ValueError, match="TLS_CERTIFICATE_AND_HOSTNAME_VERIFICATION_REQUIRED"):
        Runtime(gateway.writer, "http://127.0.0.1:8080", context)


@pytest.mark.integration
def test_docker_deployment_validation():
    if not shutil.which("docker"):
        pytest.skip("UNVERIFIED: Docker executable unavailable; mounts/users/network checks not run")
    # The validation runner uses the project's compose file only and owns its test stack.
    from deploy.validate import validate
    result = validate()
    if result["status"] == "UNVERIFIED":
        pytest.skip("UNVERIFIED: " + result["reason"])
    assert result["status"] == "VERIFIED"
