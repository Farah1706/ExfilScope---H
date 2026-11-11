"""Separate writer capabilities and read-only verification access.

OS/container mounts must enforce write separation; class boundaries alone cannot.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Generic, TypeVar

from .contracts import Contract, ObservedEvent, RuntimeEvent
from .health import CollectionHealth, request_fingerprint

Event = TypeVar("Event", bound=Contract)


class _Writer(Generic[Event]):
    kind: str
    model: type[Event]

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            # Schema and ownership metadata become visible together, rather than
            # exposing an empty ledger_meta table before its INSERT commits.
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE IF NOT EXISTS ledger_meta (kind TEXT, version TEXT)")
            row = db.execute("SELECT kind, version FROM ledger_meta").fetchone()
            if row is None:
                db.execute("INSERT INTO ledger_meta VALUES (?, ?)", (self.kind, "1.0"))
            elif row != (self.kind, "1.0"):
                raise ValueError("WRONG_LEDGER")
            db.execute("CREATE TABLE IF NOT EXISTS events "
                       "(event_id TEXT PRIMARY KEY, trace_id TEXT, data TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS trace_idx ON events(trace_id)")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def insert(self, event: Event) -> None:
        if not isinstance(event, self.model):
            raise TypeError("WRONG_EVENT_TYPE")
        with self._connect() as db:
            db.execute("INSERT INTO events VALUES (?, ?, ?)",
                       (str(event.event_id), str(event.trace_id) if event.trace_id else None,
                        event.model_dump_json()))

    def update(self, event: Event) -> None:
        if not isinstance(event, self.model):
            raise TypeError("WRONG_EVENT_TYPE")
        with self._connect() as db:
            result = db.execute("UPDATE events SET data=? WHERE event_id=?",
                                (event.model_dump_json(), str(event.event_id)))
            if result.rowcount != 1:
                raise ValueError("EVENT_NOT_FOUND")


class RuntimeWriter(_Writer[RuntimeEvent]):
    kind = "A"
    model = RuntimeEvent


class MonitorWriter(_Writer[ObservedEvent]):
    kind = "B"
    model = ObservedEvent

    def __init__(self, path: Path):
        super().__init__(path)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS collection_health "
                       "(run_id TEXT, sequence INTEGER, data TEXT NOT NULL, "
                       "PRIMARY KEY(run_id, sequence))")

    @staticmethod
    def _append_health(db: sqlite3.Connection, record: CollectionHealth) -> None:
        db.execute("INSERT INTO collection_health VALUES (?, ?, ?)",
                   (str(record.run_id), record.sequence, record.model_dump_json()))

    def append_health(self, record: CollectionHealth) -> None:
        with self._connect() as db:
            self._append_health(db, record)

    def record_observation(self, event: ObservedEvent, record: CollectionHealth) -> None:
        if record.kind != "REQUEST" or record.request_event_id != event.event_id \
                or record.request_digest != request_fingerprint(event):
            raise ValueError("RECEIPT_EVENT_MISMATCH")
        with self._connect() as db:
            db.execute("INSERT INTO events VALUES (?, ?, ?)",
                       (str(event.event_id), str(event.trace_id) if event.trace_id else None,
                        event.model_dump_json()))
            self._append_health(db, record)


def read_events(path: Path, model: type[Event], kind: str) -> list[Event]:
    """Read-only URI fails if absent; never creates missing evidence databases."""
    uri = path.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as db:
        if db.execute("SELECT kind, version FROM ledger_meta").fetchone() != (kind, "1.0"):
            raise ValueError("WRONG_LEDGER")
        return [model.model_validate_json(row[0]) for row in db.execute(
            "SELECT data FROM events ORDER BY rowid")]


def read_monitor_snapshot(path: Path) -> tuple[list[ObservedEvent], list[CollectionHealth]]:
    """Single SQLite read snapshot: never mix receipts and events from different commits.

    Legacy B databases return no health and cannot qualify an absence conclusion.
    """
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True,
                                timeout=10)) as db:
        db.execute("BEGIN")
        metadata = db.execute("SELECT kind, version FROM ledger_meta").fetchone()
        if metadata is None:
            raise sqlite3.OperationalError("LEDGER_INITIALIZATION_INCOMPLETE")
        if metadata != ("B", "1.0"):
            raise ValueError("WRONG_LEDGER")
        events = [ObservedEvent.model_validate_json(row[0]) for row in db.execute(
            "SELECT data FROM events ORDER BY rowid")]
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_health'").fetchone()
        health = [CollectionHealth.model_validate_json(row[0]) for row in db.execute(
            "SELECT data FROM collection_health ORDER BY rowid")] if exists else []
        return events, health
