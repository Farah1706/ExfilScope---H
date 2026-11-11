"""Security regressions for the submission builder (scripts/build_submission.py) and the
public build's static inputs (webapp.public_site): untracked or unexpected files, symlinks,
the pinned synthetic-value exception and the public integrity manifest."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from webapp import public_site
from webapp.paths import ROOT

SPEC = importlib.util.spec_from_file_location("build_submission", ROOT / "scripts/build_submission.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)

CANARY = b"\x00\x01\x02 harmless binary canary, not a key \xff\xfe"


def committed(path: str) -> bytes:
    return subprocess.run(["git", "show", f"HEAD:{path}"], cwd=ROOT, capture_output=True, check=True).stdout


@pytest.fixture(scope="module")
def registry():
    return builder.load_registry(committed(builder.REGISTRY_PATH))


@pytest.fixture(scope="module")
def synthetic_value(registry):
    # Taken from the registry at run time so this file itself holds no registered value.
    return registry.items[0].value.encode("utf-8")


# ---- pinned synthetic-value exception ----------------------------------------------------

def test_approved_synthetic_files_still_pass(registry):
    for path in builder.SYNTHETIC_VALUE_FILES:
        assert builder.source_problems(path, committed(path), registry) == [], path


def test_exempt_filename_cannot_hide_an_added_registered_value(registry, synthetic_value):
    """The 39fa0ea bypass: any content in an exempt filename passed the registered-value scan."""
    path = "tests/test_policy.py"
    tampered = committed(path) + b"\nLEAK = '" + synthetic_value + b"'\n"
    assert builder.source_problems(path, tampered, registry) == [
        f"{path}: differs from the approved synthetic-value file"]


def test_exempt_filename_cannot_hide_an_unregistered_secret(registry):
    path = "examples/phase2/documents.json"
    tampered = committed(path).replace(b"]", b', {"id": "x", "text": "sk-live-0000-not-registered"}]', 1)
    assert builder.source_problems(path, tampered, registry)


def test_registered_value_outside_the_exempt_files_is_refused(registry, synthetic_value):
    for path in ("docs/NOTES.md", "webapp/static/js/app.js", "examples/demo_dataset/README.md"):
        assert builder.source_problems(path, b"key: " + synthetic_value, registry) == [
            f"{path}: registered protected value"]


def test_only_the_approved_registry_is_accepted(synthetic_value):
    data = committed(builder.REGISTRY_PATH)
    items = json.loads(data)
    items.append({**items[0], "protected_id": "SECRET_099", "value": "SYNTHETIC_EXTRA_VALUE_Z99"})
    with pytest.raises(SystemExit, match="not the approved registry"):
        builder.load_registry(json.dumps(items).encode("utf-8"))
    with pytest.raises(SystemExit, match="not the approved registry"):
        builder.load_registry(data.replace(synthetic_value, b"SYNTHETIC_SUBSTITUTE_Q00"))


def test_private_keys_and_local_paths_are_refused_everywhere(registry):
    # Assembled at run time so this file holds no key header or user path the build would refuse.
    marker = b"PRIVATE " + b"KEY-----"
    block = b"-----BEGIN RSA " + marker + b"\nAAAA\n-----END RSA " + marker + b"\n"
    assert builder.source_problems("docs/x.md", block, registry) == ["docs/x.md: private-key block"]
    local = b"C:" + b"\\" + b"Users" + b"\\" + b"someone"
    assert builder.public_problems("data/x.json", local, registry) == ["data/x.json: local user path"]
    exempt = "tests/test_policy.py"
    assert "private-key block" in " ".join(builder.source_problems(exempt, committed(exempt) + block, registry))


def test_public_files_may_hold_no_registered_value(registry, synthetic_value):
    assert builder.public_problems("data/research.json", synthetic_value, registry) == [
        "data/research.json: registered protected value"]


# ---- public static inputs ------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          cwd=repo, capture_output=True, check=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A minimal committed checkout with the static layout the public build expects."""
    root = tmp_path / "repo"
    static = root / "webapp/static"
    for name, data in {"index.html": b"<!doctype html>", "fonts/README.md": b"# Fonts",
                       "fonts/A-OFL.txt": b"SIL Open Font License", "fonts/a.woff2": b"wOF2\x00\x01",
                       "js/app.js": b"export {};", "css/app.css": b"body{}", "img/mark.svg": b"<svg/>"}.items():
        (static / name).parent.mkdir(parents=True, exist_ok=True)
        (static / name).write_bytes(data)
    (root / ".gitignore").write_text("*.key\n")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "static")
    return root


def test_clean_static_tree_is_accepted(repo):
    assets = public_site.static_assets(repo, "HEAD")
    assert set(assets) == {"index.html", "fonts/README.md", "fonts/A-OFL.txt", "fonts/a.woff2",
                           "js/app.js", "css/app.css", "img/mark.svg"}


def test_ignored_binary_key_canary_is_refused(repo):
    """Regression: an ignored binary .key under webapp/static reached the site."""
    (repo / "webapp/static/fonts/canary.key").write_bytes(CANARY)
    assert git(repo, "status", "--porcelain") == ""  # ignored: invisible to a clean-tree check
    with pytest.raises(public_site.UnsafePublicInput, match="canary.key"):
        public_site.static_assets(repo, "HEAD")
    with pytest.raises(public_site.UnsafePublicInput, match="UNEXPECTED_STATIC_FILE fonts/canary.key"):
        public_site.static_assets(repo, None)


def test_tracked_unexpected_file_types_are_refused(repo):
    for name in ("fonts/server.pem", "js/data.json", "certs/ca.crt", "js/.env", "js/old.zip"):
        (repo / "webapp/static" / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / "webapp/static" / name).write_bytes(CANARY)
        git(repo, "add", "-f", "webapp/static/" + name)
        git(repo, "commit", "-q", "-m", name)
        with pytest.raises(public_site.UnsafePublicInput, match="UNEXPECTED_STATIC_FILE"):
            public_site.static_assets(repo, "HEAD")
        git(repo, "rm", "-q", "webapp/static/" + name)
        git(repo, "commit", "-q", "-m", "remove " + name)


def test_untracked_or_changed_static_files_are_refused(repo):
    (repo / "webapp/static/js/extra.js").write_bytes(b"export {};")
    with pytest.raises(public_site.UnsafePublicInput, match="untracked=\\['js/extra.js'\\]"):
        public_site.static_assets(repo, "HEAD")
    (repo / "webapp/static/js/extra.js").unlink()
    (repo / "webapp/static/js/app.js").write_bytes(b"export const changed = 1;")
    with pytest.raises(public_site.UnsafePublicInput, match="changed=\\['js/app.js'\\]"):
        public_site.static_assets(repo, "HEAD")


def test_committed_symlink_is_refused(repo):
    blob = git(repo, "hash-object", "-w", "--stdin")  # empty target name
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},webapp/static/js/link.js")
    git(repo, "commit", "-q", "-m", "symlink")
    with pytest.raises(public_site.UnsafePublicInput, match="UNSAFE_ENTRY 120000"):
        public_site.static_assets(repo, "HEAD")


def test_font_must_really_be_woff2(repo):
    (repo / "webapp/static/fonts/a.woff2").write_bytes(CANARY)
    git(repo, "commit", "-q", "-am", "not a font")
    with pytest.raises(public_site.UnsafePublicInput, match="NOT_A_WOFF2_FONT"):
        public_site.static_assets(repo, "HEAD")


def test_unsafe_paths_are_refused():
    for bad in ("../x.js", "/etc/x.js", "a/../../x.js", "C:/x.js", "a\\b.js"):
        with pytest.raises(public_site.UnsafePublicInput, match="UNSAFE_PATH"):
            public_site._safe(bad)


# ---- public integrity manifest ------------------------------------------------------------

def manifest_site(tmp_path, include_commit=True):
    site = tmp_path / "site"
    (site / "static").mkdir(parents=True)
    (site / "index.html").write_bytes(b"<!doctype html>")
    (site / "static/app.js").write_bytes(b"export {};")
    (site / "SOURCE-COMMIT.txt").write_bytes(b"commit abc\n")
    names = ["index.html", "static/app.js"] + (["SOURCE-COMMIT.txt"] if include_commit else [])
    (site / "SHA256SUMS.txt").write_text("".join(
        f"{hashlib.sha256((site / n).read_bytes()).hexdigest()}  {n}\n" for n in names))
    return site


def test_public_manifest_must_cover_source_commit_and_match(tmp_path):
    builder.verify_public(manifest_site(tmp_path))
    with pytest.raises(SystemExit, match="manifest coverage differs"):
        builder.verify_public(manifest_site(tmp_path / "b", include_commit=False))
    site = manifest_site(tmp_path / "c")
    (site / "SOURCE-COMMIT.txt").write_bytes(b"commit forged\n")
    with pytest.raises(SystemExit, match="checksum mismatch"):
        builder.verify_public(site)
