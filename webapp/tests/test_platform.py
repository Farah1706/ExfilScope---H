"""Platform boundaries without network experiments: validation, service guards, privacy,
snapshot integrity, readiness degradation and the static UI contract."""

import json
from pathlib import Path
import re
import sys
import time

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from dashboard.evidence import load_catalog
from exfilscope.registry import Registry
from exfilscope.research.fas_review import QUESTIONS
from webapp import readiness, research, server
from webapp.contracts import RunRequest
from webapp.evidence import load_run_snapshot
from webapp.interpret import incident_view, title
from webapp.paths import ROOT, SNAPSHOTS, STATIC, env_root
from webapp.runs import NotOwner, RunManager
from webapp.scenarios import BY_ID, SCENARIOS, lab_case

TOKEN = "test-launch-token-0123456789abcdef"
BASE = "http://127.0.0.1:8600"
ORIGIN = {"Origin": BASE, "X-ExfilScope": "1"}
REGISTRY = Registry.load(ROOT / "examples/registry.json")
RUN = RunRequest.model_validate({"scenario_id": "routine-submission", "mode": "lab",
                                 "protocol": "http"})
READY = {"items": [], "modes": {m: {"ready": True, "blocking": []}
                                for m in ("lab", "stub", "live", "trust")}}


def sleeper(seconds=30):
    return [sys.executable, "-c", f"import sys, time; sys.stdin.read(); time.sleep({seconds})"]


@pytest.fixture
def manager(tmp_path):
    return RunManager(runs=tmp_path / "runs", command=sleeper())


@pytest.fixture
def client(manager, monkeypatch):
    monkeypatch.setattr(readiness, "check", lambda: READY)
    app = server.create_app(token=TOKEN, port=8600, manager=manager)
    with TestClient(app, base_url=BASE) as c:
        yield c
    manager.shutdown()


def login(client):
    response = client.post("/api/session", json={"token": TOKEN}, headers=ORIGIN)
    assert response.status_code == 200
    return client


# ---- run requests -----------------------------------------------------------------------

def test_run_request_accepts_supported_combinations():
    for scenario in SCENARIOS:
        for mode in scenario.modes():
            RunRequest.model_validate({"scenario_id": scenario.id, "mode": mode, "protocol": "https"})


@pytest.mark.parametrize("payload", [
    {"scenario_id": "../../etc/passwd", "mode": "lab", "protocol": "http"},
    {"scenario_id": "transmission-after-rejection", "mode": "live", "protocol": "http"},
    {"scenario_id": "routine-submission", "mode": "lab", "protocol": "ftp"},
    {"scenario_id": "routine-submission", "mode": "lab", "protocol": "http", "protected_item": "SECRET_001"},
    {"scenario_id": "confidential-request", "mode": "live", "protocol": "http", "protected_item": "SECRET_002"},
    {"scenario_id": "confidential-request", "mode": "lab", "protocol": "http", "protected_item": "SECRET_999"},
    {"scenario_id": "missing-observation", "mode": "lab", "protocol": "http", "claim_mode": "false_not_executed"},
    {"scenario_id": "routine-submission", "mode": "lab", "protocol": "http", "url": "http://example.com"},
    {"scenario_id": "routine-submission", "mode": "lab", "protocol": "http", "command": "calc.exe"},
    {"scenario_id": "government-trust", "mode": "lab", "protocol": "http"},
    {"scenario_id": 7, "mode": "lab", "protocol": "http"},
])
def test_run_request_rejects_unsupported_or_unsafe_input(payload):
    with pytest.raises(ValidationError):
        RunRequest.model_validate(payload)


def test_lab_case_selects_registry_item_and_payload_subtype():
    alteration, substitution = BY_ID["modified-after-approval"], BY_ID["redaction-reversed"]
    for index, item in enumerate(("SECRET_001", "SECRET_002", "SECRET_003")):
        assert lab_case(alteration, item) % 2 == 0 and lab_case(alteration, item) % 3 == index
        assert lab_case(substitution, item) % 2 == 1 and lab_case(substitution, item) % 3 == index
    assert lab_case(BY_ID["prohibited-transfer"], "SECRET_003") == 2


def test_scenario_library_maps_eight_research_types_and_one_extension():
    core = [s for s in SCENARIOS if not s.extension]
    assert [s.number for s in core] == list(range(1, 9))
    assert {s.lab_scenario for s in core} == {"allow", "redact", "block", "block_bypass",
                                              "payload_divergence", "destination_divergence",
                                              "no_observation"}
    # Live mode is offered only where the frozen agent tasks exist.
    assert {s.id for s in core if "live" in s.modes()} == {
        "routine-submission", "confidential-request", "prohibited-transfer"}


# ---- service guards ---------------------------------------------------------------------

def test_api_requires_session_and_valid_token(client):
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/session", json={"token": "wrong"}, headers=ORIGIN).status_code == 401
    assert client.post("/api/session", json={"token": TOKEN}).status_code == 403
    login(client)
    assert client.get("/api/status").status_code == 200


def test_session_state_requires_a_session(client):
    assert client.get("/api/session").status_code == 401
    assert client.get("/api/session").json()["error"] == "SESSION_REQUIRED"
    login(client)
    assert client.get("/api/session").status_code == 200


def test_stale_reused_and_invalid_launch_states(client, monkeypatch):
    cookie = client.app.state.cookie
    client.cookies.set(cookie, "stale-session-from-an-earlier-launch")
    response = client.get("/api/status")
    assert response.status_code == 401 and response.json()["error"] == "SESSION_EXPIRED_OR_STALE"
    client.cookies.clear()
    bad = client.post("/api/session", json={"token": "not-the-token"}, headers=ORIGIN)
    assert bad.status_code == 401 and bad.json()["error"] == "INVALID_LAUNCH_TOKEN"
    login(client)
    client.cookies.clear()
    again = client.post("/api/session", json={"token": TOKEN}, headers=ORIGIN)
    assert again.status_code == 401 and again.json()["error"] == "LAUNCH_LINK_ALREADY_USED"


def test_sessions_expire_when_idle(client, monkeypatch):
    login(client)
    assert client.get("/api/status").status_code == 200
    monkeypatch.setattr(server, "SESSION_IDLE_SECONDS", 0.05)
    time.sleep(0.1)
    response = client.get("/api/status")
    assert response.status_code == 401 and response.json()["error"] == "SESSION_EXPIRED_OR_STALE"


def test_request_bodies_are_bounded(client):
    login(client)
    big = b'{"token":"' + b"a" * (server.MAX_BODY_BYTES + 1) + b'"}'
    response = client.post("/api/runs", content=big,
                           headers={**ORIGIN, "Content-Type": "application/json"})
    assert response.status_code == 413


def test_cookie_name_is_specific_to_the_port(client):
    response = client.post("/api/session", json={"token": TOKEN}, headers=ORIGIN)
    assert response.headers["set-cookie"].startswith("exfilscope_session_8600=")


def test_cookie_is_httponly_and_strict(client):
    response = client.post("/api/session", json={"token": TOKEN}, headers=ORIGIN)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_host_and_origin_checks(client):
    login(client)
    assert client.get("/healthz", headers={"Host": "attacker.example"}).status_code == 421
    bad_origin = {"Origin": "http://attacker.example", "X-ExfilScope": "1"}
    payload = {"scenario_id": "routine-submission", "mode": "lab", "protocol": "http"}
    assert client.post("/api/runs", json=payload, headers=bad_origin).status_code == 403
    assert client.post("/api/runs", json=payload, headers={"Origin": BASE}).status_code == 403


def test_security_headers(client):
    response = client.get("/")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("path", [
    "/api/runs/..%2F..%2Fetc", "/api/runs/run-1", "/api/investigations/snapshot:..%2Fsecret",
    "/api/investigations/run:run-20260101-000000-zzzzzzzz", "/api/trust/..%2F..",
    "/api/investigations/snapshot:qwen3-live/..%2F..%2Fexport.csv",
])
def test_paths_cannot_escape_fixed_locations(client, path):
    login(client)
    assert client.get(path).status_code in (404, 405)


def test_static_files_cannot_escape_static_root(client):
    for path in ("/static/../server.py", "/static/..%2F..%2Fpaths.py", "/static/%2e%2e/server.py"):
        response = client.get(path)
        assert response.status_code == 404 or b"create_app" not in response.content


def test_invalid_run_requests_are_rejected_with_codes(client):
    login(client)
    response = client.post("/api/runs", json={"scenario_id": "transmission-after-rejection",
                                              "mode": "live", "protocol": "http"}, headers=ORIGIN)
    assert response.status_code == 422
    assert "MODE_NOT_SUPPORTED_FOR_SCENARIO" in response.json()["codes"]
    response = client.post("/api/runs", content=b"{not json", headers={**ORIGIN, "Content-Type": "application/json"})
    assert response.status_code in (400, 422)


def test_unavailable_mode_is_refused(client, monkeypatch):
    login(client)
    blocked = {"items": [], "modes": {**READY["modes"], "live": {"ready": False, "blocking": ["ollama"]}}}
    monkeypatch.setattr(readiness, "check", lambda: blocked)
    response = client.post("/api/runs", json={"scenario_id": "routine-submission", "mode": "live",
                                              "protocol": "http"}, headers=ORIGIN)
    assert response.status_code == 503 and response.json()["blocking"] == ["ollama"]


def test_concurrent_runs_are_rejected_and_cancel_stops_the_run(client, manager):
    login(client)
    payload = {"scenario_id": "routine-submission", "mode": "lab", "protocol": "http"}
    first = client.post("/api/runs", json=payload, headers=ORIGIN)
    assert first.status_code == 202
    run_id = first.json()["run_id"]
    assert client.post("/api/runs", json=payload, headers=ORIGIN).status_code == 409
    assert client.post(f"/api/runs/{run_id}/cancel", headers=ORIGIN).status_code == 200
    deadline = time.time() + 20
    while client.get(f"/api/runs/{run_id}").json()["status"] == "running" and time.time() < deadline:
        time.sleep(0.2)
    record = client.get(f"/api/runs/{run_id}").json()
    assert record["status"] == "cancelled" and record["error"] == "CANCELLED_BY_USER"
    assert manager.active is None
    # A cancelled run has no evidence and is not offered as an investigation.
    assert client.get(f"/api/investigations/run:{run_id}").status_code == 404


def test_runner_output_is_sanitized(tmp_path):
    secret = REGISTRY.items[0].value
    lines = [
        {"xs_stage": "environment", "status": "complete", "detail": "<script>alert(1)</script>"},
        {"xs_stage": "gateway", "status": "complete", "detail": "ok", "facts": {"decision": secret}},
        {"xs_stage": "not-a-stage", "status": "complete", "detail": "x"},
        {"xs_stage": "drain", "status": "complete", "detail": "ok", "facts": ["not", "a", "dict"]},
        ["not", "an", "object"],
        {"xs_stage": "verification", "status": "complete", "detail": "fine",
         "facts": {"result": "MATCH", "path": "C:/secret", "labels": ["<b>"]}},
    ]
    script = "import json,sys\nsys.stdin.read()\n" + "".join(
        f"print(json.dumps({line!r}))\n" for line in lines) + "print('not json')\nsys.exit(1)\n"
    manager = RunManager(runs=tmp_path / "runs", command=[sys.executable, "-c", script])
    record = manager.start(RunRequest.model_validate(
        {"scenario_id": "routine-submission", "mode": "lab", "protocol": "http"}))
    deadline = time.time() + 15
    while manager.active is not None and time.time() < deadline:
        time.sleep(0.1)
    stored = manager.get(record["run_id"])
    text = json.dumps(stored)
    assert secret not in text and "<script>" not in text and "C:/secret" not in text
    stages = {s["id"]: s for s in stored["stages"]}
    assert stages["environment"]["detail"] == "DETAIL_WITHHELD"
    assert stages["gateway"]["detail"] == "DETAIL_WITHHELD" and stages["gateway"]["facts"] == {}
    assert stages["verification"]["facts"] == {"result": "MATCH"}
    assert stored["status"] == "failed"


def test_interrupted_runs_are_marked_on_restart(tmp_path):
    first = RunManager(runs=tmp_path / "runs", command=sleeper(60))
    record = first.start(RUN)
    first.active["process"].kill()
    # Let the first manager finish its own record, then simulate a service that died while
    # the run was still marked running: its OS lock is gone with it.
    deadline = time.time() + 15
    while first.active is not None and time.time() < deadline:
        time.sleep(0.05)
    assert first.active is None
    path = tmp_path / "runs" / record["run_id"] / "lifecycle.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "running"
    path.write_text(json.dumps(data), encoding="utf-8")
    first.ownership.release()
    second = RunManager(runs=tmp_path / "runs", command=sleeper())
    assert second.owner
    second.recover()
    assert second.get(record["run_id"])["status"] == "interrupted"
    second.shutdown()


def test_second_manager_cannot_touch_a_live_owners_runs(tmp_path):
    first = RunManager(runs=tmp_path / "runs", command=sleeper(30))
    record = first.start(RUN)
    second = RunManager(runs=tmp_path / "runs", command=sleeper())
    assert first.owner and not second.owner
    second.recover()
    assert second.get(record["run_id"])["status"] == "running"
    with pytest.raises(NotOwner):
        second.start(RUN)
    first.shutdown()  # cancels its run and releases the claim
    assert first.get(record["run_id"])["status"] == "cancelled"
    third = RunManager(runs=tmp_path / "runs", command=sleeper())
    assert third.owner
    third.shutdown()
    second.shutdown()


def test_supervision_failure_releases_the_service(tmp_path, monkeypatch):
    from webapp import runs as runs_module

    manager = RunManager(runs=tmp_path / "runs",
                         command=[sys.executable, "-c", "import sys; sys.stdin.read()"])
    calls = {"n": 0}
    real_write = runs_module.write_json

    def failing_write(path, data):
        # Let the initial record through, then fail every later write, including the final one.
        calls["n"] += 1
        if calls["n"] > 1:
            raise PermissionError("simulated persistent sharing violation")
        real_write(path, data)

    monkeypatch.setattr(runs_module, "write_json", failing_write)
    monkeypatch.setattr(runs_module, "load_run_snapshot",
                        lambda _: (_ for _ in ()).throw(TypeError("malformed manifest")))
    record = manager.start(RUN)
    deadline = time.time() + 15
    while manager.active is not None and time.time() < deadline:
        time.sleep(0.05)
    assert manager.active is None, "the service must accept new runs after a failure"
    final = manager.get(record["run_id"])
    assert final["status"] == "failed" and final["error"] in ("SUPERVISION_ERROR",
                                                             "EXPORT_REJECTED_BY_LOADER")
    assert all(s["status"] != "running" for s in final["stages"])
    monkeypatch.setattr(runs_module, "write_json", real_write)
    assert manager.start(RUN)["status"] == "running"
    manager.shutdown()


def test_responses_carrying_registered_values_are_withheld(client, monkeypatch):
    login(client)
    monkeypatch.setattr(research, "records", lambda: {"leak": REGISTRY.items[1].value})
    response = client.get("/api/research")
    assert response.status_code == 500 and response.json() == {"error": "RESPONSE_WITHHELD"}


# ---- evidence views ---------------------------------------------------------------------

def test_committed_snapshots_are_served_without_protected_values(client):
    login(client)
    collections = client.get("/api/investigations").json()["collections"]
    assert {c["id"] for c in collections} >= {"snapshot:qwen3-live", "snapshot:engineering-faults"}
    for identifier in ("snapshot:qwen3-live", "snapshot:engineering-faults"):
        response = client.get(f"/api/investigations/{identifier}")
        assert response.status_code == 200 and not REGISTRY.contains(response.text)
        data = response.json()
        assert data["summary"]["total"] == len(data["incidents"])
        csv = client.get(f"/api/investigations/{identifier}/export.csv")
        assert csv.status_code == 200 and not REGISTRY.contains(csv.text)


def test_incident_view_keeps_dashboard_interpretation():
    catalog, issues = load_catalog(SNAPSHOTS)
    assert not issues
    for bundle in catalog.values():
        for incident in bundle.incidents:
            view = incident_view(incident)
            if view["scoped_absence"]:
                assert view["runtime"]["decision"] == "BLOCK" and view["verification"]["result"] == "MATCH"
            if view["verification"]["result"] == "UNVERIFIED":
                assert all(v == "Unavailable" for v in view["comparison"].values()) or view["observation"]
            assert view["limits"], "every incident states what it does not prove"


def _export(tmp_path, record, **changes):
    from webapp.export import digest

    snapshot = {"schema_version": "platform-run-1.0", "run_id": record["run_id"],
                "scenario_id": "unexpected-destination", "mode": "lab", "protocol": record["protocol"],
                "claim_mode": "plausible", "source_hashes": {"results.csv": "0" * 64},
                "incidents": [record], **changes}
    export = tmp_path / "export"
    export.mkdir(exist_ok=True)
    data = json.dumps(snapshot).encode()
    (export / "snapshot.json").write_bytes(data)
    (export / "manifest.json").write_text(json.dumps(
        {"schema_version": "platform-run-1.0", "files": {"snapshot.json": digest(data)}}))
    return export


def _fault_record():
    catalog, _ = load_catalog(SNAPSHOTS)
    incident = next(i for i in catalog["engineering-faults"].incidents
                    if i.scenario == "destination_divergence")
    return json.loads(incident.model_dump_json())


def test_run_snapshot_loader_checks_hash_and_schema(tmp_path):
    record = _fault_record()
    export = _export(tmp_path, record)
    assert load_run_snapshot(export).incidents[0].verification.result == "MISMATCH"
    (export / "snapshot.json").write_bytes((export / "snapshot.json").read_bytes() + b" ")
    with pytest.raises(ValueError):
        load_run_snapshot(export)


def test_run_snapshot_rejects_contradictory_evidence(tmp_path):
    record = _fault_record()
    record["verification"]["result"] = "MATCH"
    record["verification"]["labels"] = []
    with pytest.raises(ValueError):
        load_run_snapshot(_export(tmp_path, record))
    record = _fault_record()
    record["observation_withheld"] = True  # a withheld observation may never be shown restored
    second = tmp_path / "second"
    second.mkdir()
    with pytest.raises(ValueError):
        load_run_snapshot(_export(second, record))


def test_run_snapshot_rejects_extra_published_files(tmp_path):
    export = _export(tmp_path, _fault_record())
    manifest = json.loads((export / "manifest.json").read_text())
    manifest["files"]["hmac.key"] = "0" * 64
    (export / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        load_run_snapshot(export)


# ---- readiness --------------------------------------------------------------------------

def test_missing_ollama_disables_only_live_mode(monkeypatch):
    monkeypatch.setattr(readiness, "OLLAMA", "http://127.0.0.1:9")
    state = readiness.check()
    ollama = next(i for i in state["items"] if i["id"] == "ollama")
    assert ollama["state"] == "missing"
    assert state["modes"]["live"]["ready"] is False and "ollama" in state["modes"]["live"]["blocking"]
    assert "ollama" not in state["modes"]["lab"]["blocking"]
    assert set(state["modes"]) == {"lab", "stub", "live", "trust"}
    assert state["modes"]["trust"]["blocking"] == state["modes"]["lab"]["blocking"]


def test_missing_agent_environment_disables_agent_modes(monkeypatch, tmp_path):
    monkeypatch.setenv("EXFILSCOPE_AGENT_PYTHON", str(tmp_path / "missing.exe"))
    state = readiness.check()
    assert not state["modes"]["stub"]["ready"] and not state["modes"]["live"]["ready"]


# ---- research figures and static UI contract -------------------------------------------

def test_research_figures_match_committed_documents():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    e1 = research.EXPERIMENT_1
    assert f"{e1['primary']['denominator']} primary cases: 18 MATCH, 18 MISMATCH, 6 UNVERIFIED" in readme
    assert "6 supplementary cases: 6 MISMATCH" in readme and e1["run_id"] in readme
    assert "24/24 conditions" in readme and research.DIAGNOSTICS["run_id"] in readme
    assert "180/180 valid pairs" in readme and "22.1–25.6 ms" in readme
    assert "360 measured requests + 120 warm-ups" in readme
    assert sum(c["cases"] for c in e1["classes"]) == e1["primary"]["denominator"]
    assert sum(e1["primary"]["outcomes"].values()) == e1["primary"]["denominator"]


def test_static_ui_loads_nothing_external_and_resolves_imports():
    files = [p for p in STATIC.rglob("*") if p.is_file() and p.suffix in (".js", ".css", ".html")]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "googleapis" not in text and "gstatic" not in text
        assert not re.search(r"""(src|href)=["']https?://""", text), path
        assert "innerHTML" not in text and "insertAdjacentHTML" not in text and "eval(" not in text, path
        for target in re.findall(r"""from\s+["'](\.{1,2}/[^"']+)["']""", text):
            assert (path.parent / target).resolve().is_file(), (path, target)


def test_learning_center_has_twenty_guides_and_verbatim_fas_questions():
    content = (STATIC / "js/content.js").read_text(encoding="utf-8")
    guides = content[content.index("export const GUIDES"):content.index("export const GUIDE_BY_ID")]
    assert len(re.findall(r'^  \{ id: "', guides, re.M)) == 20
    for question in QUESTIONS:
        assert json.dumps(question) in content


def test_bundled_fonts_are_served_locally_with_licences(client):
    css = client.get("/fonts.css").text
    fonts = STATIC / "fonts"
    for name in ("InterVariable.woff2", "JetBrainsMono-Regular.woff2",
                 "JetBrainsMono-Medium.woff2", "JetBrainsMono-SemiBold.woff2"):
        assert f'url("/static/fonts/{name}")' in css
        assert (fonts / name).read_bytes()[:4] == b"wOF2"
        assert client.get(f"/static/fonts/{name}").status_code == 200
    for licence in ("Inter-OFL.txt", "JetBrainsMono-OFL.txt"):
        assert "SIL Open Font License" in (fonts / licence).read_text(encoding="utf-8")
    assert "http" not in css


def test_service_binds_loopback_only():
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in source and "0.0.0.0" not in source


def test_payload_subtypes_have_distinct_titles_and_trust_origin_is_labelled():
    catalog, _ = load_catalog(SNAPSHOTS)
    payload = [i for i in catalog["engineering-faults"].incidents
               if i.scenario == "payload_divergence"]
    assert {incident_view(i)["scenario_title"] for i in payload} == {
        "Payload divergence: original body restored after redaction"}  # both are REDACT here
    from types import SimpleNamespace

    allow = SimpleNamespace(scenario="payload_divergence", runtime=SimpleNamespace(decision="ALLOW"))
    assert title(allow) == "Payload divergence: body altered after approval"
    view = incident_view(payload[0], "Government Trust extension")
    assert view["display_origin"] == "Government Trust extension"
    assert view["origin"] == payload[0].origin  # the snapshot's own field is unchanged


def test_privacy_results_lead_with_the_accepted_campaign_and_keep_the_failure():
    records = research.records()["privacy"]
    assert records["latest"]["campaign"].startswith("673cac8b")
    assert records["latest"]["status"] == "CORRECTED_FINAL_LIVE_VERIFIED"
    history = records["history"]
    assert history[0]["campaign"] == "final-live-20261031" and history[0]["status"] == "FAILED"
    assert "command" in history[0]["summary"] and "stdin" in history[1]["summary"]


def test_fas_workstation_figures_match_the_custody_record():
    name = "artifacts/fas-packaging-custody-ab166c9.json"
    custody = next((r / name for r in (ROOT, env_root()) if (r / name).is_file()), ROOT / name)
    if not custody.is_file():
        pytest.skip("custodian workstation record not present in this checkout")
    record = json.loads(custody.read_text(encoding="utf-8"))
    rows = {r["label"]: r for r in research.FAS["workstation"]}
    packages = rows["Final custodian packages from run e1-c2292f76f71a"]
    assert record["status"] == "VALIDATED_CUSTODIAN_ONLY" and record["package_count"] == 48
    assert packages["value"] == "48" and record["final_run"] == "e1-c2292f76f71a"
    assert record["formal_successor_approval_complete"] is False
    assert record["reviewer_release_authorized"] is False
    assert rows["Independent human responses"]["value"] == "0"


def test_bundled_samples_are_not_recovered_or_listed_as_local_runs(tmp_path, monkeypatch):
    from webapp.public_site import SAMPLES

    sample = next(SAMPLES.iterdir())
    samples = tmp_path / "samples"
    target = samples / sample.name
    import shutil
    shutil.copytree(sample, target)
    lifecycle = target / "lifecycle.json"
    record = json.loads(lifecycle.read_text(encoding="utf-8"))
    record["status"] = "running"
    lifecycle.write_text(json.dumps(record), encoding="utf-8")
    before = lifecycle.read_bytes()
    manager = RunManager(runs=tmp_path / "local", samples=samples)
    monkeypatch.setattr(readiness, "check", lambda: READY)
    try:
        assert manager.is_sample(sample.name)
        manager.recover()
        assert lifecycle.read_bytes() == before
        with TestClient(server.create_app(token=TOKEN, port=8600, manager=manager),
                        base_url=BASE) as client:
            login(client)
            assert client.get("/api/runs").json() == {"runs": []}
            assert client.get("/api/runs/" + sample.name).status_code == 200
    finally:
        manager.shutdown()
