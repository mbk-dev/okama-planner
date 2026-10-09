"""Synthetic examples use dated currency-specific inputs, independently of presentation."""

import json
import runpy
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_synthetic_request_uses_currency_specific_macro_history_and_independent_amounts() -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, metadata = module["build_request"]("EUR", snapshots)
    eur = snapshots["currencies"]["EUR"]
    assert request["currency"] == "EUR"
    assert request["plan"]["assets"][0]["amount"] == 90000
    assert request["plan"]["rates"]["inflation_rate"] == eur["inflation_rate"]
    assert request["plan"]["rates"]["buffer_rate"] == eur["risk_free_rate"]
    assert request["return_samples"]["accumulation"]["monthly_returns"] == (
        eur["portfolios"]["accumulation"]["monthly_returns"]
    )
    assert request["plan"]["t0"] == "2026-10"
    assert request["plan"]["withdrawal_years"] == 30
    assert metadata["currency"] == "EUR"
    assert "no FX conversion" in metadata["amount_method"]
    assert module["DEFAULT_CURRENCIES"] == {"en": "USD", "ru": "RUB", "zh": "CNY", "de": "EUR", "es": "EUR"}


def test_missing_chinese_policy_rate_requires_explicit_dated_input() -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    snapshots["currencies"]["CNY"]["risk_free_rate"] = None
    with pytest.raises(ValueError, match="CNY policy rate"):
        module["build_request"]("CNY", snapshots)


def test_currency_snapshots_are_finite_and_cny_reference_is_explicit() -> None:
    import math

    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    for entry in snapshots["currencies"].values():
        for portfolio in entry["portfolios"].values():
            assert math.isfinite(portfolio["cagr"])
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    request, metadata = module["build_request"]("CNY", snapshots, language="zh")
    assert request["plan"]["rates"]["buffer_rate"] == .03
    assert metadata["rate_symbol"] == "CHN_LPR1.RATE"
    assert "user-selected" in metadata["rate_kind"]
    assert request["plan"]["goals"][0]["label"] == "汽车"


def test_full_synthetic_structure_preserves_purchase_and_retirement_funding() -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, _ = module["build_request"]("USD", snapshots)
    plan = request["plan"]
    assert {asset["asset_class"] for asset in plan["assets"]} == {
        "portfolio", "reserve", "savings", "non_working",
    }
    assert len(plan["liabilities"]) == 1
    assert plan["goals"][0]["replaces_asset"] == "Current car"
    assert plan["goals"][2]["amount_basis"] == "expense_share"
    assert plan["goals"][2]["amount_pv"] == 1
    assert plan["savings_mode"] == "separate"
    assert len(plan["goal_savings_rates"]) == 2
    assert len(plan["budget_items"]) == 2
    assert plan["budget_items"][0]["monthly_amount"] == 15000


@pytest.mark.parametrize("parameter", ["opening_capital", "income"])
def test_calibration_changes_only_selected_lever_and_validates_independently(parameter: str) -> None:
    from copy import deepcopy

    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, _ = module["build_request"]("USD", snapshots)
    original = deepcopy(request)
    calls = []
    baseline = (request["plan"]["assets"][0]["amount"] if parameter == "opening_capital"
                else request["plan"]["budget_items"][0]["monthly_amount"])

    def evaluate(candidate: dict) -> dict:
        calls.append(deepcopy(candidate))
        amount = (candidate["plan"]["assets"][0]["amount"] if parameter == "opening_capital"
                  else candidate["plan"]["budget_items"][0]["monthly_amount"])
        return {"metrics": {"probability_of_success": min(.99, amount / (2 * baseline))}}

    calibrated, result, metadata = module["calibrate_request"](
        request, parameter=parameter, evaluator=evaluate, mc_number=2000,
    )
    assert request == original
    assert result["metrics"]["probability_of_success"] >= .90
    assert metadata["selection_probability"] >= .92
    assert metadata["calibrated_value"] > metadata["baseline_value"]
    assert calls[-1]["seed"] != calls[0]["seed"]
    assert {call["seed"] for call in calls[:-1]} == {calls[0]["seed"]}
    assert all(call["mc_number"] == 2000 for call in calls)
    restored = deepcopy(calibrated)
    restored["seed"] = original["seed"]
    restored["mc_number"] = original["mc_number"]
    if parameter == "opening_capital":
        restored["plan"]["assets"][0]["amount"] = baseline
    else:
        restored["plan"]["budget_items"][0]["monthly_amount"] = baseline
    assert restored == original


def test_calibration_refuses_unsatisfied_limit_and_independent_validation() -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, _ = module["build_request"]("USD", snapshots)
    with pytest.raises(ValueError, match="limit"):
        module["calibrate_request"](request, max_multiplier=2,
                                    evaluator=lambda _: {"metrics": {"probability_of_success": .1}})
    with pytest.raises(ValueError, match="Independent"):
        module["calibrate_request"](
            request, evaluator=lambda value: {"metrics": {
                "probability_of_success": .99 if value["seed"] == 707 else .89,
            }},
        )


@pytest.mark.parametrize("currency", ["USD", "EUR", "CNY", "RUB"])
def test_full_synthetic_request_builds_valid_cash_flow(currency: str) -> None:
    from okama_planner.api import ForecastRequest
    from okama_planner.ledger.build import build_ledger

    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, _ = module["build_request"](currency, snapshots)
    ledger = build_ledger(ForecastRequest.model_validate(request).plan)
    assert len(ledger.months) == 528


@pytest.mark.parametrize("currency", ["USD", "EUR", "CNY", "RUB"])
def test_real_currency_forecasts_pass_independent_success_threshold(currency: str) -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, _ = module["build_request"](currency, snapshots)
    calibrated, result, calibration = module["calibrate_request"](request, mc_number=2000)
    assert calibration["selection_probability"] >= .92
    assert result["metrics"]["probability_of_success"] >= .90
    assert all(goal["p_affordable"] >= .90 for goal in result["goals"])
    assert result["provenance"]["seed"] == calibrated["seed"] == 1707
    assert result["provenance"]["mc_number"] == 2000
    assert calibrated["plan"]["goals"] == request["plan"]["goals"]
