"""Two probabilities per goal. Confusing them is the reporting error the spec warns about."""

from __future__ import annotations

import pandas as pd
import pytest

from okama_planner.forecast.goal_results import goal_outcomes, p_affordable, p_alive
from okama_planner.ledger.build import build_ledger
from okama_planner.ledger.types import Ledger
from planner_tests.ledger.test_build import INPUTS
from planner_tests.ledger.test_goal_savings import _inputs as separate_inputs
from okama_planner.inputs import BudgetItemIn

# Four scenarios. In 2028-07 (the month before the car) they hold 5 000 000 / 4 000 000 / 0 / 100.
# The second scenario drops below the car's nominal amount in 2028-08 on purpose: it makes
# p_affordable differ between the two months (0.5 against 0.25), so a probability measured in the
# wrong one of them is visible. p_alive stays 0.5 in 2028-08 either way.
WEALTH = pd.DataFrame(
    [
        [5_000_000.0, 4_000_000.0, 0.0, 100.0],
        [5_100_000.0, 3_000_000.0, 0.0, 0.0],
    ],
    index=pd.PeriodIndex(["2028-07", "2028-08"], freq="M"),
)


def test_p_alive_counts_scenarios_with_a_positive_balance() -> None:
    assert p_alive(WEALTH, "2028-07") == pytest.approx(0.75)
    assert p_alive(WEALTH, "2028-08") == pytest.approx(0.5)


def test_a_funded_separate_goal_is_not_penalised_for_an_unrelated_household_deficit() -> None:
    original = separate_inputs()
    inputs = separate_inputs(
        goals=(original.goals[0].model_copy(update={"target_month": 11}), original.goals[1]),
        goal_savings_rates={"Car": 0, "House": 0},
        budget_items=(
            BudgetItemIn(
                kind="income", label="Salary", monthly_amount=120, end_rule="until_month", end_month="2026-10"
            ),
            BudgetItemIn(kind="expense", label="Bills", monthly_amount=10, start_month="2026-11"),
        ),
    )
    ledger = build_ledger(inputs)
    # The car account holds all 60; the portfolio's -10 in Nov pays bills only.
    assert ledger.portfolio_flow["2026-11"] == pytest.approx(-10)
    wealth = pd.DataFrame(
        [[0, 5, 20], [0, 0, 10], [0, 0, 0]], index=pd.period_range("2026-10", periods=3, freq="M")
    )
    outcomes = {outcome.label: outcome for outcome in goal_outcomes(wealth, inputs, ledger)}
    assert outcomes["Car"].p_affordable == pytest.approx(1)
    # House holds 60 of 120. The other 10 of Dec withdrawal is bills, not house price.
    assert ledger.goal_portfolio_shares["House"] == pytest.approx(60)


def test_roundoff_cannot_make_a_funded_goal_unaffordable_with_a_zero_portfolio() -> None:
    from okama_planner.inputs import AssetIn

    original = separate_inputs()
    inputs = separate_inputs(
        goals=(original.goals[0],),
        goal_savings_rates={"Car": 0.12},
        budget_items=(),
        assets=(AssetIn(label="Saved", amount=58.87734890429018, currency="RUB", asset_class="savings"),),
    )
    ledger = build_ledger(inputs)
    wealth = pd.DataFrame([[0], [0]], index=pd.period_range("2026-11", periods=2, freq="M"))
    assert goal_outcomes(wealth, inputs, ledger)[0].p_affordable == pytest.approx(1)


def test_large_goal_roundoff_is_below_monetary_precision_not_a_real_shortfall() -> None:
    from okama_planner.inputs import AssetIn

    original = separate_inputs()
    goal = original.goals[0].model_copy(
        update={
            "amount_pv": 100_000_000,
            "target_year": 2029,
            "target_month": 4,
        }
    )
    inputs = separate_inputs(
        goals=(goal,),
        goal_savings_rates={"Car": 0.18},
        budget_items=(),
        retirement_year=2030,
        horizon_years=5,
        assets=(AssetIn(label="Saved", amount=66_114_235.70082781, currency="RUB", asset_class="savings"),),
    )
    ledger = build_ledger(inputs)
    wealth = pd.DataFrame([[0], [0]], index=pd.period_range("2029-03", periods=2, freq="M"))
    assert goal_outcomes(wealth, inputs, ledger)[0].p_affordable == pytest.approx(1)


def test_p_affordable_counts_scenarios_that_could_pay_the_nominal_amount() -> None:
    # Only two of the four hold at least 4 000 000 the month before.
    assert p_affordable(WEALTH, "2028-07", amount=4_000_000.0) == pytest.approx(0.5)
    assert p_affordable(WEALTH, "2028-07", amount=6_000_000.0) == pytest.approx(0.0)


def test_the_two_numbers_differ_and_that_is_the_point() -> None:
    assert p_alive(WEALTH, "2028-07") != p_affordable(WEALTH, "2028-07", amount=4_000_000.0)


def test_a_lump_goal_is_measured_the_month_before_it_falls_due() -> None:
    outcomes = goal_outcomes(WEALTH, INPUTS, build_ledger(INPUTS))
    car = next(outcome for outcome in outcomes if outcome.label == "Автомобиль")

    assert car.month == "2028-08"
    assert car.amount_nominal == pytest.approx(3_000_000.0 * 1.09**2)
    assert car.amount_nominal == pytest.approx(3_564_300.0, abs=0.01)
    # 3 564 300 nominal. In 2028-07, the month before: two of the four scenarios hold at least
    # that much (5 000 000 and 4 000 000), so p_affordable = 0.5; three of the four are still
    # above zero (5 000 000, 4 000 000, 100), so p_alive = 0.75.
    assert car.p_affordable == pytest.approx(0.5)
    assert car.p_alive == pytest.approx(0.75)


def test_both_probabilities_are_measured_in_the_same_month() -> None:
    """They are only comparable at one moment; measuring p_alive in the goal's own month would
    subtract the goal itself and give 0.5 here instead of 0.75."""
    outcomes = goal_outcomes(WEALTH, INPUTS, build_ledger(INPUTS))
    car = next(outcome for outcome in outcomes if outcome.label == "Автомобиль")

    assert car.p_alive == pytest.approx(p_alive(WEALTH, "2028-07"))
    assert car.p_alive != pytest.approx(p_alive(WEALTH, "2028-08"))
    assert car.p_affordable == pytest.approx(p_affordable(WEALTH, "2028-07", car.amount_nominal))
    assert car.p_affordable != pytest.approx(p_affordable(WEALTH, "2028-08", car.amount_nominal))


def test_a_goal_whose_month_is_outside_the_table_is_skipped() -> None:
    outcomes = goal_outcomes(WEALTH, INPUTS, build_ledger(INPUTS))

    assert [outcome.label for outcome in outcomes] == ["Автомобиль"]


def test_a_goal_in_the_plans_first_year_is_reported() -> None:
    """A goal dated in t0's calendar year produces an outcome — it is charged, so it must appear.

    The wealth table's first row is t0 - 1, so both the goal's month and the month before it exist.
    The current code skips n <= 0, but ledger.goals accepts n == 0 (raises only for n < 0), so a
    goal whose target_year equals t0's calendar year becomes a real outflow that never appears in
    the goal table.
    """
    # A wealth table that includes t0 - 1 (2026-07) and t0 (2026-08) so a goal in 2026-08 has both
    # the "before" row and the "due" row.
    wealth_with_opening = pd.DataFrame(
        [
            [5_000_000.0, 4_000_000.0, 0.0, 100.0],
            [4_800_000.0, 3_900_000.0, 0.0, 50.0],
        ],
        index=pd.PeriodIndex(["2026-07", "2026-08"], freq="M"),
    )
    # Move the car to target_year=2026, t0=2026-08 → year_index = 0, month 2026-08.
    inputs_with_first_year_goal = INPUTS.model_copy(
        update={
            "t0": "2026-08",
            "goals": [goal.model_copy(update={"target_year": 2026}) for goal in INPUTS.goals],
        }
    )

    outcomes = goal_outcomes(
        wealth_with_opening, inputs_with_first_year_goal, build_ledger(inputs_with_first_year_goal)
    )

    # The car (target_year=2026) must appear in the outcomes.
    labels = [outcome.label for outcome in outcomes]
    assert "Автомобиль" in labels


# The car (2028, two years out) as a savings goal. The ledger is hand-built: only the month of the
# purchase matters, and what matters about it is how much the portfolio was asked to pay.
SAVINGS_INPUTS = INPUTS.model_copy(update={"savings_horizon_years": 5})


def _ledger(portfolio_paid: float) -> Ledger:
    return Ledger(t0="2026-08", months=("2028-07", "2028-08"), portfolio_flow={"2028-08": -portfolio_paid})


def _car(outcomes: tuple) -> object:  # type: ignore[type-arg]
    return next(outcome for outcome in outcomes if outcome.label == "Автомобиль")


def test_a_savings_goal_paid_from_the_buffer_is_affordable_in_every_scenario() -> None:
    # Two of the four scenarios hold the nominal amount; that is irrelevant when the deposit paid.
    car = _car(goal_outcomes(WEALTH, SAVINGS_INPUTS, _ledger(portfolio_paid=0.0)))

    assert car.p_affordable == pytest.approx(1.0)
    assert car.amount_nominal == pytest.approx(3_000_000.0 * 1.09**2)


def test_a_savings_goal_with_a_shortfall_is_measured_on_the_shortfall_only() -> None:
    # The portfolio had to find 50: three of the four scenarios hold that much the month before.
    car = _car(goal_outcomes(WEALTH, SAVINGS_INPUTS, _ledger(portfolio_paid=50.0)))

    assert car.p_affordable == pytest.approx(0.75)


def test_a_shortfall_larger_than_the_goal_is_capped_at_the_goal() -> None:
    # A 9 000 000 withdrawal that month cannot all be the car's: the car is measured on its nominal.
    car = _car(goal_outcomes(WEALTH, SAVINGS_INPUTS, _ledger(portfolio_paid=9_000_000.0)))

    assert car.p_affordable == pytest.approx(0.5)


# An investment goal is measured the same way. The buffer pre-saves an investment goal too
# (including the purchase month among the deficits of its window), and the saved part is
# a deposit — no market risk — so the goal's only uncertainty is what the portfolio has to pay.


def test_an_investment_goal_the_buffer_paid_in_full_is_affordable_in_every_scenario() -> None:
    # INPUTS has no savings horizon: the car is an investment goal. Two of the four scenarios hold
    # the nominal 3 564 300 the month before; irrelevant when the portfolio paid nothing.
    car = _car(goal_outcomes(WEALTH, INPUTS, _ledger(portfolio_paid=0.0)))

    assert car.p_affordable == pytest.approx(1.0)


def test_an_investment_goal_is_measured_on_the_portfolios_share_only() -> None:
    # The buffer covered all but 50 of the 3 564 300: three of the four scenarios hold 50 the
    # month before (5 000 000, 4 000 000, 100), so 0.75 — not the 0.5 the full nominal gives.
    car = _car(goal_outcomes(WEALTH, INPUTS, _ledger(portfolio_paid=50.0)))

    assert car.p_affordable == pytest.approx(0.75)


# The month before retirement (2029-07) holds 500 000 / 400 000 / 100 000 / 0.
RETIREMENT_WEALTH = pd.DataFrame(
    [[500_000.0, 400_000.0, 100_000.0, 0.0], [400_000.0, 300_000.0, 0.0, 0.0]],
    index=pd.PeriodIndex(["2029-07", "2029-08"], freq="M"),
)


def _pension(outcomes: tuple) -> object:  # type: ignore[type-arg]
    return next(outcome for outcome in outcomes if outcome.goal_id == 2)


def test_a_pension_sized_as_a_share_is_measured_on_its_ledger_line() -> None:
    """A share of the expenses has no amount to index; the amount is what the ledger pays."""
    share = INPUTS.model_copy(
        update={
            "pension_replaces_expenses": True,
            "goals": (
                INPUTS.goals[0],
                INPUTS.goals[1].model_copy(update={"amount_basis": "expense_share", "amount_pv": 1.0}),
            ),
        }
    )

    pension = _pension(goal_outcomes(RETIREMENT_WEALTH, share, build_ledger(share)))

    # 2029-08 is month 36: all of the family expenses after three raises at 10 % = 399 300.
    assert pension.amount_nominal == pytest.approx(300_000.0 * 1.1**3)
    # 500 000 and 400 000 cover it; indexing the share 1.0 as money would have given 0.75.
    assert pension.p_affordable == pytest.approx(0.5)


def test_a_pension_sum_is_measured_on_the_same_number_as_before() -> None:
    pension = _pension(goal_outcomes(RETIREMENT_WEALTH, INPUTS, build_ledger(INPUTS)))

    assert pension.amount_nominal == pytest.approx(200_000.0 * 1.09**3)


def test_a_goal_with_a_month_is_measured_in_that_month() -> None:
    december = INPUTS.goals[0].model_copy(update={"target_month": 12})
    inputs = INPUTS.model_copy(update={"goals": (december, *INPUTS.goals[1:])})
    wealth = pd.DataFrame([[1.0], [1.0]], index=pd.PeriodIndex(["2028-11", "2028-12"], freq="M"))

    car = next(o for o in goal_outcomes(wealth, inputs, build_ledger(inputs)) if o.label == "Автомобиль")
    assert car.month == "2028-12"
