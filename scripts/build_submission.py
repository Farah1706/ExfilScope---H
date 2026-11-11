"""Build the university submission distributions from one commit (see docs/SUBMISSION.md).

    python scripts/build_submission.py source <new-output-folder> [--commit REV]
    python scripts/build_submission.py public <new-output-folder>

``source`` writes ExfilScope-source-<commit>.zip from an explicit allowlist of Git-tracked
files. File bytes are read from Git at the commit, never from the working tree, so local
edits, environments, models and private evidence cannot enter the archive. The archive holds
SOURCE-COMMIT.txt and MANIFEST.sha256; the archive's own SHA-256 is written beside it.

``public`` builds the static read-only site (webapp.public_site) into ExfilScope-public-<commit>.
It requires a clean working tree; static assets, notices and the registry come from the
commit's Git objects under a type allowlist, and any file under webapp/static that the commit
does not hold (untracked, ignored or changed), a symlink or an unexpected type stops the
build. SHA256SUMS.txt covers every file including SOURCE-COMMIT.txt and is re-verified.

Both refuse an existing output and scan every packaged file for private-key blocks and local
user paths. Registered values are checked with the commit's registry, which must be the
approved one; in the source only the four pinned files may hold them, and the public build
allows none. Run in the core environment from the repository root.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

ALLOW_DIRS = ("dashboard/", "deploy/", "docs/", "e1/", "examples/", "phase2/",
              "readiness/", "scripts/", "src/", "tests/", "webapp/")
ALLOW_FILES = {".dockerignore", ".env.example", ".gitattributes", ".gitignore", "AGENTS.md",
               "Dockerfile", "README.md", "Start-ExfilScope.cmd", "compose.yaml", "pyproject.toml",
               "requirements.lock", "requirements-phase2.in", "requirements-phase2.lock"}
# Never packaged, even if tracked by mistake.
DENY = re.compile(r"(^|/)(\.venv[^/]*|\.python|\.worktrees|artifacts|models|dist|__pycache__|"
                  r"\.idea|\.vscode|\.pytest_cache|\.ruff_cache)/|"
                  r"\.(pem|key|p12|pfx|sqlite[^/]*|db|zip|log|har|mitm|pyc)$|(^|/)\.env$")
# The source must carry the synthetic registry it runs on, so its invalid demonstration values
# appear in a few files by design. That exception is pinned, not granted by filename: the
# registry at the selected commit must be the approved frozen one, and each file allowed to
# hold its values must be byte-identical to the approved version (SHA-256 of the committed
# blob). Any edit to one of them, including an added value or any other content, stops the
# build until this table is deliberately reviewed. Every other file may hold no registered
# value, and the public build allows none anywhere.
REGISTRY_PATH = "examples/registry.json"
APPROVED_REGISTRY_SHA256 = "a5234727438d484ff40231172f50e23501146c8e027b7f20fca51a897c479982"
SYNTHETIC_VALUE_FILES = {
    REGISTRY_PATH: APPROVED_REGISTRY_SHA256,
    "examples/phase2/documents.json": "09a451f5ed943c3a6f3b8655898208d343d3a700a983b12f1baa9474ddebfc5d",
    "src/exfilscope/lab.py": "32f41da90d0803b96417cadc3a1c4d89cd3323ada89edc944c15756fec833a6b",
    "tests/test_policy.py": "476b196fde19211a4b338b30d32caa3fb30bff552c81bded8346911d9edb57cd",
}
PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
LOCAL_PATH = re.compile(rb"[A-Za-z]:\\\\?Users\\\\?[A-Za-z]|/Users/[A-Za-z]|/home/[A-Za-z]")


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8").strip()


def load_registry(data: bytes):
    """The registry used for every scan: the selected commit's bytes, only if approved."""
    from exfilscope.registry import ProtectedItem, Registry

    if hashlib.sha256(data).hexdigest() != APPROVED_REGISTRY_SHA256:
        raise SystemExit(f"Refused: {REGISTRY_PATH} at this commit is not the approved registry")
    return Registry([ProtectedItem.model_validate(i) for i in json.loads(data)])


def _content_problems(name: str, data: bytes) -> list[str]:
    problems = []
    if PRIVATE_KEY.search(data):
        problems.append(f"{name}: private-key block")
    if LOCAL_PATH.search(data):
        problems.append(f"{name}: local user path")
    return problems


def _text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None  # fonts and other binaries hold no registered text value


def source_problems(path: str, data: bytes, registry, exempt=SYNTHETIC_VALUE_FILES) -> list[str]:
    problems = _content_problems(path, data)
    if path in exempt:
        if hashlib.sha256(data).hexdigest() != exempt[path]:
            problems.append(f"{path}: differs from the approved synthetic-value file")
        return problems
    text = _text(data)
    if text is not None and registry.contains(text):
        problems.append(f"{path}: registered protected value")
    return problems


def public_problems(path: str, data: bytes, registry) -> list[str]:
    problems = _content_problems(path, data)
    text = _text(data)
    if text is not None and registry.contains(text):
        problems.append(f"{path}: registered protected value")
    return problems


def build_source(out: Path, commit: str) -> dict:
    full = git("rev-parse", "--verify", f"{commit}^{{commit}}")
    short = full[:7]
    tracked = git("ls-tree", "-r", "--name-only", full).splitlines()
    uncovered = [p for p in tracked if not (p in ALLOW_FILES or p.startswith(ALLOW_DIRS))]
    denied = [p for p in tracked if DENY.search(p)]
    if uncovered or denied:
        raise SystemExit(f"Review the allowlist first. Not covered: {uncovered}; denied: {denied}")
    stamp = time.gmtime(int(git("show", "-s", "--format=%ct", full)))[:6]
    registry = load_registry(git("show", f"{full}:{REGISTRY_PATH}", binary=True))
    missing = sorted(set(SYNTHETIC_VALUE_FILES) - set(tracked))
    if missing:
        raise SystemExit(f"Refused: approved synthetic-value files missing at this commit: {missing}")
    problems, manifest = [], []
    top = f"ExfilScope-{short}"
    archive = out / f"ExfilScope-source-{short}.zip"
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(f"{top}/{name}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        for path in tracked:
            data = git("show", f"{full}:{path}", binary=True)
            problems += source_problems(path, data, registry)
            manifest.append(f"{hashlib.sha256(data).hexdigest()}  {path}")
            add(path, data)
        add("SOURCE-COMMIT.txt", (
            f"ExfilScope source package\ncommit {full}\nbranch-independent: files are read from "
            f"this commit with an explicit allowlist (scripts/build_submission.py)\n"
            f"files {len(tracked)}\nsee docs/SUBMISSION.md\n").encode("utf-8"))
        add("MANIFEST.sha256", ("\n".join(manifest) + "\n").encode("utf-8"))
    if problems:
        archive.unlink()
        raise SystemExit("Refused: " + "; ".join(problems))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (out / f"{archive.name}.sha256").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    return {"archive": str(archive), "bytes": archive.stat().st_size, "sha256": digest,
            "commit": full, "files": len(tracked)}


def build_public(out: Path) -> dict:
    if git("status", "--porcelain"):
        raise SystemExit("Commit or stash changes first: the public build must match a commit.")
    from webapp import public_site

    full = git("rev-parse", "HEAD")
    site = out / f"ExfilScope-public-{full[:7]}"
    try:
        # Static assets, notices and registry come from this commit's Git objects; any file
        # under webapp/static that the commit does not hold stops the build.
        public_site.build(site, commit=full, root=ROOT)
    except public_site.UnsafePublicInput as exc:
        raise SystemExit(f"Refused: {exc}") from None
    (site / "SOURCE-COMMIT.txt").write_text(f"ExfilScope public read-only build\ncommit {full}\n",
                                            encoding="utf-8")
    registry = load_registry(git("show", f"{full}:{REGISTRY_PATH}", binary=True))
    problems, sums = [], []
    for path in sorted(p for p in site.rglob("*") if p.is_file()):
        name = path.relative_to(site).as_posix()
        if path.is_symlink():
            problems.append(f"{name}: symlink")
            continue
        data = path.read_bytes()
        problems += public_problems(name, data, registry)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    if problems:
        raise SystemExit("Refused: " + "; ".join(problems))
    (site / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    verify_public(site)
    return {"folder": str(site), "files": len(sums) + 1, "commit": full}


def verify_public(site: Path) -> None:
    """Every file except the manifest itself is listed with a matching SHA-256, and nothing
    else is present."""
    listed = {}
    for line in (site / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        listed[name] = digest
    present = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()} - {"SHA256SUMS.txt"}
    if present != set(listed) or "SOURCE-COMMIT.txt" not in listed:
        raise SystemExit(f"Refused: manifest coverage differs: {sorted(present ^ set(listed))}")
    bad = [n for n, d in listed.items() if hashlib.sha256((site / n).read_bytes()).hexdigest() != d]
    if bad:
        raise SystemExit(f"Refused: checksum mismatch: {bad}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build ExfilScope submission distributions")
    parser.add_argument("kind", choices=("source", "public"))
    parser.add_argument("out", type=Path)
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; choose a new folder")
    out.mkdir(parents=True, exist_ok=True)
    result = build_source(out, args.commit) if args.kind == "source" else build_public(out)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
