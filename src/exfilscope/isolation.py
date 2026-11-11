"""Non-destructive SQLite write-capability probes for deployment audits."""

import sqlite3
from pathlib import Path
from uuid import uuid4


def probe_write_access(path: Path) -> str:
    if not path.is_file():
        return "UNMOUNTED_OR_MISSING"
    db = None
    try:
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=2)
        db.execute("BEGIN IMMEDIATE")
        # A unique persistent table, rolled back before commit; no evidence row changes.
        table = "permission_probe_" + uuid4().hex
        db.execute(f"CREATE TABLE {table} (value INTEGER)")
        db.execute(f"INSERT INTO {table} VALUES (1)")
        return "WRITABLE"
    except sqlite3.Error as error:
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        return "DENIED" if code in (sqlite3.SQLITE_READONLY, sqlite3.SQLITE_PERM,
                                    sqlite3.SQLITE_AUTH) else "INDETERMINATE"
    finally:
        if db:
            db.rollback()
            db.close()
