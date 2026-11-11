"""Workspace redesign: demonstration dataset, case index, scenario wording, public replay."""

import hashlib
import json
import re
import time

import pytest

from exfilscope.registry import Registry
from webapp import dataset, public_site
from webapp.evidence import load_run_snapshot
from webapp.paths import ROOT, STATIC
from webapp.scenarios import SCENARIOS, SOURCES

from .test_platform import client, login, manager  # noqa: F401 - shared fixtures

REGISTRY = Registry.load(ROOT / "examples/registry.json")
DATASET = ROOT / "examples/demo_dataset"


# ---- demonstration dataset --------------------------------------------------------------

def test_dataset_manifest_binds_the_unchanged_frozen_inputs():
    manifest = json.loads((DATASET / "document_manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    for entry in manifest["frozen_inputs"]:
        data = (ROOT / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
    assert all(x["intact"] for x in dataset.load()["integrity"])


def test_dataset_records_agree_with_the_corpus_and_registry():
    manifest = json.loads((DATASET / "document_manifest.json").read_text(encoding="utf-8"))
    corpus = {d["id"]: d for d in json.loads(
        (ROOT / "examples/phase2/documents.json").read_text(encoding="utf-8"))}
    registry = {i["protected_id"]: i for i in json.loads(
        (ROOT / "examples/registry.json").read_text(encoding="utf-8"))}
    index = json.loads((DATASET / "protected_registry.json").read_text(encoding="utf-8"))
    assert index["values_included"] is False
    assert {i["protected_id"]: i["source_ref"] for i in index["items"]} == {
        k: v["source_ref"] for k, v in registry.items()}
    for entry in manifest["documents"]:
        record = json.loads((DATASET / entry["file"]).read_text(encoding="utf-8"))
        markers = set(dataset.MARKER.findall(json.dumps(record)))
        assert markers == set(entry["protected_ids"]), entry["file"]
        if entry["corpus_id"]:
            assert corpus[entry["corpus_id"]]["source_ref"] == entry["source_ref"]
        for protected in entry["protected_ids"]:
            assert registry[protected]["source_ref"] == entry["source_ref"]
    referenced = {ref for refs in SOURCES.values() for ref in refs}
    assert referenced <= {e["source_ref"] for e in manifest["documents"]}


def test_dataset_files_and_view_never_contain_registered_values():
    for path in DATASET.rglob("*"):
        if path.is_file():
            assert not REGISTRY.contains(path.read_text(encoding="utf-8")), path
    view = json.dumps(dataset.load())
    assert not REGISTRY.contains(view)
    assert "[[SECRET_001]]" in view  # the frozen excerpt is masked by ID, not dropped


def test_scenario_catalog_is_generated_from_the_scenario_library():
    published = json.loads((DATASET / "scenario_catalog.json").read_text(encoding="utf-8"))
    assert published == dataset.catalog()


def test_dataset_endpoint_requires_a_session_and_is_minimized(client):  # noqa: F811
    assert client.get("/api/dataset").status_code == 401
    login(client)
    data = client.get("/api/dataset").json()
    assert len(data["documents"]) == 6 and not REGISTRY.contains(json.dumps(data))


# ---- scenario wording -------------------------------------------------------------------

def test_scenario_titles_describe_situations_not_outcomes():
    outcome = re.compile(r"\b(ALLOW|REDACT|BLOCK|MATCH|MISMATCH|UNVERIFIED)\b", re.I)
    for scenario in SCENARIOS:
        assert not outcome.search(scenario.title), scenario.title
        assert not outcome.search(scenario.story), scenario.story


# ---- case index -------------------------------------------------------------------------

def test_case_index_keeps_collections_and_lists_runs_without_evidence(client, manager):  # noqa: F811
    login(client)
    run = manager.runs / "run-20261101-000000-0000abcd"
    run.mkdir(parents=True)
    (run / "lifecycle.json").write_text(json.dumps({
        "schema_version": "platform-lifecycle-1.0", "run_id": run.name,
        "scenario_id": "routine-submission", "scenario_title": "Routine service status submission",
        "mode": "lab", "protocol": "http", "protected_item": None, "claim_mode": "plausible",
        "origin": "Deterministic replay", "status": "failed", "created": time.time(),
        "finished": time.time(), "exit_code": 1, "error": "RUNNER_FAILED",
        "timeout_seconds": 180, "stages": [], "history": []}))
    index = client.get("/api/cases").json()
    assert [r["run_id"] for r in index["incomplete"]] == [run.name]
    assert all(c["run_id"] != run.name for c in index["cases"])
    assert {c["collection"] for c in index["cases"]} == {
        "snapshot:qwen3-live", "snapshot:engineering-faults"}
    assert {c["type"] for c in index["cases"]} <= set(index["types"])
    live = [c for c in index["cases"] if c["collection"] == "snapshot:qwen3-live"]
    assert live and {c["type"] for c in live} == {"live"}
    situations = {c["scenario_id"] for c in index["cases"]}
    assert "redaction-reversed" in situations and None not in situations


# ---- public read-only replay ------------------------------------------------------------

def test_public_samples_hold_only_validated_minimized_exports():
    samples = [p for p in public_site.SAMPLES.iterdir() if p.is_dir()]
    assert samples
    for sample in samples:
        files = {p.relative_to(sample).as_posix() for p in sample.rglob("*") if p.is_file()}
        assert files <= {"lifecycle.json", "export/manifest.json", "export/snapshot.json",
                         "export/trust-audit.json"}, files
        record = json.loads((sample / "lifecycle.json").read_text(encoding="utf-8"))
        assert record["status"] == "succeeded" and "owner_pid" not in record
        load_run_snapshot(sample / "export")
        for path in sample.rglob("*"):
            if path.is_file():
                assert not REGISTRY.contains(path.read_text(encoding="utf-8"))


def test_public_site_build_is_static_complete_and_private(tmp_path):
    out = tmp_path / "site"
    files = set(public_site.build(out))
    index = (out / "index.html").read_text(encoding="utf-8")
    assert '<meta name="exfilscope-mode" content="public">' in index
    assert 'href="static/css/app.css"' in index and 'src="static/js/app.js"' in index
    for required in ("data/scenarios.json", "data/research.json", "data/dataset.json",
                     "data/cases.json", "data/investigations.json", "fonts.css", "icons.json",
                     "data/investigations/snapshot_qwen3-live.json",
                     "data/export/snapshot_engineering-faults.csv"):
        assert required in files, required
    assert not any(p.startswith("data/runs") or p.startswith("data/status") for p in files)
    notices = (out / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
    assert "ISC License" in notices and "SIL Open Font License" in notices
    assert {"static/fonts/Inter-OFL.txt", "static/fonts/JetBrainsMono-OFL.txt"} <= files
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".csv", ".html", ".js", ".css"):
            assert not REGISTRY.contains(path.read_text(encoding="utf-8")), path
    with pytest.raises(FileExistsError):
        public_site.build(out)


def test_public_paths_match_the_browser_mapping():
    api = (STATIC / "js/api.js").read_text(encoding="utf-8")
    assert 'replace(/^\\/api\\//, "data/").replace(/:/g, "_")' in api
    assert public_site.public_path("/api/investigations/run:run-20261101-103227-3187cdae") == \
        "investigations/run_run-20261101-103227-3187cdae.json"


def test_navigation_has_five_workspaces_and_keeps_run_links():
    app = (STATIC / "js/app.js").read_text(encoding="utf-8")
    nav = app[app.index("const WORKSPACES"):app.index("];", app.index("const WORKSPACES"))]
    assert re.findall(r'\["(\w+)", "', nav) == ["overview", "lab", "investigate", "research",
                                                "learn"]
    assert "run: [\"lab\"" in app  # #/run/<id> deep links open inside the Scenario Lab
    assert not (STATIC / "js/views/execution.js").exists()
