"""Independent purchase accounts: literal, hand-computed balances and cash conservation."""

from __future__ import annotations

import pytest

from okama_planner.inputs import AssetIn, BudgetItemIn, GoalIn, PlanInputs, Rates
from okama_planner.ledger.build import build_ledger


def _inputs(**updates: object) -> PlanInputs:
    data = {
        "t0": "2026-10",
        "horizon_years": 2,
        "retirement_year": 2027,
        "buffer_lookahead_months": 0,
        "reserves_until_retirement": True,
        "savings_mode": "separate",
        "goal_savings_rates": {"Car": 0.0, "House": 4095.0},
        "rates": Rates(
            inflation_rate=0,
            expense_indexation_rate=0,
            income_indexation_rate=0,
            goal_indexation_rate=0,
            discount_rate=0,
            buffer_rate=0,
        ),
        "budget_items": (BudgetItemIn(kind="income", label="Salary", monthly_amount=100),),
        "goals": (
            GoalIn(
                goal_id=1,
                label="Car",
                kind="lump",
                amount_pv=60,
                pv_year=2026,
                target_year=2026,
                target_month=12,
            ),
            GoalIn(
                goal_id=2,
                label="House",
                kind="lump",
                amount_pv=120,
                pv_year=2026,
                target_year=2026,
                target_month=12,
            ),
        ),
    }
    data.update(updates)
    return PlanInputs.model_validate(data)


def test_each_account_starts_immediately_earns_its_own_rate_and_pays_only_its_goal() -> None:
    # House monthly factor 2: 20 at Oct end -> 40 + 20 in Nov -> 120 at purchase.
    # Car: 30 + 30 = 60. Oct/Nov surplus 100 - 30 - 20 = 50.
    ledger = build_ledger(_inputs())
    parts = {part.goal_label: part.balance for part in ledger.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([30, 60, 0])
    assert parts["House"][:3] == pytest.approx([20, 60, 0])
    assert ledger.buffer_balance[:3] == pytest.approx([50, 120, 0])
    assert list(ledger.portfolio_flow.values())[:3] == pytest.approx([50, 50, 100])
    deposits = ledger.lines_of("buffer_in")
    assert {(line.goal_id, line.amount) for line in deposits} == {(1, 30), (2, 20)}


def test_insufficient_income_is_split_proportionally_and_shortfall_is_not_hidden() -> None:
    ledger = build_ledger(
        _inputs(budget_items=(BudgetItemIn(kind="income", label="Salary", monthly_amount=25),))
    )
    parts = {part.goal_label: part.balance for part in ledger.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([15, 30, 0])
    assert parts["House"][:3] == pytest.approx([10, 30, 0])
    # Purchase: car shortfall 30, house shortfall 60, income 25 -> portfolio pays 65.
    assert list(ledger.portfolio_flow.values())[:3] == pytest.approx([0, 0, -65])
    assert ledger.goal_portfolio_shares == pytest.approx(
        {
            "Car": 21.666666666666668,
            "House": 43.333333333333336,
        }
    )


def test_opening_savings_reduce_contributions_but_the_emergency_reserve_stays_separate() -> None:
    ledger = build_ledger(
        _inputs(
            assets=(
                AssetIn(label="Saved", amount=45, currency="RUB", asset_class="savings"),
                AssetIn(label="Emergency", amount=1000, currency="RUB", asset_class="reserve"),
            )
        )
    )
    # PV needs Car 60, House 30; opening 45 is divided 30/15. Remaining deposits 15/10.
    parts = {part.goal_label: part.balance for part in ledger.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([45, 60, 0])
    assert parts["House"][:3] == pytest.approx([25, 60, 0])
    assert list(ledger.portfolio_flow.values())[:3] == pytest.approx([75, 75, 100])
    assert ledger.reserve_balance[:3] == pytest.approx([1000, 1000, 1000])


def test_the_car_sale_reduces_only_the_car_account_and_is_not_counted_twice() -> None:
    original = _inputs()
    car = original.goals[0].model_copy(update={"replaces_asset": "Old car"})
    ledger = build_ledger(
        _inputs(
            goals=(car, original.goals[1]),
            assets=(
                AssetIn(label="Old car", amount=20, currency="RUB", asset_class="non_working", growth_rate=0),
            ),
        )
    )
    parts = {part.goal_label: part.balance for part in ledger.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([20, 40, 0])
    assert parts["House"][:3] == pytest.approx([20, 60, 0])
    assert list(ledger.portfolio_flow.values())[:3] == pytest.approx([60, 60, 100])


def test_pooled_mode_replays_the_old_sequential_allocation() -> None:
    data = _inputs().model_dump()
    data.pop("savings_mode")
    data.pop("goal_savings_rates")
    old = build_ledger(PlanInputs.model_validate(data))
    rollback = build_ledger(_inputs(savings_mode="pooled", goal_savings_rates={}))
    assert rollback == old
    parts = {part.goal_label: part.balance for part in old.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([60, 60, 0])
    assert parts["House"][:3] == pytest.approx([40, 120, 0])
    # Legacy deficit month retains the 100 left in the pool until the following month.
    assert parts[None][:3] == pytest.approx([0, 0, 100])
    assert list(old.portfolio_flow.values())[:3] == pytest.approx([0, 20, 0])


def test_house_money_does_not_pay_a_car_shortfall_or_a_household_deficit() -> None:
    original = _inputs()
    # Car due Nov, house due Dec, zero yields: planned deposits are 60 and 60.
    car = original.goals[0].model_copy(update={"target_month": 11})
    ledger = build_ledger(
        _inputs(
            goals=(car, original.goals[1]),
            goal_savings_rates={"Car": 0, "House": 0},
            budget_items=(
                BudgetItemIn(
                    kind="income",
                    label="Salary",
                    monthly_amount=60,
                    end_month="2026-10",
                    end_rule="until_month",
                ),
                BudgetItemIn(kind="expense", label="Bills", monthly_amount=10, start_month="2026-11"),
            ),
        )
    )
    parts = {part.goal_label: part.balance for part in ledger.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([30, 0, 0])
    assert parts["House"][:3] == pytest.approx([30, 30, 0])
    assert list(ledger.portfolio_flow.values())[:3] == pytest.approx([0, -40, -100])


def test_excess_opening_savings_are_released_without_overfunding_goal_accounts() -> None:
    ledger = build_ledger(
        _inputs(assets=(AssetIn(label="Saved", amount=100, currency="RUB", asset_class="savings"),))
    )
    parts = {part.goal_label: part.balance for part in ledger.buffer_by_goal}
    assert parts["Car"][:3] == pytest.approx([60, 60, 0])
    assert parts["House"][:3] == pytest.approx([30, 60, 0])
    assert list(ledger.portfolio_flow.values())[:3] == pytest.approx([110, 100, 100])


def test_a_purchase_at_t0_uses_opening_savings_and_reports_the_rest() -> None:
    original = _inputs()
    car = original.goals[0].model_copy(update={"target_month": 10})
    ledger = build_ledger(
        _inputs(
            goals=(car,),
            goal_savings_rates={"Car": 0},
            assets=(AssetIn(label="Saved", amount=20, currency="RUB", asset_class="savings"),),
            budget_items=(),
        )
    )
    assert ledger.buffer_balance[0] == 0
    assert ledger.portfolio_flow["2026-10"] == pytest.approx(-40)


def test_deferring_a_goal_recomputes_its_contribution_without_changing_its_rate() -> None:
    from okama_planner.forecast.variants import with_goal_deferred

    original = _inputs(goal_savings_rates={"Car": 0, "House": 0}, retirement_year=2028, horizon_years=3)
    deferred = build_ledger(with_goal_deferred(original, 2, 2027))
    # House moved from month 2 to month 14: 120/14, while car remains 30/month.
    parts = {part.goal_label: part.balance for part in deferred.buffer_by_goal}
    assert parts["Car"][0] == pytest.approx(30)
    assert parts["House"][0] == pytest.approx(8.571428571428571)
    assert parts["House"][13] == pytest.approx(120)
    assert parts["House"][14] == pytest.approx(0)
