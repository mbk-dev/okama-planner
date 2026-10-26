"""A lossless, atomic and repeatable import before retiring the old working file."""

import sqlite3
from pathlib import Path

import pytest
import okama_planner.storage as storage


def source_database(path: Path) -> None:
    with sqlite3.connect(path) as db:
        db.executescript(Path("tests/fixtures/advisor-schema.sql").read_text())
        db.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES('synthetic-lfp-head')")
        for identifier in [1, 7, 100]:
            db.execute(
                "INSERT INTO client_registry(id,code,full_name,crm_id,created_at) VALUES(?,?,?,?,?)",
                (
                    identifier,
                    f"c-{identifier:04d}",
                    f"Synthetic {identifier}",
                    f"CRM-00{identifier}",
                    "2026-10-26 12:00:00.000000",
                ),
            )
        db.execute("DELETE FROM client_registry WHERE id=100")
        db.execute(
            "INSERT INTO client(id,registry_id,version,source_digest,created_at) "
            "VALUES(1,7,1,'digest','2026-10-26 12:00:00.000000')"
        )
        db.execute(
            "INSERT INTO person(id,client_id,name,birth_year,role) VALUES(1,1,'Synthetic Child',2010,'child')"
        )
        db.execute(
            "INSERT INTO client_meeting(id,registry_id,goal,date,time,format,notes) "
            "VALUES(1,7,'Review','2026-10-26','14:05:00.000000','online','## Exact Markdown')"
        )
        db.execute(
            "INSERT INTO client_intake_note(id,registry_id,source_key,content_digest,content,imported_at) "
            "VALUES(1,7,'source','digest','Exact original note','2026-10-26 12:00:00.000000')"
        )


def test_complete_import_and_idempotent_readback(tmp_path: Path) -> None:
    source, target = tmp_path / "source.db", tmp_path / "planner.db"
    source_database(source)
    storage.PlannerStore.initialize(target).close()
    importer = getattr(storage, "import_advisor_database", None)
    assert callable(importer), "Planner must import all existing client history before retiring LFP storage"
    result = importer(source, target)
    assert result["tables"]["client_registry"] == 2
    assert result["tables"]["person"] == 1
    assert result["tables"]["client_intake_note"] == 1
    assert result["status"] == "imported"
    assert importer(source, target)["status"] == "unchanged"
    with storage.PlannerStore.open(target) as store:
        assert store.get_client("c-0007")["crm_id"] == "CRM-007"
        assert store.list_meetings("c-0007")[0]["notes"] == "## Exact Markdown"
        assert store.create_client({"full_name": "New Synthetic"})["code"] == "c-0101"
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT name,birth_year FROM person").fetchone() == ("Synthetic Child", 2010)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)


def test_conflicting_import_is_atomic(tmp_path: Path) -> None:
    source, target = tmp_path / "source.db", tmp_path / "planner.db"
    source_database(source)
    with storage.PlannerStore.initialize(target) as store:
        store.create_client({"full_name": "Different Synthetic"})
    importer = getattr(storage, "import_advisor_database", None)
    assert callable(importer), "Missing verified import"
    with pytest.raises(ValueError, match="conflict"):
        importer(source, target)
    with storage.PlannerStore.open(target) as store:
        assert len(store.list_clients()) == 1
        assert store.get_client("c-0001")["full_name"] == "Different Synthetic"
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT count(*) FROM person").fetchone()[0] == 0


def test_unknown_source_columns_are_not_silently_discarded(tmp_path: Path) -> None:
    source, target = tmp_path / "source.db", tmp_path / "planner.db"
    source_database(source)
    storage.PlannerStore.initialize(target).close()
    with sqlite3.connect(source) as db:
        db.execute("ALTER TABLE client_registry ADD COLUMN future_private_field TEXT")
    importer = getattr(storage, "import_advisor_database", None)
    assert callable(importer), "Missing verified import"
    with pytest.raises(ValueError, match="schema"):
        importer(source, target)
    with storage.PlannerStore.open(target) as store:
        assert store.list_clients() == []
