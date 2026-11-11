"""Read-only demonstration dataset for the Scenario Lab's data explorer.

``examples/demo_dataset`` holds presentation records and indexes. The agent still retrieves
from the frozen corpus ``examples/phase2/documents.json``; this module only reads it, checks
it against the hashes in the manifest and masks every registered value by its ID before
anything is returned. ``python -m webapp.dataset`` rewrites ``scenario_catalog.json``.
"""

import hashlib
import json
from pathlib import Path
import re
import sys

from .paths import ROOT
from .scenarios import GROUPS, SCENARIOS, SOURCES, group

DATASET = ROOT / "examples" / "demo_dataset"
MARKER = re.compile(r"\[\[(SECRET_[0-9]{3})\]\]")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry_items() -> list[dict]:
    return json.loads((ROOT / "examples/registry.json").read_text(encoding="utf-8"))


def mask(text: str, items: list[dict]) -> str:
    """Replace each registered value with its marker, as the presentation records do."""
    for item in items:
        text = text.replace(item["value"], f"[[{item['protected_id']}]]")
    return text


def catalog() -> dict:
    """Scenario catalog as published in the dataset folder, derived from webapp.scenarios."""
    return {"schema_version": "demo-scenario-catalog-1.0",
            "generated_from": "webapp/scenarios.py",
            "groups": [{"id": g, "title": t, "note": n} for g, t, n in GROUPS],
            "scenarios": [{"id": s.id, "number": s.number, "title": s.title, "group": group(s),
                           "engine": s.lab_scenario, "agent_task": s.live_case,
                           "sources": list(SOURCES[s.id])} for s in SCENARIOS]}


def load() -> dict:
    manifest = json.loads((DATASET / "document_manifest.json").read_text(encoding="utf-8"))
    index = json.loads((DATASET / "protected_registry.json").read_text(encoding="utf-8"))
    integrity = [{"path": f["path"], "role": f["role"],
                  "intact": (ROOT / f["path"]).is_file() and _hash(ROOT / f["path"]) == f["sha256"]}
                 for f in manifest["frozen_inputs"]]
    items = _registry_items()
    corpus = {d["id"]: d for d in
              json.loads((ROOT / "examples/phase2/documents.json").read_text(encoding="utf-8"))}
    used_by = {}
    for s in SCENARIOS:
        for ref in SOURCES[s.id]:
            used_by.setdefault(ref, []).append({"id": s.id, "number": s.number, "title": s.title})
    documents = []
    for entry in manifest["documents"]:
        record = json.loads((DATASET / entry["file"]).read_text(encoding="utf-8"))
        chunk = corpus.get(entry["corpus_id"]) if entry["corpus_id"] else None
        documents.append({**record, "file": f"examples/demo_dataset/{entry['file']}",
                          "source_ref": entry["source_ref"], "role": entry["role"],
                          "protected_ids": entry["protected_ids"],
                          "corpus_excerpt": mask(chunk["text"], items) if chunk else None,
                          "used_by": used_by.get(entry["source_ref"], [])})
    return {"dataset_version": manifest["dataset_version"], "notice": manifest["notice"],
            "integrity": integrity,
            "protected": [{k: i[k] for k in ("protected_id", "data_type", "category",
                                             "source_ref")} for i in index["items"]],
            "documents": documents,
            "no_document": [{"id": s.id, "number": s.number, "title": s.title}
                            for s in SCENARIOS if not SOURCES[s.id]]}


def main() -> int:
    path = DATASET / "scenario_catalog.json"
    path.write_text(json.dumps(catalog(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
