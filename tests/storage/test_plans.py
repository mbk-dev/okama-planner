import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from okama_planner import forecast
from okama_planner.api import ForecastRequest
from okama_planner.storage import PlannerStore


def request() -> dict:
    data = json.loads(Path("examples/readme-request.json").read_text())
    data["mc_number"] = 10
    return data


def test_versions_scenarios_results_and_replay(tmp_path: Path) -> None:
    original = request()
    changed = copy.deepcopy(original)
    changed["seed"] = 7
    result = json.loads(json.dumps(forecast(original)))
    with PlannerStore.initialize(tmp_path / "plans.db") as store:
        first = store.create_client({"full_name": "Synthetic One"})
        second = store.create_client({"full_name": "Synthetic Two"})
        p1 = store.save_plan(first["code"], original)
        p2 = store.save_plan(first["code"], changed, note="Second version")
        p3 = store.save_plan(second["code"], original)
        assert [p["version"] for p in store.list_plans(first["code"])] == [1, 2]
        assert [p["id"] for p in store.list_plans(second["code"])] == [p3]
        saved = store.load_plan(p1)
        assert isinstance(saved, ForecastRequest)
        assert saved.model_dump(mode="json") == ForecastRequest.model_validate(original).model_dump(
            mode="json"
        )
        assert json.loads(json.dumps(forecast(saved))) == result
        s1 = store.save_scenario(p1, "Original", original)
        s2 = store.save_scenario(p2, "Changed", changed)
        assert store.load_scenario(s2).seed == 7
        r1 = store.save_result(s1, result)
        r2 = store.save_result(s1, result)
        assert r1 != r2
        assert store.load_result(r1) == result
        store.update_client(first["code"], {"full_name": "Synthetic Renamed"})
        assert store.load_plan(p1) == saved
        mutable = store.load_result(r1)
        mutable["metrics"].clear()
        assert store.load_result(r1) == result
        assert store.load_plan(p2).seed == 7
        with pytest.raises(ValueError, match="match"):
            store.save_result(s2, result)
        for operation, identifier in [
            (store.load_plan, 9999),
            (store.load_scenario, 9999),
            (store.load_result, 9999),
        ]:
            with pytest.raises(LookupError):
                operation(identifier)
        with pytest.raises(LookupError):
            store.save_scenario(9999, "Missing", original)
        with pytest.raises(LookupError):
            store.save_result(9999, result)


def test_joint_request_and_components(tmp_path: Path) -> None:
    data = json.loads(Path("examples/family-per-goal-request.json").read_text())
    expected = ForecastRequest.model_validate(data).model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(expected, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    with PlannerStore.initialize(tmp_path / "joint.db") as store:
        client = store.create_client({"full_name": "Synthetic One"})
        pid = store.save_plan(client["code"], data)
        assert store.load_plan(pid).model_dump(mode="json") == expected
        assert store.list_plans(client["code"])[0]["source_digest"] == digest
        with store.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM goal").scalar() == len(
                data["plan"]["goals"]
            )
            rows = (
                connection.exec_driver_sql("SELECT payload FROM portfolio ORDER BY position").scalars().all()
            )
            assert len(rows) == len(data["allocation"]["segments"]) + 1
        scenario = store.save_scenario(pid, "Joint", data)
        result = json.loads(json.dumps(forecast(data)))
        rid = store.save_result(scenario, result)
        assert store.load_result(rid) == result


def test_invalid_request_and_result_leave_no_partial_rows(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path / "atomic.db") as store:
        client = store.create_client({"full_name": "Synthetic One"})
        bad = request()
        bad["currency"] = "INVALID"
        with pytest.raises(ValueError):
            store.save_plan(client["code"], bad)
        assert store.list_plans(client["code"]) == []
        pid = store.save_plan(client["code"], request())
        with pytest.raises(ValueError):
            store.save_scenario(pid, "  ", request())
        sid = store.save_scenario(pid, "Baseline", request())
        with pytest.raises(ValueError):
            store.save_result(sid, {"provenance": {}})
        bad_result = forecast(request())
        bad_result["metrics"]["bad_number"] = float("nan")
        with pytest.raises(ValueError):
            store.save_result(sid, bad_result)
        with store.engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM plan_run").scalar() == 0


def test_concurrent_versions(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.db"
    with PlannerStore.initialize(path) as store:
        code = store.create_client({"full_name": "Synthetic One"})["code"]
    data = request()

    def save(index: int) -> int:
        with PlannerStore.open(path) as store:
            return store.save_plan(code, data, note=f"Version {index}")

    with ThreadPoolExecutor(max_workers=3) as pool:
        identifiers = list(pool.map(save, range(6)))
    assert len(set(identifiers)) == 6
    with PlannerStore.open(path) as store:
        assert [row["version"] for row in store.list_plans(code)] == list(range(1, 7))


def test_database_failure_rolls_back_entire_version(tmp_path: Path) -> None:
    from sqlalchemy.exc import IntegrityError

    with PlannerStore.initialize(tmp_path / "rollback.db") as store:
        code = store.create_client({"full_name": "Synthetic One"})["code"]
        with store.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_asset BEFORE INSERT ON asset "
                "BEGIN SELECT RAISE(ABORT, 'test failure'); END"
            )
        with pytest.raises(IntegrityError, match="test failure"):
            store.save_plan(code, request())
        assert store.list_plans(code) == []
        with store.engine.connect() as connection:
            for table in ("client", "plan_snapshot", "person", "asset", "goal", "portfolio"):
                assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0
        with store.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER fail_asset")
        pid = store.save_plan(code, request())
        assert store.list_plans(code)[0]["version"] == 1
        assert store.load_plan(pid).currency == request()["currency"]
