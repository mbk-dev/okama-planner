"""Goals of three kinds: a dated lump, a monthly retirement stream, a reserve top-up."""

from __future__ import annotations

import pytest

from okama_planner.inputs import GoalIn, PlanInputs, Rates
from okama_planner.ledger.goals import (
    AssetSale,
    GoalExpansion,
    expand_goals,
    goal_month_index,
    is_savings_goal,
)
from okama_planner.ledger.types import LedgerLine
from planner_tests.ledger.test_build import SEEDED, ZERO_RATES

RATES = Rates(
    inflation_rate=0.09,
    expense_indexation_rate=0.10,
    income_indexation_rate=0.06,
    goal_indexation_rate=0.09,
    discount_rate=0.09,
    buffer_rate=0.0,
)
FLAT = GoalIn(
    goal_id=1,
    label="Квартира",
    kind="lump",
    amount_pv=13_000_000.0,
    pv_year=2026,
    target_year=2031,
    becomes_asset=True,
)
PENSION = GoalIn(
    goal_id=2,
    label="Пассивный доход от портфеля",
    kind="retirement_income",
    amount_pv=250_000.0,
    pv_year=2026,
    target_year=2031,
)
SHARE = PENSION.model_copy(update={"amount_basis": "expense_share", "amount_pv": 0.7})
RESERVE = GoalIn(
    goal_id=3,
    label="Резервный фонд",
    kind="reserve_topup",
    amount_pv=1_800_000.0,
    pv_year=2026,
    target_year=2028,
)
NEW_CAR = GoalIn(
    goal_id=4,
    label="Новый автомобиль",
    kind="lump",
    amount_pv=6_000_000.0,
    pv_year=2026,
    target_year=2029,
    becomes_asset=True,
    replaces_asset="Автомобиль",
)


def _expand(*goals: GoalIn, months: int = 84, retirement_index: int = 60) -> GoalExpansion:
    return expand_goals(goals, t0="2026-08", months=months, retirement_index=retirement_index, rates=RATES)


def test_a_lump_goal_is_one_outflow_at_its_own_month() -> None:
    expansion = _expand(FLAT)
    outflows = [line for line in expansion.lines if line.line_kind == "goal_outflow"]

    assert len(outflows) == 1
    assert outflows[0].month == "2031-08"
    assert outflows[0].amount == pytest.approx(-13_000_000.0 * 1.09**5)
    assert outflows[0].amount == pytest.approx(-20_002_111.41, abs=0.01)
    assert outflows[0].resolved_rate == pytest.approx(0.09)


def test_becomes_asset_records_an_acquired_asset_at_the_goal_rate() -> None:
    expansion = _expand(FLAT)

    assert len(expansion.acquired) == 1
    acquired = expansion.acquired[0]
    assert acquired.month_index == 60
    assert acquired.value == pytest.approx(13_000_000.0 * 1.09**5)
    assert acquired.value == pytest.approx(20_002_111.41, abs=0.01)
    # No separate rate field exists on a goal, so the rate that priced it also grows it.
    assert acquired.growth_rate == pytest.approx(0.09)


def test_a_consumed_goal_acquires_nothing() -> None:
    education = GoalIn(
        goal_id=4,
        label="Образование",
        kind="lump",
        amount_pv=2_000_000.0,
        pv_year=2026,
        target_year=2030,
        becomes_asset=False,
    )
    assert _expand(education).acquired == ()


def test_retirement_income_is_a_monthly_stream_indexed_every_anniversary() -> None:
    """Indexed on the t0 anniversary, not on the Gregorian January.

    t0 is 2026-08, so month 71 (2032-07) and month 72 (2032-08) straddle the August anniversary,
    not a January one. That pair is what proves the raise lands on the anniversary.
    """
    expansion = _expand(PENSION)
    outflows = [line for line in expansion.lines if line.line_kind == "goal_outflow"]

    # Starts at the retirement month and runs to the end of the horizon.
    assert outflows[0].month == "2031-08"
    assert len(outflows) == 84 - 60
    # The stream is worth its PV amount inflated by (base_year + n // 12) - pv_year years.
    assert outflows[0].amount == pytest.approx(-250_000.0 * 1.09**5)
    assert outflows[0].amount == pytest.approx(-384_655.99, abs=0.01)
    assert outflows[11].month == "2032-07"
    assert outflows[11].amount == pytest.approx(-250_000.0 * 1.09**5)
    assert outflows[11].amount == pytest.approx(-384_655.99, abs=0.01)
    assert outflows[12].month == "2032-08"
    assert outflows[12].amount == pytest.approx(-250_000.0 * 1.09**6)
    assert outflows[12].amount == pytest.approx(-419_275.03, abs=0.01)
    assert outflows[-1].month == "2033-07"
    # n=83: base_year 2026 + 83 // 12 == 6 == the same bracket as month 72, not a 7th raise.
    assert outflows[-1].amount == pytest.approx(-250_000.0 * 1.09**6)
    assert outflows[-1].amount == pytest.approx(-419_275.03, abs=0.01)


def test_retirement_income_honours_a_pv_year_that_differs_from_t0s_year() -> None:
    """Nothing on the branch covered pv_year != t0's year before this."""
    pension_priced_earlier = GoalIn(
        goal_id=11,
        label="Пассивный доход",
        kind="retirement_income",
        amount_pv=250_000.0,
        pv_year=2024,
        target_year=2031,
    )
    expansion = _expand(pension_priced_earlier)
    outflows = [line for line in expansion.lines if line.line_kind == "goal_outflow"]

    # n=60 -> base_year 2026 + 60 // 12 == 5 == 2031; exponent is (2031 - 2024) == 7.
    assert outflows[0].month == "2031-08"
    assert outflows[0].amount == pytest.approx(-250_000.0 * 1.09**7)


def test_a_share_pension_is_its_share_of_the_expenses_from_retirement() -> None:
    expenses = (
        LedgerLine("2031-07", "expense", "Расходы семьи", -100_000.0, 0.10),  # month 59: before
        LedgerLine("2031-08", "expense", "Расходы семьи", -100_000.0, 0.10),  # month 60: retirement
        LedgerLine("2031-08", "expense", "Лечение", -50_000.0, 0.05),
        LedgerLine("2031-08", "income", "Госпенсия", 30_000.0, 0.06),  # income stays income
        LedgerLine("2031-09", "expense", "Расходы семьи", -100_000.0, 0.10),
    )

    expansion = expand_goals(
        (SHARE,), t0="2026-08", months=84, retirement_index=60, rates=RATES, expenses=expenses
    )

    assert [(line.month, line.line_kind, line.goal_id) for line in expansion.lines] == [
        ("2031-08", "goal_outflow", 2),
        ("2031-09", "goal_outflow", 2),
    ]
    # 0.7 × (100 000 + 50 000) = 105 000; two items at two rates — no single rate to record.
    assert expansion.lines[0].amount == pytest.approx(-105_000.0)
    assert expansion.lines[0].resolved_rate is None
    # 0.7 × 100 000 = 70 000, one item at 10 %.
    assert expansion.lines[1].amount == pytest.approx(-70_000.0)
    assert expansion.lines[1].resolved_rate == pytest.approx(0.10)


def test_a_share_pension_without_the_expenses_it_replaces_is_a_loud_error() -> None:
    with pytest.raises(ValueError, match="share of the family expenses"):
        _expand(SHARE)


def test_a_reserve_topup_is_a_target_not_an_outflow() -> None:
    expansion = _expand(RESERVE)

    assert [line.line_kind for line in expansion.lines] == []
    assert expansion.reserve_targets == ((24, pytest.approx(1_800_000.0 * 1.09**2), 3),)
    assert expansion.reserve_targets == ((24, pytest.approx(2_138_580.00, abs=0.01), 3),)


def test_a_goal_past_the_horizon_is_dropped() -> None:
    late = GoalIn(
        goal_id=5,
        label="Поздняя цель",
        kind="lump",
        amount_pv=1_000_000.0,
        pv_year=2026,
        target_year=2040,
    )
    assert _expand(late).lines == ()


def test_a_goal_before_t0_raises() -> None:
    early = GoalIn(
        goal_id=7,
        label="Цель в прошлом",
        kind="lump",
        amount_pv=1_000_000.0,
        pv_year=2026,
        target_year=2025,
    )
    with pytest.raises(ValueError, match="target_year 2025 precedes"):
        _expand(early)


def test_a_goal_in_t0_year_works() -> None:
    same_year = GoalIn(
        goal_id=8,
        label="Цель в этом году",
        kind="lump",
        amount_pv=500_000.0,
        pv_year=2026,
        target_year=2026,
    )
    expansion = _expand(same_year)
    assert len(expansion.lines) == 1
    assert expansion.lines[0].month == "2026-08"


def test_an_undated_lump_goal_fails_loudly() -> None:
    undated = GoalIn(goal_id=6, label="Без срока", kind="lump", amount_pv=1_000_000.0, pv_year=2026)

    with pytest.raises(ValueError, match="a lump goal needs"):
        _expand(undated)


def test_an_undated_reserve_topup_fails_loudly() -> None:
    undated = GoalIn(
        goal_id=9, label="Резерв без срока", kind="reserve_topup", amount_pv=500_000.0, pv_year=2026
    )
    with pytest.raises(ValueError, match="a reserve_topup goal needs"):
        _expand(undated)


def test_unknown_goal_kind_raises() -> None:
    unknown = GoalIn(
        goal_id=10,
        label="Неизвестная цель",
        kind="mystery",
        amount_pv=1_000_000.0,
        pv_year=2026,
        target_year=2030,
    )
    with pytest.raises(ValueError, match="unknown goal kind"):
        _expand(unknown)


def test_replaces_asset_records_a_sale_in_the_goal_month() -> None:
    expansion = _expand(NEW_CAR)

    # The sale carries labels only: the asset's value is the ledger's to compute, since the
    # expansion never sees the assets.
    assert expansion.sold == (
        AssetSale(month_index=36, asset_label="Автомобиль", goal_label="Новый автомобиль"),
    )


def test_a_goal_without_a_replaced_asset_sells_nothing() -> None:
    assert _expand(FLAT).sold == ()


def test_a_goal_past_the_horizon_sells_nothing_either() -> None:
    # Dropping the purchase but keeping the sale would hand the plan money for nothing.
    assert _expand(NEW_CAR, months=24).sold == ()


@pytest.mark.parametrize("goal", [PENSION, RESERVE], ids=["retirement_income", "reserve_topup"])
def test_only_a_lump_goal_can_replace_an_asset(goal: GoalIn) -> None:
    with pytest.raises(ValueError, match="replaces_asset"):
        _expand(goal.model_copy(update={"replaces_asset": "Автомобиль"}))


def _plan(goal: GoalIn, **update: object) -> PlanInputs:
    base = PlanInputs(
        t0="2026-08",
        horizon_years=20,
        retirement_year=2035,
        buffer_lookahead_months=12,
        rates=ZERO_RATES,
        goals=(goal,),
    )
    return base.model_copy(update=update)


def test_a_lump_goal_under_the_savings_horizon_is_a_savings_goal() -> None:
    car = FLAT.model_copy(update={"target_year": 2029})
    assert is_savings_goal(car, _plan(car, savings_horizon_years=5)) is True
    assert is_savings_goal(FLAT, _plan(FLAT, savings_horizon_years=5)) is False
    # t0 2026-08: 2030 is 4 years out (48 < 60 months), still under the horizon.
    car_2030 = FLAT.model_copy(update={"target_year": 2030})
    assert is_savings_goal(car_2030, _plan(car_2030, savings_horizon_years=5)) is True


def test_without_a_savings_horizon_every_goal_is_an_investment_goal() -> None:
    car = FLAT.model_copy(update={"target_year": 2029})
    assert is_savings_goal(car, _plan(car)) is False


@pytest.mark.parametrize(("year", "expected"), [(2027, True), (2034, True), (2035, False), (2040, False)])
def test_under_the_retirement_rule_every_purchase_before_retirement_is_saved_for(
    year: int, expected: bool
) -> None:
    # Retirement is 2035: a purchase in 2034 is still paid from the reserve, one in the year of
    # retirement is the portfolio's — there is no salary left to save from.
    goal = FLAT.model_copy(update={"target_year": year})
    plan = _plan(goal, reserves_until_retirement=True, savings_horizon_years=5)
    assert is_savings_goal(goal, plan) is expected


def test_under_the_retirement_rule_a_pension_is_never_a_savings_goal() -> None:
    pension = GoalIn(
        goal_id=9,
        label="Пенсия",
        kind="retirement_income",
        amount_pv=1.0,
        pv_year=2026,
        target_year=2030,
    )
    assert is_savings_goal(pension, _plan(pension, reserves_until_retirement=True)) is False


def test_only_lump_goals_can_be_savings_goals() -> None:
    # The reserve top-up already is a savings vehicle; the pension is the portfolio's job.
    assert is_savings_goal(PENSION, _plan(PENSION, savings_horizon_years=60)) is False
    assert is_savings_goal(RESERVE, _plan(RESERVE, savings_horizon_years=60)) is False
    undated = FLAT.model_copy(update={"target_year": None})
    assert is_savings_goal(undated, _plan(undated, savings_horizon_years=60)) is False


def test_goal_lines_carry_the_id_of_their_goal() -> None:
    from okama_planner.ledger.calendar import year_index
    from planner_tests.ledger.test_build import INPUTS

    expansion = expand_goals(
        INPUTS.goals, INPUTS.t0, 60, year_index(INPUTS.t0, INPUTS.retirement_year), INPUTS.rates
    )

    outflows = [line for line in expansion.lines if line.line_kind == "goal_outflow"]
    assert outflows and all(line.goal_id is not None for line in outflows)
    assert {line.goal_id for line in outflows} == {
        goal.goal_id for goal in INPUTS.goals if goal.kind != "reserve_topup"
    }
    # The reserve target remembers which goal asked for it.
    assert [target[2] for target in expansion.reserve_targets] == [
        goal.goal_id for goal in INPUTS.goals if goal.kind == "reserve_topup"
    ]


DECEMBER = GoalIn(
    goal_id=11,
    label="Квартира в декабре",
    kind="lump",
    amount_pv=1_000_000.0,
    pv_year=2026,
    target_year=2029,
    target_month=12,
)


def test_a_goal_month_counts_from_t0() -> None:
    # (2029 - 2026) * 12 + (12 - 8) = 40; without a month, t0's own month of 2029: 36.
    assert goal_month_index(DECEMBER, "2026-08") == 40
    assert goal_month_index(DECEMBER.model_copy(update={"target_month": None}), "2026-08") == 36


def test_a_goal_with_a_month_falls_in_that_month() -> None:
    outflows = [line for line in _expand(DECEMBER).lines if line.line_kind == "goal_outflow"]

    assert [line.month for line in outflows] == ["2029-12"]


def test_without_a_month_the_goal_keeps_t0s_month() -> None:
    plain = DECEMBER.model_copy(update={"target_month": None})
    outflows = [line.month for line in _expand(plain).lines if line.line_kind == "goal_outflow"]

    assert outflows == ["2029-08"]


def test_a_goal_month_before_t0_raises() -> None:
    march = DECEMBER.model_copy(update={"target_year": 2026, "target_month": 3})
    with pytest.raises(ValueError, match="2026-03 precedes the plan start 2026-08"):
        _expand(march)


def test_a_reserve_topup_lands_in_its_month() -> None:
    topup = DECEMBER.model_copy(update={"kind": "reserve_topup", "target_year": 2027})
    # (2027 - 2026) * 12 + (12 - 8) = 16
    assert [target[0] for target in _expand(topup).reserve_targets] == [16]


def test_a_purchase_before_the_retirement_month_is_saved_for_even_in_the_retirement_year() -> None:
    # SEEDED: t0 2026-08, retirement 2031 — the boundary is 2031-08 (month 60). March 2031 is
    # month 55, before it: saved for. September 2031 (month 61) and t0's own month are not.
    march = FLAT_2031.model_copy(update={"target_month": 3})
    assert is_savings_goal(march, SEEDED)
    assert not is_savings_goal(FLAT_2031.model_copy(update={"target_month": 9}), SEEDED)
    assert not is_savings_goal(FLAT_2031, SEEDED)


FLAT_2031 = GoalIn(
    goal_id=1,
    label="Квартира",
    kind="lump",
    amount_pv=2_000_000.0,
    pv_year=2026,
    target_year=2031,
)
