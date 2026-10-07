"""Public calculations must run without the private application's storage or exports."""

import json
import socket

import pytest

from okama_planner import PlanInputs, forecast
from okama_planner.inputs import AssetIn, BudgetItemIn, GoalIn, Rates
from okama_planner.ledger.build import build_ledger


def inputs() -> PlanInputs:
    return PlanInputs(
        t0="2026-01",
        horizon_years=4,
        retirement_year=2028,
        buffer_lookahead_months=0,
        rates=Rates(
            inflation_rate=0,
            expense_indexation_rate=0,
            income_indexation_rate=0,
            goal_indexation_rate=0,
            discount_rate=0,
            buffer_rate=0,
        ),
        assets=(AssetIn(label="Opening savings", amount=10000, currency="USD", asset_class="portfolio"),),
        budget_items=(
            BudgetItemIn(kind="income", label="Income", monthly_amount=100, end_rule="until_retirement"),
        ),
        goals=(
            GoalIn(
                goal_id=None, label="Purchase", kind="lump", amount_pv=1000, pv_year=2026, target_year=2027
            ),
        ),
        accumulation_last_date_pin="2025-12",
        withdrawal_last_date_pin="2025-12",
    )


def run(value: PlanInputs) -> dict:
    return forecast(
        {
            "plan": value.model_dump(mode="json"),
            "currency": "USD",
            "mc_number": 20,
            "seed": 7,
            "return_samples": {
                name: {"start_month": "2024-01", "monthly_returns": [0.0] * 24}
                for name in ("accumulation", "withdrawal")
            },
        }
    )


def test_offline_forecast_has_hand_computed_flows_and_balances(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("offline calculation opened a network socket")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    result = run(inputs())
    assert result["metrics"]["terminal_p50"] == pytest.approx(11400)
    assert result["metrics"]["probability_of_success"] == 1
    assert result["goals"][0]["goal_id"] is None
    assert result["goals"][0]["p_affordable"] == 1
    assert result["goals"][0]["p_alive"] == 1
    assert len(result["portfolio_flow"]) == 48
    assert result["portfolio_flow"]["2027-01"] == -900
    assert result["portfolio_flow"]["2028-01"] == 0
    assert result["charts"]["portfolio"][0]["month"] == "2025-12"
    json.dumps(result, allow_nan=False)


def test_seed_and_pinned_histories_repeat_and_purchase_moves() -> None:
    original = inputs()
    assert run(original) == run(original)
    moved = original.model_copy(
        update={"goals": (original.goals[0].model_copy(update={"target_year": 2029}),)}
    )
    result = run(moved)
    assert result["portfolio_flow"]["2027-01"] == 100
    assert result["portfolio_flow"]["2029-01"] == -1000
    assert result["goals"][0]["month"] == "2029-01"
    assert original.goals[0].target_year == 2027


def test_mixed_currency_does_not_silently_add_unconverted_money() -> None:
    original = inputs()
    foreign = original.model_copy(
        update={"assets": (original.assets[0].model_copy(update={"currency": "EUR"}),)}
    )
    with pytest.raises(ValueError, match="currenc"):
        run(foreign)


def test_ledger_is_callable_without_database_and_keeps_goal_cost() -> None:
    ledger = build_ledger(inputs())
    assert ledger.portfolio_flow["2027-01"] == -900
    assert ledger.liability_balance == (0,) * 48


@pytest.mark.parametrize(("start_month", "expected"), [("2026-06", 10000), ("2025-11", 9200)])
def test_opening_capital_uses_outstanding_debt(start_month: str, expected: float) -> None:
    from okama_planner.inputs import LiabilityIn

    original = inputs()
    value = original.model_copy(
        update={
            "liabilities": (
                LiabilityIn(
                    label="Synthetic loan",
                    principal=1000,
                    annual_rate=0,
                    monthly_payment=100,
                    term_months=10,
                    start_month=start_month,
                ),
            )
        }
    )
    assert run(value)["charts"]["capital"][0]["p50"] == expected
