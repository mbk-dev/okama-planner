import sqlite3
from importlib.resources import files
from pathlib import Path

from okama_planner.storage import PlannerStore


def test_supplied_template_and_generated_database_are_empty(tmp_path: Path) -> None:
    from okama_planner.storage import create_template
    from okama_planner.storage.models import Base
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    supplied = files("okama_planner.storage").joinpath("templates/empty.sqlite3")
    assert supplied.is_file()
    generated = tmp_path / "empty.db"
    create_template(generated)
    for path in (Path(str(supplied)), generated):
        with PlannerStore.open(path) as store:
            assert store.list_clients() == []
            with store.engine.connect() as connection:
                assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        with sqlite3.connect(path) as db:
            for table in Base.metadata.tables:
                assert db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] == 0
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_initialize_database_permissions(tmp_path: Path) -> None:
    path = tmp_path / "private.db"
    PlannerStore.initialize(path).close()
    assert path.stat().st_mode & 0o077 == 0
