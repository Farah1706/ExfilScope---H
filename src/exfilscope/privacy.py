"""Exact synthetic exposure checks, including JSON escapes and SQLite UTF-16 variants."""

import json
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path

from .registry import Registry

SCANNER_VERSION = "exposure-2"


def unicode_escaped(value: str, *, upper: bool = False) -> str:
    """JSON Unicode escapes use UTF-16 code units, including surrogate pairs."""
    raw = value.encode("utf-16-be")
    spec = "04X" if upper else "04x"
    return "".join("\\u" + format(int.from_bytes(raw[i:i + 2], "big"), spec)
                   for i in range(0, len(raw), 2))


def _logical_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _logical_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _logical_strings(child)


def _decoded_text(text: str):
    yield text
    try:
        yield from _logical_strings(json.loads(text))
    except (ValueError, RecursionError):
        pass


def _logical_content(path: Path, data: bytes):
    if path.suffix in (".sqlite", ".db"):
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for (table,) in tables:
                quoted = '"' + table.replace('"', '""') + '"'
                for row in db.execute("SELECT * FROM " + quoted):
                    for cell in row:
                        if isinstance(cell, str):
                            yield from _decoded_text(cell)
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeError:
            return
        yield from _decoded_text(text)
        for line in text.splitlines():
            yield from _decoded_text(line)


def scan_routine_files(paths: list[Path], registry: Registry) -> dict[str, list[str]]:
    """Return IDs and basenames only, never leaked plaintext or file contents."""
    with ExitStack() as guards:
        # Pin SQLite read transactions before scanning retained DB/WAL bytes. A live
        # heartbeat writer would otherwise checkpoint/unlink WAL between listing and read.
        mains = {p for p in paths if p.suffix in (".sqlite", ".db")}
        for main in mains:
            db = guards.enter_context(closing(sqlite3.connect(
                main.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)))
            db.execute("BEGIN")
            db.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        retained = []
        for path in paths:
            if path.name.endswith("-wal") and not path.exists():
                main = Path(str(path).removesuffix("-wal"))
                if main not in mains:
                    raise OSError("WAL_CAPTURE_UNVERIFIED")
                # Checkpoint completed before the read guard: scan the retained main DB;
                # do not claim that a no-longer-retained historical WAL was captured.
                continue
            retained.append(path)
        for main in mains:
            wal = Path(str(main) + "-wal")
            if wal.exists() and wal not in retained:
                retained.append(wal)
        return _scan_retained(retained, registry)


def _scan_retained(paths: list[Path], registry: Registry) -> dict[str, list[str]]:
    leaks = {}
    for path in paths:
        data = path.read_bytes()
        logical = tuple(_logical_content(path, data))
        recovered = []
        for item in registry.items:
            texts = {item.value, json.dumps(item.value, ensure_ascii=True)[1:-1],
                     json.dumps(item.value, ensure_ascii=False)[1:-1],
                     unicode_escaped(item.value), unicode_escaped(item.value, upper=True)}
            patterns = [text.encode(encoding) for text in texts
                        for encoding in ("utf-8", "utf-16-le", "utf-16-be")]
            if any(pattern in data for pattern in patterns) or any(item.value in s for s in logical):
                recovered.append(item.protected_id)
        if recovered:
            leaks[path.name] = recovered
    return leaks


def routine_paths(directory: Path) -> list[Path]:
    return [path for path in directory.rglob("*") if path.is_file()
            and not path.name.endswith("-shm")  # transient SQLite index, not a payload store
            and ("sqlite" in path.name or path.suffix in (".log", ".csv", ".jsonl", ".json"))]
