"""Deleting one client's imported history must not erase a different identity."""

import sqlite3
from pathlib import Path

import pytest
from okama_planner.ai import PlannerClientAccess
from okama_planner.storage import PlannerStore, import_advisor_database


def test_delete_all_owned_history_preserves_other_clients(tmp_path: Path) -> None:
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    with sqlite3.connect(source) as db:
        db.executescript(Path("tests/fixtures/advisor-schema.sql").read_text())
        db.execute("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES('synthetic')")
        for identifier in [1, 2]:
            db.execute(
                "INSERT INTO client_registry(id,code,full_name,created_at) VALUES(?,?,?,?)",
                (identifier, f"c-{identifier:04d}", f"Synthetic {identifier}", "2026-10-26"),
            )
            db.execute(
                "INSERT INTO client(id,registry_id,version,source_digest,created_at) VALUES(?,?,1,?,?)",
                (identifier, identifier, "digest", "2026-10-26"),
            )
            db.execute(
                "INSERT INTO person(id,client_id,name,birth_year,role) VALUES(?,?,?,?,?)",
                (identifier, identifier, f"Synthetic {identifier}", 1980, "client"),
            )
    PlannerStore.initialize(target).close()
    import_advisor_database(source, target)
    service = PlannerClientAccess(target, allow_personal_data=True)
    history = getattr(service, "client_history", None)
    assert callable(history), "Full access must include imported client history through Planner"
    assert history("c-0001", "person")["records"][0]["name"] == "Synthetic 1"
    assert history("c-0001", "person", offset=1)["records"] == []
    with pytest.raises(ValueError):
        PlannerClientAccess(target).client_history("c-0001", "person")
    assert service.client_delete("c-0001")["deleted"]
    with PlannerStore.open(target) as store:
        assert [r["code"] for r in store.list_clients()] == ["c-0002"]
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT name FROM person").fetchall() == [("Synthetic 2",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_cross_client_reference_never_grants_deletion_ownership(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    with PlannerStore.initialize(path) as store:
        one = store.create_client({"full_name": "Synthetic One"})
        two = store.create_client({"full_name": "Synthetic Two"})
        with store.engine.begin() as db:
            for identifier, code in [(1, one["id"]), (2, two["id"])]:
                db.exec_driver_sql(
                    "INSERT INTO client(id,registry_id,version,source_digest,created_at) VALUES(?,?,1,?,?)",
                    (identifier, code, "digest", "2026-10-26"),
                )
            db.exec_driver_sql(
                "INSERT INTO goal(id,client_id,label,kind,amount_pv,amount_basis,pv_year,priority,"
                "becomes_asset,can_defer,can_resize) VALUES(1,1,'Synthetic','lump',1,'amount',2026,1,0,0,0)"
            )
            db.exec_driver_sql(
                "INSERT INTO scenario(id,client_id,label,is_base,created_at) "
                "VALUES(1,2,'Synthetic',1,'2026-10-26')"
            )
            db.exec_driver_sql(
                "INSERT INTO goal_adjustment(id,scenario_id,goal_id,action) VALUES(1,1,1,'drop')"
            )
    with pytest.raises(ValueError):
        PlannerClientAccess(path, allow_personal_data=True).client_delete(one["code"])
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM client_registry").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM goal_adjustment").fetchone()[0] == 1
