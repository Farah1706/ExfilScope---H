"""Build a deterministic private Windows product ZIP from a committed tree."""

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_submission import DENY, REGISTRY_PATH, load_registry, source_problems

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {"README.md", "Launch-Hackathon.cmd", "Launch-Live-Hackathon.cmd", "Start-ExfilScope.cmd", "pyproject.toml",
              ".gitignore", "requirements.lock", "requirements-phase2.lock",
              "SOURCE-COMMIT.txt"}
PREFIXES = ("src/", "phase2/", "webapp/", "dashboard/", "examples/")
CORE_TESTS = {"tests/conftest.py", "tests/test_policy.py", "tests/test_verifier.py",
              "tests/test_health.py", "tests/test_privacy_controls.py", "tests/test_api.py",
              "tests/test_monitor.py", "tests/test_isolation.py", "tests/test_integration.py",
              "tests/test_hardening_integration.py"}
DOCS = {"docs/TECHNICAL.md", "docs/DEPLOYMENT.md", "docs/SETUP.md"}
SCRIPTS = {"scripts/setup.ps1", "scripts/start-exfilscope.ps1", "scripts/launch-hackathon.ps1",
           "scripts/hackathon-environment.ps1", "scripts/serve-hackathon-model.ps1",
           "scripts/benchmark_trust.py", "scripts/refresh_government_data.py", "scripts/refresh_gdrfa_statistics.py", "scripts/build_submission.py", "scripts/package_hackathon.py"}

# Keep the final distribution focused on the current application. Shared evidence
# readers, proxy add-ons and checklist definitions remain part of the product.
RETIRED = {"dashboard/app.py", "dashboard/style.css", "dashboard/tests/test_app.py"}
SHARED_RESEARCH = {"src/exfilscope/research/__init__.py", "src/exfilscope/research/content_addon.py",
                   "src/exfilscope/research/measurement_addon.py", "src/exfilscope/research/fas_review.py"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    archive = args.archive.resolve()
    if ROOT / "dist" not in archive.parents or archive.suffix != ".zip":
        parser.error("Choose a fresh ZIP path under this project's dist directory")
    checksum = archive.with_suffix(".zip.sha256")
    if checksum.exists():
        parser.error("Checksum destination already exists")
    commit = git("rev-parse", "HEAD").decode().strip()
    files = {}
    for item in git("ls-tree", "-rz", commit).split(b"\0"):
        if not item:
            continue
        metadata, raw_path = item.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        name = raw_path.decode()
        if name in RETIRED or (name.startswith("src/exfilscope/research/") and name not in SHARED_RESEARCH):
            continue
        path = PurePosixPath(name)
        if name not in ROOT_FILES | DOCS | SCRIPTS | CORE_TESTS and not name.startswith(PREFIXES):
            continue
        if (mode not in {"100644", "100755"} or kind != "blob" or path.is_absolute()
                or ".." in path.parts or ".git" in path.parts or "\\" in name or ":" in name
                or DENY.search(name)):
            raise ValueError(f"Unsafe package path: {name}")
        files[name] = git("cat-file", "blob", oid)
    required = {"README.md", "Launch-Hackathon.cmd", "Launch-Live-Hackathon.cmd", "docs/TECHNICAL.md", "docs/DEPLOYMENT.md",
                "webapp/trust/dispatch.py"}
    if not required <= files.keys():
        raise ValueError("Commit product files before packaging")
    registry = load_registry(files[REGISTRY_PATH])
    problems = [problem for name, data in files.items()
                for problem in source_problems(name, data, registry)]
    if problems:
        raise ValueError("Package rejected: " + ", ".join(problems))
    files["HACKATHON-COMMIT.txt"] = (commit + "\n").encode()
    files["MANIFEST.sha256"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(files.items())).encode()
    archive.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive, "x", compression=ZIP_DEFLATED, compresslevel=9) as out:
        for name, data in sorted(files.items()):
            info = ZipInfo(name)
            info.external_attr = 0o100644 << 16
            out.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
    with ZipFile(archive) as check:
        if set(check.namelist()) != set(files) or any(
                check.read(name) != data for name, data in files.items()):
            raise ValueError("ZIP verification failed")
    with checksum.open("x", encoding="ascii") as output:
        output.write(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")


if __name__ == "__main__":
    main()
