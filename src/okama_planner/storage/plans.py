"""Append-only requests and results, linked to a stable client identity."""

import copy
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from okama_planner.api import ForecastRequest, _parse_request
from okama_planner.multicurrency import MulticurrencyRequest

from .models import (
    Asset,
    BudgetItem,
    Client,
    Goal,
    Liability,
    Person,
    PlanRun,
    PlanSnapshot,
    Portfolio,
    Scenario,
)
from .registry import now, record, require_client


def digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def snapshot(request: ForecastRequest | MulticurrencyRequest | dict[str, Any]) -> dict[str, Any]:
    data = _parse_request(request).model_dump(mode="json")
    # Enforce finite JSON across fields as well as the forecast request's validation.
    digest(data)
    return data


def require_row(session: Session, model: Any, identifier: int) -> Any:
    if type(identifier) is not int or identifier < 1:
        raise ValueError("A database identifier must be a positive integer")
    row = session.get(model, identifier)
    if row is None:
        raise LookupError(f"{model.__tablename__} {identifier} does not exist")
    return row


def portfolio_components(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "groups" in data:
        return [
            {
                "role": "currency_group",
                "group_id": group["group_id"],
                "currency": group["request"]["currency"],
                "portfolio_mode": group["request"]["portfolio_mode"],
                "allocation": group["request"]["allocation"],
                "stages": stage_components(group["request"]["plan"]),
            }
            for group in data["groups"]
        ]
    if data.get("allocation") is not None:
        allocation = data["allocation"]
        return [
            {"role": "single", "strategy": allocation["single_strategy"]},
            *[{"role": "segment", **segment} for segment in allocation["segments"]],
        ]
    return stage_components(data["plan"])


def stage_components(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve the complete native stage definitions in component rows."""
    return [
        {
            "role": stage,
            "holdings": plan[f"{stage}_holdings"],
            "rebalancing": plan[f"{stage}_rebalancing"],
            "last_date_pin": plan[f"{stage}_last_date_pin"],
        }
        for stage in ("accumulation", "withdrawal")
    ]


def input_components(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Keep household rows once and mark native rows with their currency owner."""
    if "groups" not in data:
        return data["plan"][key]
    if key in {"persons", "budget_items"}:
        return data["household"][key]
    return [
        {**item, "group_id": group["group_id"], "currency": group["request"]["currency"]}
        for group in data["groups"]
        for item in group["request"]["plan"][key]
    ]


class PlanMethods:
    def save_plan(
        self,
        code: str,
        request: ForecastRequest | MulticurrencyRequest | dict[str, Any],
        note: str | None = None,
    ) -> int:
        data = snapshot(request)
        if note is not None and not isinstance(note, str):
            raise ValueError("Plan note must be a string or null")
        with self._transaction() as session:
            client = require_client(session, code)
            maximum = session.scalar(select(func.max(Client.version)).where(Client.registry_id == client.id))
            row = Client(
                registry_id=client.id,
                version=(maximum or 0) + 1,
                source_digest=digest(data),
                note=note,
                created_at=now(),
            )
            session.add(row)
            session.flush()
            session.add(PlanSnapshot(client_id=row.id, request=data))
            for model, key in (
                (Person, "persons"),
                (Asset, "assets"),
                (Liability, "liabilities"),
                (BudgetItem, "budget_items"),
                (Goal, "goals"),
            ):
                for position, payload in enumerate(input_components(data, key)):
                    session.add(model(client_id=row.id, position=position, payload=payload))
            for position, payload in enumerate(portfolio_components(data)):
                session.add(Portfolio(client_id=row.id, position=position, payload=payload))
            return row.id

    def load_plan(self, plan_id: int) -> ForecastRequest | MulticurrencyRequest:
        with self._transaction() as session:
            row = require_row(session, PlanSnapshot, plan_id)
            return _parse_request(row.request)

    def list_plans(self, code: str) -> list[dict[str, Any]]:
        with self._transaction() as session:
            client = require_client(session, code)
            return [
                record(row)
                for row in session.scalars(
                    select(Client).where(Client.registry_id == client.id).order_by(Client.version)
                )
            ]

    def save_scenario(
        self,
        plan_id: int,
        label: str,
        request: ForecastRequest | MulticurrencyRequest | dict[str, Any],
    ) -> int:
        data = snapshot(request)
        if not isinstance(label, str) or not label.strip():
            raise ValueError("A scenario label must be nonempty")
        with self._transaction() as session:
            require_row(session, Client, plan_id)
            row = Scenario(client_id=plan_id, label=label, request=data, created_at=now())
            session.add(row)
            session.flush()
            return row.id

    def load_scenario(self, scenario_id: int) -> ForecastRequest | MulticurrencyRequest:
        with self._transaction() as session:
            return _parse_request(require_row(session, Scenario, scenario_id).request)

    def save_result(self, scenario_id: int, result: dict[str, Any]) -> int:
        # Serialize now so NaN, Infinity and non-JSON payloads fail before any write.
        try:
            data = json.loads(json.dumps(result, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("Result must be finite JSON data") from exc
        if not isinstance(data, dict) or not isinstance(data.get("provenance"), dict):
            raise ValueError("Result requires forecast provenance")
        with self._transaction() as session:
            scenario = require_row(session, Scenario, scenario_id)
            source_digest = digest(scenario.request)
            if data["provenance"].get("input_sha256") != source_digest:
                raise ValueError("Result input hash does not match the stored scenario")
            row = PlanRun(
                scenario_id=scenario.id,
                request=scenario.request,
                result=data,
                source_digest=source_digest,
                created_at=now(),
            )
            session.add(row)
            session.flush()
            return row.id

    def load_result(self, run_id: int) -> dict[str, Any]:
        with self._transaction() as session:
            return copy.deepcopy(require_row(session, PlanRun, run_id).result)
