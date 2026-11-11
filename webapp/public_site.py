"""Build the public, read-only ExfilScope site: ``python -m webapp.public_site <new-folder>``.

The site is the same browser interface with every read-only API answer precomputed, so it
can be served by any static host (for example GitHub Pages) without Python, Ollama or
mitmproxy. Answers come from the real service code reading only committed material: the
engineering snapshots in ``dashboard/data``, the demonstration dataset and the reviewed
sample runs in ``webapp/public_samples`` (validated exports, never ledgers, keys or
restricted files). Nothing on the site can start a run. Every written file is checked
against the protected-value registry, and the build refuses an existing output folder.
"""

import json
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
import tempfile

from fastapi.testclient import TestClient

from exfilscope.registry import ProtectedItem, Registry

from . import server
from .paths import ROOT
from .runs import RunManager

SAMPLES = Path(__file__).resolve().parent / "public_samples"
BASE = "http://127.0.0.1:8600"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'none'")

# Static assets the site may copy, by type; anything else under webapp/static stops the build.
STATIC_PREFIX = "webapp/static/"
SAMPLES_PREFIX = "webapp/public_samples/"
ASSET_SUFFIXES = (".js", ".css", ".svg", ".woff2", ".txt")
TEMPLATES = {"index.html", "fonts/README.md"}  # read and transformed or quoted, never copied
UNSAFE_NAME = re.compile(r"\.(key|pem|crt|cer|der|csr|p12|pfx|jks|kdbx|sqlite\d*|db|env|log|har|"
                         r"mitm|zip|7z|tar|gz|bak|tmp)$|(^|/)\.", re.IGNORECASE)


class UnsafePublicInput(RuntimeError):
    """A file the public build must not publish, or cannot vouch for, was found."""


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def _safe(relative: str) -> str:
    parts = PurePosixPath(relative).parts
    if not relative or relative.startswith("/") or ".." in parts or "\\" in relative or ":" in relative:
        raise UnsafePublicInput(f"UNSAFE_PATH {relative}")
    return relative


def committed_files(root: Path, commit: str, prefix: str) -> dict[str, bytes]:
    """Regular files under ``prefix`` at ``commit``, read from Git objects, keyed by path
    relative to the prefix. Symlinks, submodules and unsafe paths are refused."""
    files = {}
    for entry in _git(root, "ls-tree", "-r", "-z", "--full-tree", commit, "--", prefix).split(b"\0"):
        if not entry:
            continue
        meta, path = entry.decode("utf-8").split("\t", 1)
        mode, kind, sha = meta.split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise UnsafePublicInput(f"UNSAFE_ENTRY {mode} {path}")
        files[_safe(path[len(prefix):])] = _git(root, "cat-file", "blob", sha)
    return files


def working_files(root: Path, prefix: str) -> dict[str, bytes]:
    """Every file under ``prefix`` in the working tree, ignored ones included; links refused."""
    base, files = root / prefix, {}
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if path.is_symlink():
            raise UnsafePublicInput(f"SYMLINK {path.relative_to(root).as_posix()}")
        if path.is_file():
            files[_safe(path.relative_to(base).as_posix())] = path.read_bytes()
    return files


def static_assets(root: Path = ROOT, commit: str | None = None) -> dict[str, bytes]:
    """The approved static files. With ``commit`` they come from that commit, and any file in
    the working tree that the commit does not hold (untracked, ignored or changed) stops the
    build; without it the working tree is used. Either way only the allowlisted types are
    accepted."""
    if commit:
        files = committed_files(root, commit, STATIC_PREFIX)
        present = working_files(root, STATIC_PREFIX)
        extra = sorted(set(present) - set(files))
        changed = sorted(p for p in set(present) & set(files) if present[p] != files[p])
        if extra or changed:
            raise UnsafePublicInput(f"STATIC_TREE_NOT_COMMITTED untracked={extra} changed={changed}")
    else:
        files = working_files(root, STATIC_PREFIX)
    for relative, data in files.items():
        if relative in TEMPLATES or relative in ("government-data.json", "gdrfa-statistics.json"):
            continue
        if UNSAFE_NAME.search(relative) or not relative.endswith(ASSET_SUFFIXES):
            raise UnsafePublicInput(f"UNEXPECTED_STATIC_FILE {relative}")
        if relative.endswith(".woff2") and not data.startswith(b"wOF2"):
            raise UnsafePublicInput(f"NOT_A_WOFF2_FONT {relative}")
    missing = TEMPLATES - set(files)
    if missing:
        raise UnsafePublicInput(f"MISSING_TEMPLATE {sorted(missing)}")
    return files


def committed_text(root: Path, commit: str | None, path: str) -> str:
    data = _git(root, "show", f"{commit}:{path}") if commit else (root / path).read_bytes()
    return data.decode("utf-8")


def public_path(api: str) -> str:
    """Mirror of publicPath() in static/js/api.js."""
    return api.removeprefix("/api/").replace(":", "_") + ".json"


def stage_samples(runs: Path) -> list[str]:
    """Copy each sample's lifecycle record and validated export into a scratch runs folder."""
    names = []
    for sample in sorted(p for p in SAMPLES.iterdir() if p.is_dir()) if SAMPLES.is_dir() else []:
        target = runs / sample.name
        target.mkdir(parents=True)
        shutil.copy2(sample / "lifecycle.json", target / "lifecycle.json")
        shutil.copytree(sample / "export", target / "export")
        names.append(sample.name)
    return names


def build(out: Path, commit: str | None = None, root: Path = ROOT) -> list[str]:
    """Build into ``out``. ``commit`` (used by scripts/build_submission.py) takes the static
    assets, notices and registry from that commit and refuses anything the commit does not
    hold; without it the working tree is used under the same type allowlist."""
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"{out} is not empty; choose a new folder")
    assets = static_assets(root, commit)
    if commit:
        sample_files = working_files(root, SAMPLES_PREFIX)
        extra = sorted(set(sample_files) - set(committed_files(root, commit, SAMPLES_PREFIX)))
        if extra:
            raise UnsafePublicInput(f"UNTRACKED_SAMPLE_FILES {extra}")
    registry = Registry([ProtectedItem.model_validate(i) for i in
                         json.loads(committed_text(root, commit, "examples/registry.json"))])
    written: list[str] = []

    def write(relative: str, data: bytes, binary: bool = False) -> None:
        if not binary and registry.contains(data.decode("utf-8")):
            raise RuntimeError(f"PROTECTED_VALUE_IN_PUBLIC_FILE {relative}")
        target = out / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(relative)

    with tempfile.TemporaryDirectory() as scratch:
        runs = Path(scratch) / "runs"
        runs.mkdir()
        samples = stage_samples(runs)
        token = secrets.token_urlsafe(32)
        manager = RunManager(runs=runs, command=["unused"])
        app = server.create_app(token=token, port=8600, manager=manager)
        try:
            with TestClient(app, base_url=BASE) as client:
                client.post("/api/session", json={"token": token},
                            headers={"Origin": BASE, "X-ExfilScope": "1"}).raise_for_status()

                def fetch(api: str) -> dict:
                    response = client.get(api)
                    response.raise_for_status()
                    write("data/" + public_path(api), response.content)
                    return response.json()

                fetch("/api/scenarios")
                fetch("/api/research")
                fetch("/api/dataset")
                fetch("/api/government-data")
                cases = fetch("/api/cases")
                for collection in fetch("/api/investigations")["collections"]:
                    identifier = collection["id"]
                    fetch(f"/api/investigations/{identifier}")
                    csv = client.get(f"/api/investigations/{identifier}/export.csv")
                    csv.raise_for_status()
                    write(f"data/export/{identifier.replace(':', '_')}.csv", csv.content)
                for name in samples:
                    if json.loads((runs / name / "lifecycle.json").read_text())["mode"] == "trust":
                        fetch(f"/api/trust/{name}")
                if cases["incomplete"]:
                    raise RuntimeError("PUBLIC_SAMPLE_WITHOUT_VALIDATED_EXPORT")
        finally:
            manager.shutdown()

    for relative, data in sorted(assets.items()):
        if relative not in TEMPLATES:
            write("static/" + relative, data, binary=relative.endswith(".woff2"))
    index = assets["index.html"].decode("utf-8").replace(
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '  <meta name="exfilscope-mode" content="public">\n'
        f'  <meta http-equiv="Content-Security-Policy" content="{CSP}">')
    write("index.html", index.encode("utf-8"))
    fonts = []
    for family, name, weight in server.FONTS:
        sources = [f'local("{family}")']
        if f"fonts/{name}" in assets:
            sources.insert(0, f'url("static/fonts/{name}") format("woff2")')
        fonts.append(f'@font-face {{ font-family: "{family}"; font-style: normal; '
                     f'font-weight: {weight}; font-display: swap; src: {", ".join(sources)}; }}')
    write("fonts.css", "\n".join(fonts).encode("utf-8"))
    write("icons.json", json.dumps(server.ICONS).encode("utf-8"))
    write(".nojekyll", b"")
    # Licence notices for what the site redistributes: Lucide path data in icons.json (ISC)
    # and the bundled fonts (their OFL texts are copied beside the font files above).
    notices = committed_text(root, commit, "dashboard/THIRD_PARTY_NOTICES.md").rstrip()
    sources = assets["fonts/README.md"].decode("utf-8")
    write("THIRD-PARTY-NOTICES.md", f"{notices}\n\n## Font sources\n\n{sources}".encode("utf-8"))
    write("PUBLIC-SITE.txt", (
        "ExfilScope public read-only replay. Built by python -m webapp.public_site.\n"
        "Every case shown here was recorded earlier in a local laboratory with synthetic data.\n"
        "Nothing on this site executes the agent, gateway, proxy or verifier.\n"
        "Third-party licences: THIRD-PARTY-NOTICES.md and static/fonts/*-OFL.txt.\n").encode("utf-8"))
    return written


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m webapp.public_site <new-output-folder>")
        return 2
    out = Path(sys.argv[1]).resolve()
    files = build(out)
    print(f"Wrote {len(files)} files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
