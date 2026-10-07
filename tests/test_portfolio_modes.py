"""Switching modes changes allocation, not the household or sampled market paths."""

import copy
import json

import numpy as np
import pytest

from okama_planner import ForecastRequest, forecast
from test_allocation import allocation, request, strategy
from test_segmented import simulate


def test_identical_strategies_pathwise_equivalent_including_depletion_and_later_income() -> None:
    from okama_planner import compare_portfolio_modes, with_portfolio_mode

    raw = request(100)
    raw["plan"]["budget_items"] = [
        {"kind": "expense", "label": "Needs", "monthly_amount": 40},
        {"kind": "income", "label": "Later income", "monthly_amount": 50, "start_month": "2026-06"},
    ]
    raw["plan"]["goals"] = []
    raw["allocation"] = allocation(100, ())
    raw["joint_history"]["asset_returns"]["A"] = [0.05, -0.05] * 6
    raw["mc_number"] = 40
    # Add a pension segment to exercise transfers after the pool hits zero.
    raw["plan"]["goals"] = [
        {"goal_id": 1, "kind": "retirement_income", "label": "Pension", "amount_pv": 5, "pv_year": 2026}
    ]
    raw["allocation"] = allocation(100, (1,))
    raw["allocation"]["segments"][0]["opening_amount"] = 20
    raw["allocation"]["segments"][1]["opening_amount"] = 80
    original = ForecastRequest.model_validate(raw)
    baseline = with_portfolio_mode(original, portfolio_mode="single")
    assert original.portfolio_mode == "per_goal"
    left, right = simulate(baseline.model_dump(mode="json")), simulate(raw)
    np.testing.assert_allclose(left.portfolio, right.portfolio, atol=1e-10)
    np.testing.assert_allclose(left.capital, right.capital, atol=1e-10)
    assert np.any(left.portfolio[3] == 0)
    assert np.all(left.portfolio[7] > 0)
    compared = compare_portfolio_modes(baseline, original)
    assert compared["differences"]["metrics"]["terminal_p50"] == pytest.approx(0)
    assert compared["baseline"]["portfolio_mode"] == "single"
    assert compared["variant"]["portfolio_mode"] == "per_goal"
    assert (
        compared["baseline"]["provenance"]["scenario_rows_sha256"]
        == compared["variant"]["provenance"]["scenario_rows_sha256"]
    )
    assert compared["risk_structure"]["single_strategy"] == raw["allocation"]["single_strategy"]
    json.dumps(compared, allow_nan=False)


def test_two_anticorrelated_segments_aggregate_paths_before_quantiles() -> None:
    raw = request(100)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [
        {
            "goal_id": 1,
            "kind": "lump",
            "label": "Future",
            "amount_pv": 1,
            "pv_year": 2026,
            "target_year": 2029,
        }
    ]
    raw["allocation"] = allocation(100, (1,))
    for segment in raw["allocation"]["segments"]:
        segment["opening_amount"] = 50
    raw["allocation"]["segments"][1]["strategy"] = strategy("B")
    raw["joint_history"]["asset_returns"] = {"A": [0.1, -0.1] * 6, "B": [-0.1, 0.1] * 6}
    raw["mc_number"] = 40
    actual = simulate(raw)
    np.testing.assert_allclose(actual.portfolio[1], 100)
    result = forecast(raw)
    assert result["charts"]["portfolio"][1]["p10"] == pytest.approx(100)
    assert result["charts"]["portfolio"][1]["p90"] == pytest.approx(100)


def test_different_segment_risk_is_a_visible_controlled_comparison() -> None:
    from okama_planner import compare_portfolio_modes, with_portfolio_mode

    raw = request(100)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [
        {
            "goal_id": 1,
            "kind": "lump",
            "label": "Future",
            "amount_pv": 1,
            "pv_year": 2026,
            "target_year": 2029,
        }
    ]
    raw["allocation"] = allocation(100, (1,))
    for segment in raw["allocation"]["segments"]:
        segment["opening_amount"] = 50
    raw["allocation"]["segments"][1]["strategy"] = strategy("B")
    raw["joint_history"]["asset_returns"] = {"A": [0.01] * 12, "B": [0] * 12}
    comparison = compare_portfolio_modes(with_portfolio_mode(raw, portfolio_mode="single"), raw)
    expected = 50 * (1.01**24) + 50 - 100 * (1.01**24)
    assert comparison["differences"]["metrics"]["terminal_p50"] == pytest.approx(expected)
    assert comparison["risk_structure"]["strategies_differ"] is True


@pytest.mark.parametrize("change", ["seed", "mc_number", "family", "history", "mode"])
def test_comparison_rejects_uncontrolled_changes(change: str) -> None:
    from okama_planner import compare_portfolio_modes, with_portfolio_mode

    raw = request()
    single = with_portfolio_mode(raw, portfolio_mode="single")
    modified = copy.deepcopy(raw)
    if change == "seed":
        modified["seed"] += 1
    if change == "mc_number":
        modified["mc_number"] += 1
    if change == "family":
        modified["plan"]["budget_items"][0]["monthly_amount"] += 1
    if change == "history":
        modified["joint_history"]["asset_returns"]["A"][0] = 0.1
    if change == "mode":
        modified["portfolio_mode"] = "single"
    with pytest.raises(ValueError):
        compare_portfolio_modes(single, modified)


def test_legacy_default_dump_and_digest_exclude_all_new_fields() -> None:
    from okama_planner.api import _digest
    from test_api import inputs, run

    original = {"plan": inputs(), "currency": "USD"}
    value = ForecastRequest.model_validate(original)
    assert not {"joint_history", "allocation", "portfolio_mode"} & value.model_dump().keys()
    baseline = run(inputs())
    staged = {
        "plan": inputs(),
        "currency": "USD",
        "mc_number": 20,
        "seed": 7,
        "return_samples": {
            k: {"start_month": "2024-01", "monthly_returns": [0] * 24} for k in ("accumulation", "withdrawal")
        },
    }
    assert baseline["provenance"]["input_sha256"] == _digest(
        ForecastRequest.model_validate(staged).model_dump(mode="json")
    )
    assert forecast({**staged, "portfolio_mode": "single"}) == baseline


def test_comparison_samples_shared_cube_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from okama_planner import compare_portfolio_modes, with_portfolio_mode
    import okama_planner.scenarios as scenarios

    count = []
    original = scenarios.sample_joint_returns

    def counted(*args, **kwargs):
        count.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(scenarios, "sample_joint_returns", counted)
    raw = request()
    compare_portfolio_modes(with_portfolio_mode(raw, portfolio_mode="single"), raw)
    assert len(count) == 1


@pytest.mark.parametrize("name", ["baseline", "deferred"])
def test_saved_legacy_json_results_remain_exact(name: str) -> None:
    from pathlib import Path

    examples = Path(__file__).parents[1] / "examples"
    raw = json.loads((examples / f"{name}-request.json").read_text())
    saved = json.loads((examples / f"{name}-result.json").read_text())
    actual = json.loads(json.dumps(forecast(raw), allow_nan=False))
    # Saved fixtures record the producer environment; consumers resolve dependencies.
    # Verify live metadata separately and compare every calculation field exactly.
    from importlib.metadata import version

    import okama

    runtime_versions = {"okama_version": okama.__version__}
    runtime_versions.update({f"{name}_version": version(name) for name in ("numpy", "pandas", "scipy")})
    for key, current in runtime_versions.items():
        assert actual["provenance"][key] == current
        saved["provenance"][key] = current
    assert actual == saved


def test_mode_helper_rejects_invalid_override_without_changing_source() -> None:
    from okama_planner import with_portfolio_mode

    raw = request()
    before = copy.deepcopy(raw)
    bad = copy.deepcopy(raw["allocation"])
    bad["segments"][0]["opening_amount"] += 1
    with pytest.raises(ValueError):
        with_portfolio_mode(raw, portfolio_mode="single", allocation=bad)
    assert raw == before
