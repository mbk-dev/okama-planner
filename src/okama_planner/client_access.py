"""Planner-owned client access policy, fixed by the local application at startup."""

from pathlib import Path
from typing import Any
from datetime import date, datetime, time

from sqlalchemy.sql.elements import ColumnElement

from sqlalchemy import delete, func, or_, select, text

from okama_planner.ai import PlannerAI, _boundary, _code
from okama_planner.storage import PlannerStore
from okama_planner.storage.models import Base
from okama_planner.storage.meetings import meeting_record
from okama_planner.storage.advisor_models import ClientMeeting
from okama_planner.storage.registry import require_client


def ownership(registry_id: int) -> dict[str, ColumnElement[bool]]:
    registry = Base.metadata.tables["client_registry"]
    predicates = {"client_registry": registry.c.id == registry_id}
    for table in Base.metadata.sorted_tables:
        if table.name == "client_registry":
            continue
        clauses = [
            foreign.parent.in_(select(foreign.column).where(predicates[foreign.column.table.name]))
            for foreign in table.foreign_keys
            if foreign.column.table.name in predicates
            and foreign.column.table is not table
            and foreign.parent.name
            in {"registry_id", "client_id", "scenario_id", "plan_run_id", "portfolio_id"}
        ]
        if table.name == "client_intake_note":
            clauses.append(table.c.registry_id == registry_id)
        if clauses:
            predicates[table.name] = or_(*clauses)
    return predicates


class PlannerClientAccess:
    """Anonymous reads by default; explicit trusted local opt-in enables personal CRUD.

    The setting is not accepted in any tool call and cannot be changed by a model.
    SQL, file paths, schema operations and deletion remain internal to Planner.
    """

    @_boundary
    def __init__(self, database: Path | str, *, allow_personal_data: bool = False) -> None:
        if type(allow_personal_data) is not bool:
            raise ValueError("Personal access requires an explicit boolean")
        self.__database = Path(database).resolve(strict=True)
        self.__personal = allow_personal_data
        self.__anonymous = PlannerAI(database)

    def _write_allowed(self) -> None:
        if not self.__personal:
            raise ValueError("Personal access is disabled; use the local Planner interface")

    @_boundary
    def client_get(self, code: str) -> dict[str, Any]:
        if not self.__personal:
            return self.__anonymous.client_get(code)
        with PlannerStore.open(self.__database) as store:
            return store.get_client(_code(code))

    @_boundary
    def client_list(self) -> list[dict[str, Any]]:
        if not self.__personal:
            return self.__anonymous.client_list()
        with PlannerStore.open(self.__database) as store:
            return store.list_clients()

    @_boundary
    def client_create(self, details: dict[str, Any]) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store:
            return store.create_client(details)

    @_boundary
    def client_update(self, code: str, changes: dict[str, Any]) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store:
            return store.update_client(_code(code), changes)

    @_boundary
    def client_delete(self, code: str) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store, store._transaction() as session:
            identity = require_client(session, _code(code))
            predicates = ownership(identity.id)
            session.execute(text("PRAGMA defer_foreign_keys=ON"))
            for table in reversed(Base.metadata.sorted_tables):
                if table.name in predicates:
                    session.execute(delete(table).where(predicates[table.name]))
        return {"code": code, "deleted": True}

    @_boundary
    def client_set_tax_residency(
        self, code: str, year: int, country: str, note: str | None = None
    ) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store:
            return store.set_tax_residency(_code(code), year, country, note)

    @_boundary
    def client_get_tax_residency(self, code: str, year: int) -> dict[str, Any] | None:
        if not self.__personal:
            return self.__anonymous.client_get_tax_residency(code, year)
        with PlannerStore.open(self.__database) as store:
            return store.get_tax_residency(_code(code), year)

    @_boundary
    def client_save_plan(self, code: str, request: Any) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store:
            identifier = store.save_plan(_code(code), request)
            version = next(row["version"] for row in store.list_plans(code) if row["id"] == identifier)
            return {"code": code, "version": version}

    def client_list_plans(self, code: str) -> list[dict[str, Any]]:
        return self.__anonymous.client_list_plans(code)

    @_boundary
    def client_load_plan(self, code: str, version: int) -> dict[str, Any]:
        if not self.__personal:
            return self.__anonymous.client_load_plan(code, version)
        with PlannerStore.open(self.__database) as store:
            row = next(row for row in store.list_plans(_code(code)) if row["version"] == version)
            return store.load_plan(row["id"]).model_dump(mode="json")

    def client_forecast(self, code: str, version: int) -> dict[str, Any]:
        # Forecast/report responses retain the signed anonymous contract in both modes.
        return self.__anonymous.client_forecast(code, version)

    @_boundary
    def meeting_list(self, code: str) -> list[dict[str, Any]]:
        with PlannerStore.open(self.__database) as store:
            records = store.list_meetings(_code(code))
        if self.__personal:
            return records
        return [
            {
                key: (f"meeting-{row['id']:04d}-{key}" if key in {"goal", "notes"} else value)
                for key, value in row.items()
                if key != "registry_id"
            }
            for row in records
        ]

    @_boundary
    def meeting_save(
        self, code: str, meeting: dict[str, Any], meeting_id: int | None = None, revision: str | None = None
    ) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store:
            return store.save_meeting(_code(code), meeting, meeting_id, revision)

    @_boundary
    def meeting_delete(self, code: str, meeting_id: int, revision: str) -> dict[str, Any]:
        self._write_allowed()
        with PlannerStore.open(self.__database) as store, store._transaction() as session:
            identity = require_client(session, _code(code))
            row = session.scalar(
                select(ClientMeeting).where(
                    ClientMeeting.id == meeting_id, ClientMeeting.registry_id == identity.id
                )
            )
            if row is None or meeting_record(row)["revision"] != revision:
                raise ValueError("Unknown or changed meeting")
            session.delete(row)
        return {"code": code, "deleted": True}

    @_boundary
    def client_history(self, code: str, table: str, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        self._write_allowed()
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Invalid history page")
        with PlannerStore.open(self.__database) as store, store._transaction() as session:
            identity = require_client(session, _code(code))
            predicates = ownership(identity.id)
            if table not in predicates:
                raise ValueError("Unknown client history section")
            model = Base.metadata.tables[table]
            query = select(model).where(predicates[table]).order_by(*model.primary_key.columns)
            rows = session.execute(query.offset(offset).limit(limit)).mappings()
            records = [
                {
                    key: value.isoformat() if isinstance(value, (date, time, datetime)) else value
                    for key, value in row.items()
                }
                for row in rows
            ]
            count = session.scalar(select(func.count()).select_from(model).where(predicates[table]))
        return {
            "code": code,
            "table": table,
            "offset": offset,
            "limit": limit,
            "total": count,
            "records": records,
        }
