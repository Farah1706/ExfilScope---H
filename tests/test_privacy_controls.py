"""Exposure scanner controls live only in test artifacts, outside experiment denominators."""

import json
import sqlite3

import pytest

from exfilscope.privacy import scan_routine_files, unicode_escaped
from exfilscope.registry import ProtectedItem, Registry


def registry():
    return Registry([
        ProtectedItem(protected_id="CONTROL_KEY", value='SYNTHETIC_KEY_Z19"\\TOKEN',
                      source_ref="CONTROL", data_type="API_KEY"),
        ProtectedItem(protected_id="CONTROL_PHRASE", value="SYNTHETIC_秘密_é_😀_phrase",
                      source_ref="CONTROL", data_type="PHRASE")])


def represented(item, representation):
    if representation == "plain":
        return item.value
    if representation in ("minimal", "ascii"):
        return json.dumps(item.value, ensure_ascii=representation == "ascii")[1:-1]
    return unicode_escaped(item.value, upper=representation == "upper")


@pytest.mark.parametrize("category", ["database", "wal", "export", "journal_log"])
@pytest.mark.parametrize("representation", ["plain", "minimal", "ascii", "lower", "upper"])
def test_declared_positive_controls(tmp_path, category, representation):
    markers = registry()
    content = "\n".join(represented(i, representation) for i in markers.items)
    if category in ("database", "wal"):
        path = tmp_path / "control.sqlite"
        with sqlite3.connect(path) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("CREATE TABLE control (value TEXT)")
            writer.commit()
            reader = sqlite3.connect(path)
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM control").fetchall()
            try:
                writer.execute("INSERT INTO control VALUES (?)", (content,))
                writer.commit()
                if category == "wal":
                    path = tmp_path / "control.sqlite-wal"
                    assert path.exists()
                else:
                    # Database allocated-page control after an actual checkpoint.
                    reader.close()
                    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                recovered = scan_routine_files([path], markers)
            finally:
                reader.close()
    else:
        path = tmp_path / ("control.jsonl" if category == "export" else "control.log")
        path.write_text(content, encoding="utf-8")
        recovered = scan_routine_files([path], markers)
    assert recovered == {path.name: ["CONTROL_KEY", "CONTROL_PHRASE"]}


@pytest.mark.parametrize("category", ["database", "wal", "export", "journal_log"])
def test_negative_controls(tmp_path, category):
    path = tmp_path / ("negative.sqlite" if category in ("database", "wal") else "negative.log")
    if category in ("database", "wal"):
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE control (value TEXT)")
            db.commit()
            reader = sqlite3.connect(path)
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM control").fetchall()
            try:
                db.execute("INSERT INTO control VALUES ('harmless')")
                db.commit()
                if category == "wal":
                    path = tmp_path / "negative.sqlite-wal"
                assert scan_routine_files([path], registry()) == {}
            finally:
                reader.close()
    else:
        path.write_text('{"harmless":"ordinary"}', encoding="utf-8")
        assert scan_routine_files([path], registry()) == {}


def test_structured_json_and_ledger_logical_decoding_detect_mixed_escape_case(tmp_path):
    markers = registry()
    escaped = unicode_escaped(markers.items[1].value)
    mixed = escaped.replace("00e9", "00E9").replace("d83d", "D83D")
    path = tmp_path / "mixed.jsonl"
    path.write_text('{"value":"' + mixed + '"}', encoding="utf-8")
    assert scan_routine_files([path], markers) == {path.name: ["CONTROL_PHRASE"]}
    ledger = tmp_path / "mixed.sqlite"
    with sqlite3.connect(ledger) as db:
        db.execute("CREATE TABLE control (value TEXT)")
        db.execute("INSERT INTO control VALUES (?)", (path.read_text(),))
    assert scan_routine_files([ledger], markers) == {ledger.name: ["CONTROL_PHRASE"]}
