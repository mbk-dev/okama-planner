"""One identity owns CRM, meetings and both historical/native planning formats."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from okama_planner.storage import PlannerStore, upgrade_database
from okama_planner.storage.database import make_engine, migration_config


def test_crm_identifier_is_opaque_and_human_only(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path / "clients.db") as store:
        client = store.create_client({"full_name": "Synthetic Client", "crm_id": "CRM-0007/A"})
        assert client["crm_id"] == "CRM-0007/A"
        store.update_client(client["code"], {"crm_id": "000013"})
        assert store.get_client(client["code"])["crm_id"] == "000013"
        with pytest.raises(ValueError):
            store.update_client(client["code"], {"crm_id": "   "})


def test_meetings_persist_with_ownership_and_stale_edit_protection(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    with PlannerStore.initialize(path) as store:
        one = store.create_client({"full_name": "Synthetic One"})["code"]
        two = store.create_client({"full_name": "Synthetic Two"})["code"]
        assert hasattr(store, "save_meeting"), "Planner must persist the human meeting journal"
        first = store.save_meeting(
            one,
            {
                "goal": "Review",
                "date": "2026-10-26",
                "time": "14:05",
                "format": "online",
                "notes": "## Notes\n\nExact **Markdown**",
            },
        )
        assert first["date"] == "2026-10-26" and first["time"] == "14:05"
        saved = store.save_meeting(
            one,
            {"goal": "Updated", "date": "2026-10-26", "time": "", "format": "phone", "notes": ""},
            first["id"],
            first["revision"],
        )
        assert saved["time"] == "" and saved["revision"] != first["revision"]
        with pytest.raises(ValueError, match="changed"):
            store.save_meeting(
                one,
                {"goal": "Stale", "date": "2026-10-26", "format": "online"},
                first["id"],
                first["revision"],
            )
        with pytest.raises(LookupError):
            store.save_meeting(
                two,
                {"goal": "Wrong owner", "date": "2026-10-26", "format": "online"},
                saved["id"],
                saved["revision"],
            )
        assert store.list_meetings(two) == []
        for field, value in [
            ("date", "2026-02-30"),
            ("time", "24:00"),
            ("time", "10:99"),
            ("format", "unknown"),
            ("goal", "  "),
        ]:
            invalid = {"goal": "Review", "date": "2026-10-26", "format": "online", field: value}
            with pytest.raises(ValueError):
                store.save_meeting(one, invalid)
    with PlannerStore.open(path) as store:
        assert store.list_meetings(one)[0]["goal"] == "Updated"
        assert len(store.list_meetings(one)) == 1
        assert store.list_plans(one) == []


def test_old_planner_schema_upgrades_without_losing_native_plans(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    path.touch()
    engine = make_engine(path)
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), "0002")
        connection.exec_driver_sql(
            "INSERT INTO client_registry(id,code,full_name,created_at) "
            "VALUES(1,'c-0001','Synthetic','2026-10-26')"
        )
        connection.exec_driver_sql(
            "INSERT INTO client(id,registry_id,version,source_digest,created_at) "
            "VALUES(1,1,1,'synthetic','2026-10-26')"
        )
    engine.dispose()
    upgrade_database(path)
    upgrade_database(path)
    with PlannerStore.open(path) as store:
        assert store.get_client("c-0001")["crm_id"] is None
        assert len(store.list_plans("c-0001")) == 1
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT count(*) FROM planner_client").fetchone()[0] == 1
        assert database.execute("SELECT count(*) FROM client").fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM client_meeting").fetchone()[0] == 0
