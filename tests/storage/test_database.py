import sqlite3
from pathlib import Path

import pytest


def test_initialize_empty_schema(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore

    path = tmp_path / "new.sqlite3"
    with PlannerStore.initialize(path):
        pass
    with sqlite3.connect(path) as db:
        columns = {r[1] for r in db.execute("PRAGMA table_info(client_registry)")}
        assert columns == {
            "id",
            "code",
            "full_name",
            "sex",
            "birth_year",
            "email",
            "phone",
            "telegram",
            "telegram_id",
            "whatsapp",
            "max_messenger",
            "brokers",
            "primary_channel",
            "ips_sent_at",
            "note",
            "created_at",
        }
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "client",
            "tax_residency",
            "plan_snapshot",
            "person",
            "asset",
            "liability",
            "budget_item",
            "goal",
            "portfolio",
            "scenario",
            "plan_run",
        } <= tables
        for table in tables - {"alembic_version", "sqlite_sequence"}:
            assert db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0


def test_open_missing_and_initialize_existing_do_not_write(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore

    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        PlannerStore.open(path)
    assert not path.exists()
    path.write_bytes(b"keep me")
    with pytest.raises(FileExistsError):
        PlannerStore.initialize(path)
    assert path.read_bytes() == b"keep me"


def test_foreign_keys_and_unknown_revision(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore, upgrade_database

    path = tmp_path / "db.sqlite3"
    with PlannerStore.initialize(path) as store:
        with store.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    with sqlite3.connect(path) as db:
        db.execute("UPDATE alembic_version SET version_num='future' ")
    with pytest.raises(ValueError, match="schema"):
        PlannerStore.open(path)
    with pytest.raises(ValueError, match="schema"):
        upgrade_database(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "future"


def test_upgrade_preserves_previous_schema_data(tmp_path: Path) -> None:
    from okama_planner.storage.database import migration_config, make_engine
    from okama_planner.storage import PlannerStore, upgrade_database
    from alembic import command

    path = tmp_path / "older.db"
    path.touch()
    engine = make_engine(path)
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "0001")
        connection.exec_driver_sql(
            "INSERT INTO client_registry (code, full_name, created_at) "
            "VALUES ('c-0001', 'Synthetic One', '2026-10-09T00:00:00+00:00')"
        )
    engine.dispose()
    with pytest.raises(ValueError, match="schema"):
        PlannerStore.open(path)
    upgrade_database(path)
    upgrade_database(path)
    with PlannerStore.open(path) as store:
        with store.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT code,full_name FROM client_registry").one() == (
                "c-0001",
                "Synthetic One",
            )
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0002"


def test_declared_current_revision_requires_complete_schema(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore

    path = tmp_path / "incomplete.db"
    PlannerStore.initialize(path).close()
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE goal")
    with pytest.raises(ValueError, match="schema"):
        PlannerStore.open(path)


def test_opened_database_is_not_recreated_after_removal(tmp_path: Path) -> None:
    from okama_planner.storage import PlannerStore
    from sqlalchemy.exc import OperationalError

    path = tmp_path / "removed.db"
    PlannerStore.initialize(path).close()
    store = PlannerStore.open(path)
    store.engine.dispose()
    path.unlink()
    try:
        with pytest.raises(OperationalError):
            store.list_clients()
        assert not path.exists()
    finally:
        store.close()


def test_concurrent_initializations_are_independent(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from okama_planner.storage import PlannerStore

    barrier = Barrier(2)

    def initialize(index: int) -> None:
        barrier.wait()
        path = tmp_path / f"parallel-{index}.db"
        with PlannerStore.initialize(path) as store:
            assert store.list_clients() == []

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(initialize, range(2)))
    for index in range(2):
        with PlannerStore.open(tmp_path / f"parallel-{index}.db") as store:
            assert store.list_clients() == []


@pytest.mark.parametrize("missing", ["primary_key", "autoincrement"])
def test_open_rejects_missing_identity_constraints(tmp_path: Path, missing: str) -> None:
    from okama_planner.storage import PlannerStore

    reference = tmp_path / "reference.db"
    PlannerStore.initialize(reference).close()
    path = tmp_path / "damaged.db"
    with sqlite3.connect(reference) as db:
        script = "\n".join(db.iterdump())
    if missing == "primary_key":
        start = script.index("CREATE TABLE client (")
        end = script.index(");", start)
        script = script[:start] + script[start:end].replace("PRIMARY KEY (id),", "") + script[end:]
    else:
        script = script.replace("PRIMARY KEY AUTOINCREMENT", "PRIMARY KEY")
        script = "\n".join(line for line in script.splitlines() if "sqlite_sequence" not in line)
    with sqlite3.connect(path) as db:
        db.executescript(script)
    with pytest.raises(ValueError, match="schema"):
        PlannerStore.open(path)
