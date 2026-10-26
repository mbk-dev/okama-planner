"""Lossless import of advisory history into the single Planner-owned SQLite file.

No record values leave this module in reports. The source is opened read-only and
snapshotted using SQLite's backup API; destination changes commit as one transaction.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .database import PlannerStore
from .models import Base

TABLES = tuple(name for name in Base.metadata.tables if not name.startswith("planner_"))


def rows_digest(db: sqlite3.Connection, table: str, columns: list[str]) -> tuple[int, str]:
    fields = ",".join(f'"{name}"' for name in columns)
    keys = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[5]]
    order = ",".join(f'"{name}"' for name in keys or columns)
    digest, count = hashlib.sha256(), 0
    for row in db.execute(f'SELECT {fields} FROM "{table}" ORDER BY {order}'):
        digest.update(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()



def _preserve_sequences(source: sqlite3.Connection, target: sqlite3.Connection, tables: set[str]) -> None:
    for name, sequence in source.execute("SELECT name,seq FROM sqlite_sequence"):
        if name not in tables:
            raise ValueError("Unsupported source sequence")
        current = target.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
        if current is None:
            target.execute("INSERT INTO sqlite_sequence(name,seq) VALUES(?,?)", (name, sequence))
        elif sequence > current[0]:
            target.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (sequence, name))


def _copy_rows(source: sqlite3.Connection, target: sqlite3.Connection, tables: set[str],
               columns: dict[str, list[str]]) -> None:
    # Deferred constraints preserve self-referencing projection-run IDs as well.
    target.execute("PRAGMA defer_foreign_keys=ON")
    for table in sorted(tables):
        fields = ",".join(f'"{name}"' for name in columns[table])
        placeholders = ",".join("?" for _ in columns[table])
        cursor = source.execute(f'SELECT {fields} FROM "{table}"')
        while batch := cursor.fetchmany(1000):
            target.executemany(f'INSERT INTO "{table}" ({fields}) VALUES({placeholders})', batch)

def _import_snapshot(source: sqlite3.Connection, target: sqlite3.Connection) -> dict[str, Any]:
    tables = {
        r[0]
        for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if r[0] != "alembic_version" and not r[0].startswith("sqlite_")
    }
    if tables != set(TABLES):
        raise ValueError("Unsupported source schema: tables differ")
    if source.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('view','trigger')").fetchone()[0]:
        raise ValueError("Unsupported source schema: views or triggers require explicit migration")
    columns = {}
    checks = {}
    nonempty = False
    for table in sorted(tables):
        columns[table] = sorted(r[1] for r in source.execute(f'PRAGMA table_info("{table}")'))
        expected = set(Base.metadata.tables[table].columns.keys())
        if set(columns[table]) != expected:
            raise ValueError(f"Unsupported source schema: columns differ in {table}")
        checks[table] = rows_digest(source, table, columns[table])
        destination = rows_digest(target, table, columns[table])
        nonempty |= destination[0] > 0
        if destination[0] and destination != checks[table]:
            raise ValueError(f"Import conflict in {table}; destination must be empty or identical")
    if nonempty:
        if any(rows_digest(target, table, columns[table]) != checks[table] for table in tables):
            raise ValueError("Import conflict: incomplete previous data")
        status = "unchanged"
    else:
        _copy_rows(source, target, tables, columns)
        status = "imported"
    _preserve_sequences(source, target, tables)
    if target.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Imported database has broken relationships")
    if any(rows_digest(target, table, columns[table]) != checks[table] for table in tables):
        raise ValueError("Imported database failed complete row verification")
    return {
        "status": status,
        "tables": {table: checks[table][0] for table in sorted(tables)},
        "sha256": {table: checks[table][1] for table in sorted(tables)},
    }


def import_advisor_database(source_path: Path | str, target_path: Path | str) -> dict[str, Any]:
    source_path, target_path = Path(source_path).resolve(strict=True), Path(target_path).resolve(strict=True)
    if source_path == target_path:
        raise ValueError("Source and destination must differ")
    with PlannerStore.open(target_path):
        pass
    with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(":memory:")) as snapshot:
            original.backup(snapshot)
            if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Source database failed integrity check")
            with closing(sqlite3.connect(target_path.as_uri() + "?mode=rw", uri=True)) as destination:
                destination.execute("PRAGMA foreign_keys=ON")
                destination.execute("BEGIN IMMEDIATE")
                try:
                    report = _import_snapshot(snapshot, destination)
                    destination.commit()
                except BaseException:
                    destination.rollback()
                    raise
    return report
