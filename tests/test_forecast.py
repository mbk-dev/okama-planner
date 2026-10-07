"""Standalone financial forecast controls, with hand-computed zero-return cash flows."""

import importlib.util
import json

import pytest


def test_public_package_exists_without_private_application() -> None:
    assert importlib.util.find_spec("okama_planner") is not None


def request() -> dict:
    return {
        "currency": "USD",
        "mc_number": 20,
        "seed": 7,
        "plan": {
            "t0": "2026-01",
            "horizon_years": 3,
            "retirement_year": 2027,
            "buffer_lookahead_months": 0,
            "pension_replaces_expenses": True,
            "rates": dict.fromkeys(
                [
                    "inflation_rate",
                    "expense_indexation_rate",
                    "income_indexation_rate",
                    "goal_indexation_rate",
                    "discount_rate",
                    "buffer_rate",
                ],
                0.0,
            ),
            "assets": [
                {"label": "Investments", "amount": 1000, "currency": "USD", "asset_class": "portfolio"}
            ],
            "budget_items": [
                {"kind": "income", "label": "Salary", "monthly_amount": 100, "end_rule": "until_retirement"},
                {"kind": "expense", "label": "Living", "monthly_amount": 50},
            ],
            "goals": [
                {
                    "goal_id": None,
                    "label": "Purchase",
                    "kind": "lump",
                    "amount_pv": 300,
                    "pv_year": 2026,
                    "target_year": 2026,
                    "target_month": 7,
                    "becomes_asset": True,
                },
                {
                    "goal_id": None,
                    "label": "Pension",
                    "kind": "retirement_income",
                    "amount_pv": 50,
                    "pv_year": 2026,
                },
            ],
        },
        "return_samples": {
            "accumulation": {"start_month": "2024-01", "monthly_returns": [0.0] * 24},
            "withdrawal": {"start_month": "2024-01", "monthly_returns": [0.0] * 24},
        },
    }


def test_forecast_preserves_cashflows_goals_and_capital_without_database() -> None:
    from okama_planner import forecast

    result = forecast(request())
    assert result["metrics"]["probability_of_success"] == 1.0
    # 1000 + 12 * (100 - 50) - 300 - 24 * 50 = 100.
    assert result["metrics"]["terminal_p50"] == pytest.approx(100)
    assert result["portfolio_flow"]["2026-07"] == pytest.approx(-250)
    assert result["portfolio_flow"]["2027-01"] == pytest.approx(-50)
    assert result["goals"][0]["amount_nominal"] == 300
    assert result["goals"][0]["p_affordable"] == 1.0
    assert result["charts"]["capital"][-1]["p50"] == pytest.approx(400)
    assert result["charts"]["portfolio"][-1]["p50"] == pytest.approx(100)
    json.dumps(result, allow_nan=False)


def test_frozen_sample_and_seed_repeat_exactly_and_deferred_purchase_moves_flow() -> None:
    from okama_planner import forecast

    baseline = request()
    first = forecast(baseline)
    assert first == forecast(baseline)
    deferred = request()
    deferred["plan"]["goals"][0]["target_month"] = 10
    other = forecast(deferred)
    assert other["portfolio_flow"]["2026-07"] == 50
    assert other["portfolio_flow"]["2026-10"] == -250
    assert other["goals"][0]["month"] == "2026-10"
    assert first["provenance"]["input_sha256"] != other["provenance"]["input_sha256"]


def test_depletion_is_distinct_from_prefunded_purchase_affordability() -> None:
    from okama_planner import forecast

    data = request()
    data["plan"]["assets"][0]["amount"] = 100
    data["plan"]["savings_horizon_years"] = 2
    result = forecast(data)
    assert result["metrics"]["probability_of_success"] == 0.0
    assert result["goals"][0]["p_affordable"] == 1.0


@pytest.mark.parametrize("mutation", ["currency", "duplicate_label", "invalid_rate", "future_sample"])
def test_unsupported_inputs_are_rejected(mutation: str) -> None:
    from okama_planner import forecast

    data = request()
    if mutation == "currency":
        data["plan"]["assets"][0]["currency"] = "EUR"
    elif mutation == "duplicate_label":
        data["plan"]["goals"][1]["label"] = "Purchase"
    elif mutation == "invalid_rate":
        data["plan"]["rates"]["buffer_rate"] = -1
    else:
        data["return_samples"]["accumulation"]["start_month"] = "2026-01"
    with pytest.raises(ValueError):
        forecast(data)


@pytest.mark.parametrize(
    "mutation", ["end_rule", "month", "liability_nan", "unknown_field", "conflicting_pin"]
)
def test_public_request_rejects_ambiguous_or_invalid_money_inputs(mutation: str) -> None:
    from okama_planner import forecast

    data = request()
    if mutation == "end_rule":
        data["plan"]["budget_items"][0]["end_rule"] = "retirement"
    elif mutation == "month":
        data["plan"]["goals"][0]["target_month"] = 13
    elif mutation == "liability_nan":
        data["plan"]["liabilities"] = [
            {
                "label": "Loan",
                "principal": float("nan"),
                "annual_rate": 0.1,
                "monthly_payment": 100,
                "term_months": 12,
                "start_month": "2026-01",
            }
        ]
    elif mutation == "unknown_field":
        data["plan"]["unsupported_setting"] = {"version": 1}
    else:
        data["plan"]["accumulation_last_date_pin"] = "2025-11"
    with pytest.raises(ValueError):
        forecast(data)


@pytest.mark.parametrize("already_saved", [0, 5000])
def test_reserve_goal_measures_only_required_topup(already_saved: float) -> None:
    from okama_planner import forecast

    data = request()
    data["plan"]["budget_items"] = []
    data["plan"]["assets"].append(
        {"label": "Existing reserve", "amount": already_saved, "currency": "USD", "asset_class": "reserve"}
    )
    data["plan"]["goals"] = [
        {
            "goal_id": None,
            "label": "Emergency reserve",
            "kind": "reserve_topup",
            "amount_pv": 5000,
            "pv_year": 2026,
            "target_year": 2026,
            "target_month": 7,
        }
    ]
    result = forecast(data)
    assert result["goals"][0]["p_affordable"] == (1 if already_saved else 0)


@pytest.mark.parametrize("mutation", ["goal_kind", "amount_basis", "asset_class", "t0"])
def test_invalid_categories_cannot_silently_change_calculation(mutation: str) -> None:
    from okama_planner import forecast

    data = request()
    if mutation == "goal_kind":
        data["plan"]["goals"][0].update(kind="unknown", target_year=2100)
    elif mutation == "amount_basis":
        data["plan"]["goals"][1]["amount_basis"] = "expense_shrae"
    elif mutation == "asset_class":
        data["plan"]["assets"].append(
            {"label": "Other", "amount": 500, "currency": "USD", "asset_class": "unknown"}
        )
    else:
        data["plan"]["t0"] = "2026-01-15"
    with pytest.raises(ValueError):
        forecast(data)


def test_forecast_bounds_loan_work_to_the_horizon() -> None:
    from okama_planner import forecast

    data = request()
    data["plan"]["liabilities"] = [
        {
            "label": "Slow synthetic loan",
            "principal": 1e6,
            "annual_rate": 0,
            "monthly_payment": 0.01,
            "term_months": 12,
            "start_month": "2026-01",
        }
    ]
    result = forecast(data)
    assert result["ledger"]["liability_balance"][-1] == pytest.approx(1e6 - 0.36)
    assert result["metrics"]["terminal_p50"] == pytest.approx(100 - 0.36)
