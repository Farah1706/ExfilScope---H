"""Scenario Lab regressions run in a real headless Chromium browser.

F1-F3 are the audit findings on pending evidence, Pause and timers. The evidence-state
matrix (release-audit finding N1) feeds real incidents and lifecycle records to the real
stage module and checks that Scenes 5-8 never claim more than the evidence establishes.
The static modules and webapp/tests/js are served from a temporary copy on loopback; the
page replaces fetch for the route test, so no ExfilScope service or network is involved.
Skips when neither Microsoft Edge nor Google Chrome is installed (a skip is not a pass).
"""

import copy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading

import pytest

from dashboard.evidence import load_catalog
from webapp.evidence import load_run_snapshot
from webapp.interpret import incident_view
from webapp.paths import SNAPSHOTS, STATIC
from webapp.public_site import SAMPLES
from webapp.scenarios import SCENARIOS, describe

HERE = Path(__file__).resolve().parent / "js"
FIXTURES = HERE / "fixtures"
# Chrome is preferred: Edge's installed headless build can exit with an empty DOM.
CANDIDATES = [Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
              Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
              Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe"]
BROWSER = next((p for p in CANDIDATES if p.is_file()), None)
# What each case's evidence establishes; keys are checked against Scenes 5-8.
NONE = dict(crossed=False, captionCrossed=False, hmacB=False, scoped=False, noObs=False, labFault=False,
            incomplete=False)


def expect(**overrides):
    return {**NONE, **overrides}


def matrix_cases() -> list[dict]:
    catalog, _ = load_catalog(SNAPSHOTS)

    def snap(name, scenario, decision=None, protocol="https"):
        i = next(x for x in catalog[name].incidents if x.scenario == scenario and x.protocol == protocol
                 and (decision is None or x.runtime.decision == decision))
        return incident_view(i)

    sample = next(p for p in sorted(SAMPLES.iterdir())
                  if json.loads((p / "lifecycle.json").read_text())["scenario_id"] == "modified-after-approval")
    alter = incident_view(load_run_snapshot(sample / "export").incidents[0])
    transport = json.loads((FIXTURES / "transport-failure-incident.json").read_text(encoding="utf-8"))
    lifecycle = json.loads((FIXTURES / "missing-observation-lifecycle.json").read_text(encoding="utf-8"))

    # Derived variants, each labelled: real records with one evidence field changed.
    block = snap("qwen3-live", "block")
    block_gap = copy.deepcopy(block)
    block_gap.update(scoped_absence=False, observation=None, diagnostic_notes=[
        {"code": "MISSING_CLOSING_BARRIER", "text": "The proxy never confirmed that the window was fully recorded."}])
    block_gap["verification"].update(result="UNVERIFIED", evidence_status="UNVERIFIED",
                                     labels=["NO_CORRELATED_OBSERVATION"], diagnostics=["MISSING_CLOSING_BARRIER"])
    paired = copy.deepcopy(lifecycle)
    paired["scenario_id"] = "routine-submission"
    next(s for s in paired["stages"] if s["id"] == "observation")["facts"] = {"paired": True}
    next(s for s in paired["stages"] if s["id"] == "verification")["facts"] = {
        "result": "MATCH", "evidence_status": "VERIFIED", "labels": []}

    return [
        {"name": "ALLOW + EXECUTED_FAILED + UNVERIFIED, no observation (audit N1 fixture)",
         "scenario_id": "routine-submission", "mode": "lab", "data": {"incident": transport},
         "expect": expect(noObs=True, incomplete=True)},
        {"name": "Completed observation stage with paired:false (real lifecycle, no incident yet)",
         "scenario_id": "missing-observation", "mode": "lab", "data": {"record": lifecycle},
         "expect": expect(noObs=True, incomplete=True)},
        {"name": "Live record with paired:true (derived from the real lifecycle)",
         "scenario_id": "routine-submission", "mode": "lab", "data": {"record": paired},
         "expect": expect(crossed=True, captionCrossed=True)},
        {"name": "ALLOW + observed request (Qwen3 snapshot)", "scenario_id": "routine-submission", "mode": "live",
         "data": {"incident": snap("qwen3-live", "allow")}, "expect": expect(crossed=True, captionCrossed=True, hmacB=True)},
        {"name": "REDACT + validated observation (Qwen3 snapshot)", "scenario_id": "confidential-request", "mode": "live",
         "data": {"incident": snap("qwen3-live", "redact")}, "expect": expect(crossed=True, captionCrossed=True, hmacB=True)},
        {"name": "BLOCK + no observed request, complete coverage (Qwen3 snapshot)", "scenario_id": "prohibited-transfer",
         "mode": "live", "data": {"incident": block}, "expect": expect(scoped=True)},
        {"name": "BLOCK + monitoring-health gap, UNVERIFIED (derived from the BLOCK snapshot)",
         "scenario_id": "prohibited-transfer", "mode": "live", "data": {"incident": block_gap},
         "expect": expect(noObs=True, incomplete=True)},
        {"name": "Controlled block bypass, unauthorized traffic observed (fault snapshot)",
         "scenario_id": "transmission-after-rejection", "mode": "lab", "data": {"incident": snap("engineering-faults", "block_bypass")},
         "expect": expect(crossed=True, captionCrossed=True, hmacB=True, labFault=True)},
        {"name": "Payload divergence, original restored after REDACT (fault snapshot)", "scenario_id": "redaction-reversed",
         "mode": "lab", "data": {"incident": snap("engineering-faults", "payload_divergence")},
         "expect": expect(crossed=True, captionCrossed=True, hmacB=True, labFault=True)},
        {"name": "Payload divergence, body altered after ALLOW (public sample run)", "scenario_id": "modified-after-approval",
         "mode": "lab", "data": {"incident": alter}, "expect": expect(crossed=True, captionCrossed=True, hmacB=True, labFault=True)},
        {"name": "Destination divergence (fault snapshot)", "scenario_id": "unexpected-destination", "mode": "lab",
         "data": {"incident": snap("engineering-faults", "destination_divergence")},
         "expect": expect(crossed=True, captionCrossed=True, hmacB=True, labFault=True)},
        {"name": "Observation kept but withheld from the verifier (labelled demonstration)",
         "scenario_id": "missing-observation", "mode": "lab", "data": {"incident": snap("engineering-faults", "no_observation")},
         "expect": expect(crossed=True, captionCrossed=True, incomplete=True)},
        {"name": "Preview of the bypass situation (no evidence yet)", "scenario_id": "transmission-after-rejection",
         "mode": "lab", "data": {}, "expect": expect()},
    ]


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def run_page(root: Path, mutate=None) -> dict:
    """Serve a copy of the static tree plus the test page and return the page's results."""
    shutil.copytree(STATIC, root / "static")
    shutil.copytree(HERE, root / "static/js/__regress__")
    if mutate:
        stage = root / "static/js/views/stage.js"
        stage.write_text(mutate(stage.read_text(encoding="utf-8")), encoding="utf-8")
    (root / "static/js/__regress__/fixtures.json").write_text(json.dumps(
        {"scenarios": [describe(s) for s in SCENARIOS], "cases": matrix_cases()}), encoding="utf-8")
    # Real validated read-only responses, reused in the browser routing regressions.
    from fastapi.testclient import TestClient
    from webapp import server as platform
    from webapp.runs import RunManager

    manager = RunManager(runs=root / "empty-runs", samples=SAMPLES)
    token = "browser-regression-token"
    routes = {}
    try:
        with TestClient(platform.create_app(token=token, port=8600, manager=manager),
                        base_url="http://127.0.0.1:8600") as client:
            client.post("/api/session", json={"token": token}, headers={
                "Origin": "http://127.0.0.1:8600", "X-ExfilScope": "1"}).raise_for_status()
            def capture(url):
                response = client.get(url)
                response.raise_for_status()
                routes[url] = response.json()
                return routes[url]
            for url in ("/api/scenarios", "/api/research", "/api/dataset", "/api/government-data"):
                capture(url)
            for row in capture("/api/cases")["cases"]:
                capture("/api/investigations/" + row["collection"])
                if row["type"] == "trust":
                    capture("/api/trust/" + row["run_id"])
                    capture("/api/runs/" + row["run_id"])
    finally:
        manager.shutdown()
    (root / "static/js/__regress__/routes.json").write_text(json.dumps(routes), encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/static/js/__regress__/regressions.html"
    try:
        dom = subprocess.run(
            [str(BROWSER), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             "--disable-extensions", f"--user-data-dir={root / 'profile'}", "--virtual-time-budget=60000",
             "--dump-dom", url], capture_output=True, text=True, encoding="utf-8", timeout=180).stdout
    finally:
        server.shutdown()
    match = re.search(r'<pre id="result">(.*?)</pre>', dom, re.S)
    assert match and match.group(1) != "PENDING", dom[-2000:]
    return json.loads(match.group(1).replace("&quot;", '"').replace("&amp;", "&")
                      .replace("&lt;", "<").replace("&gt;", ">"))


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    if BROWSER is None:
        pytest.skip("No Edge or Chrome installation for the headless UI regressions")
    return run_page(tmp_path_factory.mktemp("ui"))


def test_f1_no_emission_or_observation_claimed_before_evidence(results):
    assert results["F1"]["pass"], results["F1"]


def test_f2_user_pause_survives_backend_polling(results):
    assert results["F2"]["pass"], results["F2"]


def test_f3_leaving_a_running_case_disposes_its_timers(results):
    assert results["F3"]["pass"], results["F3"]


def test_scenes_never_claim_more_than_the_evidence(results):
    assert results["MATRIX"]["cases"] == len(matrix_cases())
    assert results["MATRIX"]["pass"], results["MATRIX"]["failed"]


def test_matrix_catches_an_observation_inferred_from_a_completed_stage(tmp_path):
    """Mutation: infer a proxy crossing whenever the observation stage is no longer pending
    (the N1 defect). The matrix must fail on the absent-observation cases."""
    if BROWSER is None:
        pytest.skip("No Edge or Chrome installation for the headless UI regressions")
    rule = 'crossed: ["observed", "paired", "withheld"].includes(observation)'

    def reintroduce_n1(source: str) -> str:
        assert rule in source
        return source.replace(rule, 'crossed: observation !== "pending"')

    mutated = run_page(tmp_path, reintroduce_n1)
    failed = {case["name"] for case in mutated["MATRIX"]["failed"]}
    assert not mutated["MATRIX"]["pass"]
    assert "ALLOW + EXECUTED_FAILED + UNVERIFIED, no observation (audit N1 fixture)" in failed
    assert "Completed observation stage with paired:false (real lifecycle, no incident yet)" in failed


def test_all_routes_skip_absent_children_and_trust_results_precede_animation(results):
    assert results["ROUTES"]["pass"], results["ROUTES"]


def test_architecture_trust_controls_work_with_keyboard_and_pointer(results):
    assert results["ARCHITECTURE"]["pass"], results["ARCHITECTURE"]
