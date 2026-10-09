"""Snapshots preserve native ownership and the single household budget."""

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from okama_planner.api import ForecastRequest, _digest
from okama_planner.multicurrency import MulticurrencyRequest
from okama_planner.storage import PlannerStore
from okama_planner.storage.plans import snapshot
from test_allocation import allocation
from test_multicurrency import multicurrency_request


def owned_request() -> dict:
    raw = multicurrency_request()
    raw["household"]["persons"] = [{"name": "Synthetic", "birth_year": 1990, "role": "owner"}]
    for index, group in enumerate(raw["groups"], start=1):
        native = group["request"]
        native["plan"]["persons"] = raw["household"]["persons"]
        native["portfolio_mode"] = "per_goal" if index == 2 else "single"
        native["plan"]["goals"] = [{"goal_id": index, "label": "Purchase", "kind": "lump",
                                    "amount_pv": 10, "pv_year": 2026, "target_year": 2026}]
        native["plan"]["liabilities"] = [{"label": "Loan", "principal": 10, "annual_rate": 0,
                                          "monthly_payment": 1, "term_months": 10,
                                          "start_month": "2026-01"}]
        native["allocation"] = allocation(100, (index,))
        for segment in native["allocation"]["segments"]:
            segment["currency"] = native["currency"]
    return raw


def test_multicurrency_plan_scenario_and_result_round_trip(tmp_path: Path) -> None:
    parsed = MulticurrencyRequest.model_validate(owned_request())
    expected = parsed.model_dump(mode="json")
    with PlannerStore.initialize(tmp_path / "multi.db") as store:
        code = store.create_client({"full_name": "Synthetic Household"})["code"]
        pid = store.save_plan(code, parsed)
        assert isinstance(store.load_plan(pid), MulticurrencyRequest)
        assert store.load_plan(pid).model_dump(mode="json") == expected
        assert store.list_plans(code)[0]["source_digest"] == _digest(expected)
        sid = store.save_scenario(pid, "Currencies", expected)
        assert store.load_scenario(sid) == parsed
        # Storage checks JSON and provenance; numerical engine assertions live elsewhere.
        result = {"schema_version": "2.0", "provenance": {"input_sha256": _digest(expected)}}
        rid = store.save_result(sid, result)
        assert store.load_result(rid) == result
        bad = copy.deepcopy(result)
        bad["provenance"]["input_sha256"] = "wrong"
        with pytest.raises(ValueError, match="hash"):
            store.save_result(sid, bad)
        with store.engine.connect() as connection:
            def payloads(table: str) -> list[dict]:
                return [json.loads(v) for v in connection.exec_driver_sql(
                    f"SELECT payload FROM {table} ORDER BY position"
                ).scalars()]

            assert payloads("person") == expected["household"]["persons"]
            assert payloads("budget_item") == expected["household"]["budget_items"]
            for table, key in (("asset", "assets"), ("liability", "liabilities"), ("goal", "goals")):
                assert payloads(table) == [
                    {**item, "group_id": group["group_id"], "currency": group["request"]["currency"]}
                    for group in expected["groups"] for item in group["request"]["plan"][key]
                ]
            portfolios = payloads("portfolio")
            assert len(portfolios) == 2
            for row, group in zip(portfolios, expected["groups"], strict=True):
                assert row["group_id"] == group["group_id"]
                assert row["currency"] == group["request"]["currency"]
                assert row["portfolio_mode"] == group["request"]["portfolio_mode"]
                assert row["allocation"] == group["request"]["allocation"]
                assert row["stages"] == [
                    {"role": stage,
                     "holdings": group["request"]["plan"][f"{stage}_holdings"],
                     "rebalancing": group["request"]["plan"][f"{stage}_rebalancing"],
                     "last_date_pin": group["request"]["plan"][f"{stage}_last_date_pin"]}
                    for stage in ("accumulation", "withdrawal")
                ]


def test_legacy_snapshot_serialization_is_unchanged() -> None:
    raw = json.loads(Path("examples/readme-request.json").read_text())
    expected = ForecastRequest.model_validate(raw).model_dump(mode="json")
    assert snapshot(raw) == expected
    assert snapshot(ForecastRequest.model_validate(raw)) == expected
    assert "groups" not in expected
    assert "portfolio_mode" not in expected


def test_multicurrency_failure_leaves_no_partial_components(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path / "rollback.db") as store:
        code = store.create_client({"full_name": "Synthetic Household"})["code"]
        bad = owned_request()
        bad["fx"]["opening_rates"]["USD"] = 0
        with pytest.raises(ValueError):
            store.save_plan(code, bad)
        assert store.list_plans(code) == []
        with store.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TRIGGER fail_goal BEFORE INSERT ON goal "
                                       "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with pytest.raises(IntegrityError, match="test failure"):
            store.save_plan(code, owned_request())
        assert store.list_plans(code) == []
        with store.engine.connect() as connection:
            for table in ("client", "plan_snapshot", "person", "budget_item", "asset", "liability",
                          "goal", "portfolio"):
                assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0
