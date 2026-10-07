"""The whole ledger, on a small input whose every number is checkable by hand."""

from __future__ import annotations

import pytest

from okama_planner.inputs import AssetIn, BudgetItemIn, GoalIn, LiabilityIn, PlanInputs, Rates
from okama_planner.ledger.build import (
    ConflictingReserveRatesError,
    DuplicateAssetSaleError,
    RetirementBeyondHorizonError,
    SavingsAssetRateError,
    UnknownAssetClassError,
    UnknownSoldAssetError,
    build_ledger,
)
from okama_planner.ledger.types import LedgerLine

RATES = Rates(
    inflation_rate=0.09,
    expense_indexation_rate=0.10,
    income_indexation_rate=0.06,
    goal_indexation_rate=0.09,
    discount_rate=0.09,
    buffer_rate=0.0,
)

INPUTS = PlanInputs(
    t0="2026-08",
    horizon_years=5,
    retirement_year=2029,
    buffer_lookahead_months=12,
    rates=RATES,
    assets=(
        AssetIn(label="Брокерский счёт", amount=5_000_000.0, currency="RUB", asset_class="portfolio"),
        AssetIn(label="Резервный фонд", amount=1_000_000.0, currency="RUB", asset_class="reserve"),
        AssetIn(
            label="Квартира",
            amount=10_000_000.0,
            currency="RUB",
            asset_class="non_working",
            growth_rate=0.05,
        ),
    ),
    liabilities=(
        LiabilityIn(
            label="Ипотека",
            principal=1_000_000.0,
            annual_rate=0.12,
            monthly_payment=100_000.0,
            term_months=360,
            start_month="2026-08",
        ),
    ),
    budget_items=(
        BudgetItemIn(kind="income", label="Зарплата", monthly_amount=450_000.0, end_rule="until_retirement"),
        BudgetItemIn(kind="expense", label="Расходы семьи", monthly_amount=300_000.0),
    ),
    goals=(
        GoalIn(
            goal_id=1,
            label="Автомобиль",
            kind="lump",
            amount_pv=3_000_000.0,
            pv_year=2026,
            target_year=2028,
            becomes_asset=True,
        ),
        GoalIn(
            goal_id=2,
            label="Пассивный доход от портфеля",
            kind="retirement_income",
            amount_pv=200_000.0,
            pv_year=2026,
            target_year=2029,
        ),
    ),
)

# The car is replaced: the old one, worth 6 000 000 and losing 10 % a year, is sold the month the
# new one is bought (month 36, 2029-08), and the proceeds go to the portfolio.
OLD_CAR = AssetIn(
    label="Старый автомобиль",
    amount=6_000_000.0,
    currency="RUB",
    asset_class="non_working",
    growth_rate=-0.10,
)
NEW_CAR = GoalIn(
    goal_id=3,
    label="Новый автомобиль",
    kind="lump",
    amount_pv=5_000_000.0,
    pv_year=2026,
    target_year=2029,
    becomes_asset=True,
    replaces_asset="Старый автомобиль",
)
SALE_INPUTS = INPUTS.model_copy(
    update={"assets": (*INPUTS.assets, OLD_CAR), "goals": (*INPUTS.goals, NEW_CAR)}
)
#: The same plan, the old car kept: what the sale changes is the difference between the two.
KEEP_INPUTS = SALE_INPUTS.model_copy(
    update={"goals": (*INPUTS.goals, NEW_CAR.model_copy(update={"replaces_asset": None}))}
)

#: The same plan under the pension-expenses rule: the family expenses become the pension.
REPLACED = INPUTS.model_copy(update={"pension_replaces_expenses": True})
#: …and with the pension sized as all of the family expenses instead of a sum.
SHARE = REPLACED.model_copy(
    update={
        "goals": (
            INPUTS.goals[0],
            INPUTS.goals[1].model_copy(update={"amount_basis": "expense_share", "amount_pv": 1.0}),
        )
    }
)


def test_the_horizon_is_exactly_horizon_years_of_months() -> None:
    ledger = build_ledger(INPUTS)

    assert len(ledger.months) == 60
    assert ledger.months[0] == "2026-08"
    assert ledger.months[-1] == "2031-07"
    assert set(ledger.portfolio_flow) == set(ledger.months)


def test_a_fixed_withdrawal_duration_sets_the_ledger_end_from_retirement() -> None:
    fixed = INPUTS.model_copy(update={"horizon_years": 10, "withdrawal_years": 4})

    early = build_ledger(fixed.model_copy(update={"retirement_year": 2028}))
    late = build_ledger(fixed.model_copy(update={"retirement_year": 2032}))

    assert (len(early.months), len(late.months)) == (6 * 12, 10 * 12)
    assert (early.months[-1], late.months[-1]) == ("2032-07", "2036-07")


def _amounts(lines: list[LedgerLine], line_kind: str) -> list[float]:
    """Every amount of one kind, not just the last — a dict comprehension silently overwrites."""
    return [line.amount for line in lines if line.line_kind == line_kind]


def test_the_first_month_nets_income_expense_and_the_mortgage() -> None:
    ledger = build_ledger(INPUTS)
    first = [line for line in ledger.lines if line.month == "2026-08"]

    assert _amounts(first, "income") == [pytest.approx(450_000.0)]
    assert _amounts(first, "expense") == [pytest.approx(-300_000.0)]
    assert _amounts(first, "mortgage_payment") == [pytest.approx(-100_000.0)]
    # 450 000 - 300 000 - 100 000 = 50 000 free. The buffer looks only 12 months ahead, and the
    # car (24 months out) is outside that window, so nothing is sequestered yet: all 50 000 goes
    # straight to the portfolio. Hand-verified against a from-scratch recurrence in tmp/ (deleted
    # before commit), which also confirmed the reconciliation identity below.
    assert ledger.portfolio_flow["2026-08"] == pytest.approx(50_000.0)


def test_the_mortgage_stops_at_payoff_and_the_free_flow_jumps() -> None:
    ledger = build_ledger(INPUTS)
    payments = [line for line in ledger.lines if line.line_kind == "mortgage_payment"]

    assert len(payments) == 11
    assert payments[-1].month == "2027-06"
    assert not [
        line for line in ledger.lines if line.line_kind == "mortgage_payment" and line.month == "2027-07"
    ]


def test_the_salary_stops_and_the_pension_stream_starts_in_the_same_month() -> None:
    ledger = build_ledger(INPUTS)

    incomes = sorted({line.month for line in ledger.lines if line.line_kind == "income"})
    pension = sorted(
        {
            line.month
            for line in ledger.lines
            if line.line_kind == "goal_outflow" and line.label.startswith("Пассивный")
        }
    )
    assert incomes[-1] == "2029-07"
    assert pension[0] == "2029-08"


def test_the_pension_line_is_anchored_to_t0_not_the_calendar_year() -> None:
    """Pin the ledger-level number the anchor bug actually moved.

    build_ledger sums budget.py's t0-anniversary indexing with goals.py's retirement stream into
    one free cash flow. 2026-08 is t0, so 2030-01 (month 41) is a month where
    the anchored convention (year = 2026 + 41 // 12 == 2029) and the Gregorian one
    (calendar_year == 2030) disagree — reverting the anchor changes this exact line, while every
    `test_build` assertion elsewhere in this module (the reconciliation identity included) stays
    green either way, because both sides of that identity shift together.
    """
    ledger = build_ledger(INPUTS)
    pension_line = next(
        line
        for line in ledger.lines
        if line.line_kind == "goal_outflow" and line.month == "2030-01" and line.label.startswith("Пассивный")
    )

    # n=41: anchored year = 2026 + 41 // 12 == 2029, exponent (2029 - 2026) == 3.
    assert pension_line.amount == pytest.approx(-200_000.0 * 1.09**3)
    assert pension_line.amount == pytest.approx(-259_005.80, abs=0.01)


def test_the_car_is_one_outflow_and_then_a_growing_non_working_asset() -> None:
    ledger = build_ledger(INPUTS)
    car = [line for line in ledger.lines if line.line_kind == "goal_outflow" and line.label == "Автомобиль"]

    assert len(car) == 1
    assert car[0].month == "2028-08"
    assert car[0].amount == pytest.approx(-3_000_000.0 * 1.09**2)
    # Bought in month 24; the flat was there from the start, growing at its own 5%, while the
    # car itself appreciates at the goal rate 0.09 once acquired — a deliberate plan decision.
    before = ledger.non_working_balance[23]
    after = ledger.non_working_balance[24]
    assert before == pytest.approx(10_000_000.0 * 1.05 ** (23 / 12))
    # At month 24 itself the car's own growth factor is exactly 1 (factor ** 0): this value is
    # the purchase PRICE, not proof of its appreciation rate. Round 2 item 5: that assertion
    # alone is silent to the car's rate — mutating it from 0.09 to 0.05 still passes here.
    assert after == pytest.approx(10_000_000.0 * 1.05**2 + 3_000_000.0 * 1.09**2)
    # One month later the car HAS grown, at its own rate (0.09), not the flat's (0.05) — this is
    # the assertion that actually pins the appreciation rate the "growing" in the test name claims.
    one_month_later = ledger.non_working_balance[25]
    assert one_month_later == pytest.approx(
        10_000_000.0 * 1.05 ** (25 / 12) + (3_000_000.0 * 1.09**2) * 1.09 ** (1 / 12)
    )


def test_every_indexed_line_records_the_rate_it_used() -> None:
    """Every line of a kind, not just the last one a dict comprehension happens to keep."""
    ledger = build_ledger(INPUTS)

    def rates_of(line_kind: str) -> list[float | None]:
        return [line.resolved_rate for line in ledger.lines if line.line_kind == line_kind]

    income_rates = rates_of("income")
    assert income_rates and all(rate == pytest.approx(0.06) for rate in income_rates)
    expense_rates = rates_of("expense")
    assert expense_rates and all(rate == pytest.approx(0.10) for rate in expense_rates)
    goal_rates = rates_of("goal_outflow")
    assert goal_rates and all(rate == pytest.approx(0.09) for rate in goal_rates)
    mortgage_rates = rates_of("mortgage_payment")
    assert mortgage_rates and all(rate is None for rate in mortgage_rates)


def test_the_portfolio_flow_is_the_only_series_that_leaves_the_ledger() -> None:
    ledger = build_ledger(INPUTS)
    flow_lines = [line for line in ledger.lines if line.line_kind == "portfolio_flow"]

    assert len(flow_lines) == 60
    assert all(line.amount == pytest.approx(ledger.portfolio_flow[line.month]) for line in flow_lines)


def test_the_ledger_is_a_pure_function_of_its_input() -> None:
    assert build_ledger(INPUTS) == build_ledger(INPUTS)


def test_a_goal_exactly_on_the_horizon_boundary_is_dropped() -> None:
    """Pins goals.py's `n >= months` boundary so it cannot drift to `n > months`.

    INPUTS's horizon is 5 years from t0=2026-08, so its last month is 2031-07; a goal dated
    2031 (t0's year + horizon_years) resolves to n == months == 60, one month past the horizon.
    Dropping it is intended and already tested (test_goals.py); this pins the exact boundary.
    """
    on_the_edge = INPUTS.model_copy(
        update={
            "goals": (
                GoalIn(
                    goal_id=50,
                    label="На границе горизонта",
                    kind="lump",
                    amount_pv=1_000_000.0,
                    pv_year=2026,
                    target_year=2031,
                ),
            )
        }
    )
    ledger = build_ledger(on_the_edge)
    assert [line for line in ledger.lines if line.label == "На границе горизонта"] == []


def test_the_deficit_the_buffer_cannot_cover_still_reaches_the_portfolio_as_a_shortfall() -> None:
    """Buffer shortage: the car's cost outruns what 12 months of lookahead could save."""
    ledger = build_ledger(INPUTS)

    # Hand-computed from scratch (tmp/, deleted before commit): by month 23 the buffer holds
    # 1 764 000.0 against a 3 421 680.0 deficit in month 24, so 1 657 680.0 must come straight
    # out of the portfolio as a negative flow that month.
    assert ledger.buffer_balance[23] == pytest.approx(1_764_000.0)
    assert ledger.portfolio_flow["2028-08"] == pytest.approx(-1_657_680.0)


def test_every_line_the_ledger_generates_is_accounted_for_in_flow_plus_final_buffer() -> None:
    """Reconciliation, backed by an independent line count.

    With buffer_rate=0.0 there is no interest to reconcile, so the sum of every flow-affecting
    line (free-flow kinds plus the reserve top-up that moves money out of free cash) must equal
    exactly what left through the portfolio plus what the buffer still holds at the end. That
    identity alone does NOT catch a duplicated source line: doubling every line on both sides
    of the equation leaves it true. The line count below is hand-computed independently of the
    identity and catches exactly that case — income runs 36 months (to retirement), expense 60,
    the mortgage 11, and goal_outflow is the one car line plus 24 months of pension (36..59).
    """
    ledger = build_ledger(INPUTS)

    accounted_for = {"income", "expense", "mortgage_payment", "goal_outflow", "reserve_topup"}
    accounted_lines = [line for line in ledger.lines if line.line_kind in accounted_for]
    assert len(accounted_lines) == 36 + 60 + 11 + 25 + 0

    total_in = sum(line.amount for line in accounted_lines)
    total_out = sum(ledger.portfolio_flow.values()) + ledger.buffer_balance[-1]

    assert total_in == pytest.approx(total_out)


def test_a_retirement_year_at_or_past_the_horizon_is_a_loud_error() -> None:
    """A silently missing pension stream is not deliverable — this must fail, not go quiet."""
    doomed = INPUTS.model_copy(update={"horizon_years": 3, "retirement_year": 2035})

    with pytest.raises(
        RetirementBeyondHorizonError,
        match=r"retirement year 2035 is at or past the horizon: t0=2026-08, horizon_years=3 "
        r"covers 36 months",
    ):
        build_ledger(doomed)


def test_a_retirement_year_exactly_on_the_last_month_of_the_horizon_still_errors() -> None:
    """The boundary case: retirement_index == months gives expand_goals a zero-length range."""
    on_the_edge = INPUTS.model_copy(update={"horizon_years": 3, "retirement_year": 2029})

    with pytest.raises(
        RetirementBeyondHorizonError,
        match=r"retirement year 2029 is at or past the horizon: t0=2026-08, horizon_years=3 "
        r"covers 36 months, retirement falls on month 36",
    ):
        build_ledger(on_the_edge)


def test_a_retirement_year_before_t0_is_also_a_loud_error() -> None:
    """A negative retirement_index would make expand_goals build lines outside the horizon."""
    too_early = INPUTS.model_copy(update={"retirement_year": 2024})

    with pytest.raises(
        RetirementBeyondHorizonError,
        match=r"retirement year 2024 is before the plan start \(2026-08\)",
    ):
        build_ledger(too_early)


def _reserve_topup_scenario(*reserve_assets: AssetIn) -> PlanInputs:
    """A minimal input isolating the reserve fund: one topup goal, no other cash flow noise."""
    return PlanInputs(
        t0="2026-08",
        horizon_years=3,
        retirement_year=2028,
        buffer_lookahead_months=12,
        rates=RATES,
        assets=reserve_assets,
        goals=(
            GoalIn(
                goal_id=20,
                label="Резерв",
                kind="reserve_topup",
                amount_pv=1_000_000.0,
                pv_year=2026,
                target_year=2027,
            ),
        ),
    )


def _two_reserve_topups_scenario(goals: tuple[GoalIn, ...]) -> PlanInputs:
    """Two reserve_topup goals landing in the same target month, no reserve asset."""
    return PlanInputs(
        t0="2026-08",
        horizon_years=3,
        retirement_year=2028,
        buffer_lookahead_months=12,
        rates=RATES,
        goals=goals,
    )


def test_two_reserve_topups_in_the_same_month_take_the_larger_target_regardless_of_order() -> None:
    """A reserve_topup is a LEVEL the fund must reach, not a contribution to add (spec:
    «доведение резервного фонда до целевого размера»). Two levels due the same month are both
    satisfied by the larger one; summing them would double-count. Order of entry must not change
    the result — that is exactly the property round 3's blocker broke via dict(reserve_targets).
    """
    cushion = GoalIn(
        goal_id=40,
        label="Подушка",
        kind="reserve_topup",
        amount_pv=1_000_000.0,
        pv_year=2026,
        target_year=2028,
    )
    repair = GoalIn(
        goal_id=41,
        label="Ремонт",
        kind="reserve_topup",
        amount_pv=500_000.0,
        pv_year=2026,
        target_year=2028,
    )
    # Both target 2028 (n=24): cushion = 1 000 000 * 1.09**2 = 1 188 100.00 (the larger),
    # repair = 500 000 * 1.09**2 = 594 050.00. The larger must win under EITHER ordering.
    larger_target = 1_000_000.0 * 1.09**2

    cushion_first = build_ledger(_two_reserve_topups_scenario((cushion, repair)))
    repair_first = build_ledger(_two_reserve_topups_scenario((repair, cushion)))

    for ledger in (cushion_first, repair_first):
        topups = [line for line in ledger.lines if line.line_kind == "reserve_topup"]
        assert len(topups) == 1
        assert topups[0].amount == pytest.approx(-larger_target)
        assert topups[0].amount == pytest.approx(-1_188_100.0, abs=0.01)

    assert cushion_first.reserve_balance[24] == pytest.approx(repair_first.reserve_balance[24])


def test_an_unknown_asset_class_is_a_loud_error_not_a_vanished_reserve() -> None:
    """A typo in a hand-built or replayed snapshot must not silently zero out the reserve fund.

    PlanInputs types asset_class as a plain str; the DB enum guards the normal path, but a
    hand-built or replayed snapshot (phase 5's import) bypasses it. Before this guard, "reserv"
    instead of "reserve" gave reserve_balance[0] == 0.0 with no error.
    """
    typo = INPUTS.model_copy(
        update={
            "assets": (AssetIn(label="Опечатка", amount=1_000_000.0, currency="RUB", asset_class="reserv"),)
        }
    )
    with pytest.raises(UnknownAssetClassError, match=r"Опечатка.*'reserv'"):
        build_ledger(typo)


def test_a_reserve_topup_without_a_reserve_asset_falls_back_to_the_expense_rate() -> None:
    """No reserve asset to read a rate from; must use the project's own fallback, not 0.0."""
    ledger = build_ledger(_reserve_topup_scenario())
    topups = [line for line in ledger.lines if line.line_kind == "reserve_topup"]

    assert len(topups) == 1
    assert topups[0].month == "2027-08"
    assert topups[0].resolved_rate == pytest.approx(0.10)  # RATES.expense_indexation_rate
    target = 1_000_000.0 * 1.09  # goal_indexation_rate prices PV -> FV over one year
    assert topups[0].amount == pytest.approx(-target)
    assert ledger.reserve_balance[12] == pytest.approx(target)


def test_two_reserve_assets_with_conflicting_explicit_rates_raise() -> None:
    """Two DISTINCT rates the client actually typed genuinely cannot grow one summed balance."""
    scenario = _reserve_topup_scenario(
        AssetIn(label="Резерв А", amount=500_000.0, currency="RUB", asset_class="reserve", growth_rate=0.05),
        AssetIn(label="Резерв Б", amount=500_000.0, currency="RUB", asset_class="reserve", growth_rate=0.07),
    )
    with pytest.raises(ConflictingReserveRatesError, match=r"conflicting rates \[0\.05, 0\.07\]"):
        build_ledger(scenario)


def test_two_reserve_assets_with_the_same_explicit_rate_track_as_one_balance() -> None:
    scenario = _reserve_topup_scenario(
        AssetIn(label="Резерв А", amount=500_000.0, currency="RUB", asset_class="reserve", growth_rate=0.06),
        AssetIn(label="Резерв Б", amount=500_000.0, currency="RUB", asset_class="reserve", growth_rate=0.06),
    )
    ledger = build_ledger(scenario)
    # Combined opening balance 1 000 000.0, grown 12 months at the shared 6% annual rate.
    assert ledger.reserve_balance[11] == pytest.approx(1_000_000.0 * 1.06 ** (11 / 12))


def test_an_explicit_rate_on_one_reserve_asset_is_inherited_by_a_blank_sibling() -> None:
    """Round-2 regression: a blank must not be resolved to the fallback and then 'conflict'.

    A deposit at an explicitly stated 5% next to a cushion with NO rate entered must build —
    the blank inherits the one explicit rate on the balance, not the unrelated 10% expense
    fallback nobody typed. Combined balance 1 000 000.0 growing at 5%/yr falls short of the
    1 090 000.0 target (1 000 000.0 * 1.09) by exactly 40 000.0 at month 12.
    """
    scenario = _reserve_topup_scenario(
        AssetIn(label="Депозит", amount=500_000.0, currency="RUB", asset_class="reserve", growth_rate=0.05),
        AssetIn(label="Подушка", amount=500_000.0, currency="RUB", asset_class="reserve"),
    )
    ledger = build_ledger(scenario)
    topups = [line for line in ledger.lines if line.line_kind == "reserve_topup"]

    assert len(topups) == 1
    assert topups[0].resolved_rate == pytest.approx(0.05)
    assert topups[0].amount == pytest.approx(-40_000.0)
    assert ledger.reserve_balance[11] == pytest.approx(1_000_000.0 * 1.05 ** (11 / 12))
    assert ledger.reserve_balance[12] == pytest.approx(1_090_000.0)


def test_two_reserve_assets_with_no_explicit_rate_share_the_fallback() -> None:
    """Neither asset states a rate: both fall back to the project's own reserve rate, no conflict.

    A small combined balance (200 000.0) is used so the 1 090 000.0 target still needs a real
    top-up even at the 10% fallback rate — the point being the shared rate, not the shortfall.
    """
    scenario = _reserve_topup_scenario(
        AssetIn(label="Резерв А", amount=100_000.0, currency="RUB", asset_class="reserve"),
        AssetIn(label="Резерв Б", amount=100_000.0, currency="RUB", asset_class="reserve"),
    )
    ledger = build_ledger(scenario)
    topups = [line for line in ledger.lines if line.line_kind == "reserve_topup"]

    assert len(topups) == 1
    assert topups[0].resolved_rate == pytest.approx(0.10)  # RATES.expense_indexation_rate
    assert topups[0].amount == pytest.approx(-870_000.0)
    assert ledger.reserve_balance[11] == pytest.approx(200_000.0 * 1.10 ** (11 / 12))
    assert ledger.reserve_balance[12] == pytest.approx(1_090_000.0)


def test_a_reserve_already_above_its_target_gets_no_topup_and_keeps_growing() -> None:
    """The already-funded path: balance exceeds the target, so nothing tops it up or resets it."""
    scenario = PlanInputs(
        t0="2026-08",
        horizon_years=3,
        retirement_year=2028,
        buffer_lookahead_months=12,
        rates=RATES,
        assets=(
            AssetIn(
                label="Резерв",
                amount=5_000_000.0,
                currency="RUB",
                asset_class="reserve",
                growth_rate=0.05,
            ),
        ),
        goals=(
            GoalIn(
                goal_id=31,
                label="Резерв",
                kind="reserve_topup",
                amount_pv=1_000_000.0,
                pv_year=2026,
                target_year=2028,
            ),
        ),
    )
    ledger = build_ledger(scenario)

    assert [line for line in ledger.lines if line.line_kind == "reserve_topup"] == []
    # Grown balance at month 24, not reset to the (much smaller) target.
    assert ledger.reserve_balance[24] == pytest.approx(5_000_000.0 * 1.05**2)


def test_reserve_topups_with_an_existing_reserve_asset_are_hand_computed() -> None:
    """The main scenario's reserve asset (1 000 000.0, falls back to 10% expense indexation)."""
    with_topup = INPUTS.model_copy(
        update={
            "goals": (
                *INPUTS.goals,
                GoalIn(
                    goal_id=21,
                    label="Резервный фонд",
                    kind="reserve_topup",
                    amount_pv=1_500_000.0,
                    pv_year=2026,
                    target_year=2027,
                ),
            )
        }
    )
    ledger = build_ledger(with_topup)
    topups = [line for line in ledger.lines if line.line_kind == "reserve_topup"]

    assert len(topups) == 1
    assert topups[0].month == "2027-08"
    # Balance grows from 1 000 000.0 at 10%/yr for 12 months, reaching 1 100 000.0 just before
    # the target; the target is 1 500 000.0 * 1.09 == 1 635 000.0, so the shortfall is 535 000.0.
    assert ledger.reserve_balance[11] == pytest.approx(1_000_000.0 * 1.10 ** (11 / 12))
    assert topups[0].amount == pytest.approx(-535_000.0)
    assert ledger.reserve_balance[12] == pytest.approx(1_635_000.0)


def test_a_replaced_asset_is_sold_for_its_value_in_the_goal_month() -> None:
    ledger = build_ledger(SALE_INPUTS)
    sales = ledger.lines_of("asset_sale")

    assert len(sales) == 1
    assert sales[0].month == "2029-08"
    assert sales[0].label == "Старый автомобиль"
    # 36 months at -10 % a year: 6 000 000 * 0.9 ** 3, the issue's hand-computed number.
    assert sales[0].amount == pytest.approx(4_374_000.0)
    assert sales[0].resolved_rate == pytest.approx(-0.10)
    # The purchase itself is still paid in full; the proceeds are a separate inflow.
    new_car = [line for line in ledger.lines if line.label == "Новый автомобиль"]
    assert [line.amount for line in new_car] == [pytest.approx(-5_000_000.0 * 1.09**3)]


def test_the_sale_follows_t0_and_the_target_year_of_the_goal() -> None:
    # A dated goal sits on the t0 anniversary of its target year, and so does the sale: move t0
    # and the sale moves with it; move the target year and the price is a year's less decay.
    ledger = build_ledger(SALE_INPUTS.model_copy(update={"t0": "2026-06"}))
    sales = ledger.lines_of("asset_sale")
    assert sales[0].month == "2029-06"
    assert sales[0].amount == pytest.approx(6_000_000.0 * 0.9**3)

    earlier = SALE_INPUTS.model_copy(
        update={"goals": (*INPUTS.goals, NEW_CAR.model_copy(update={"target_year": 2028}))}
    )
    sales = build_ledger(earlier).lines_of("asset_sale")
    assert sales[0].month == "2028-08"
    assert sales[0].amount == pytest.approx(6_000_000.0 * 0.9**2)


def test_the_sold_asset_leaves_the_other_assets_from_the_sale_month() -> None:
    sold = build_ledger(SALE_INPUTS)
    kept = build_ledger(KEEP_INPUTS)

    # Up to the month before the sale the two plans are the same net worth.
    assert sold.non_working_balance[35] == pytest.approx(kept.non_working_balance[35])
    assert sold.non_working_balance[35] - build_ledger(INPUTS).non_working_balance[35] == pytest.approx(
        6_000_000.0 * 0.9 ** (35 / 12)
    )
    # From the sale month on, the old car is gone — and only the old car.
    for n in range(36, 60):
        assert kept.non_working_balance[n] - sold.non_working_balance[n] == pytest.approx(
            6_000_000.0 * 0.9 ** (n / 12)
        )
    # The new car is there at its purchase price the same month, as before.
    assert sold.non_working_balance[36] - build_ledger(INPUTS).non_working_balance[36] == pytest.approx(
        5_000_000.0 * 1.09**3
    )


def test_the_sale_proceeds_reach_the_portfolio_and_nothing_else_changes() -> None:
    sold = build_ledger(SALE_INPUTS)
    kept = build_ledger(KEEP_INPUTS)

    # Everything the household nets ends up in the portfolio or in the buffer: the only
    # difference between the two plans is the proceeds.
    reaches = sum(sold.portfolio_flow.values()) + sold.buffer_balance[-1]
    reaches_without = sum(kept.portfolio_flow.values()) + kept.buffer_balance[-1]
    assert reaches - reaches_without == pytest.approx(4_374_000.0)
    # Until the buffer's 12-month lookahead reaches the sale month, the two plans are identical
    # month by month; from month 24 the buffer may save less, since the net deficit it sees at
    # month 36 is smaller by the proceeds.
    for n in range(0, 24):
        assert sold.portfolio_flow[sold.months[n]] == pytest.approx(kept.portfolio_flow[kept.months[n]])


def test_replacing_an_asset_the_plan_does_not_have_is_a_loud_error() -> None:
    inputs = INPUTS.model_copy(update={"goals": (*INPUTS.goals, NEW_CAR)})

    with pytest.raises(UnknownSoldAssetError, match="Старый автомобиль"):
        build_ledger(inputs)


def test_replacing_an_asset_that_is_not_non_working_is_a_loud_error() -> None:
    portfolio_car = AssetIn(
        label="Старый автомобиль", amount=6_000_000.0, currency="RUB", asset_class="portfolio"
    )
    inputs = SALE_INPUTS.model_copy(update={"assets": (*INPUTS.assets, portfolio_car)})

    with pytest.raises(UnknownSoldAssetError, match="non_working"):
        build_ledger(inputs)


def test_replacing_an_ambiguous_label_is_a_loud_error() -> None:
    inputs = SALE_INPUTS.model_copy(update={"assets": (*SALE_INPUTS.assets, OLD_CAR)})

    with pytest.raises(UnknownSoldAssetError, match="two"):
        build_ledger(inputs)


def test_selling_one_asset_twice_is_a_loud_error() -> None:
    again = NEW_CAR.model_copy(update={"goal_id": 4, "label": "Ещё один автомобиль", "target_year": 2030})
    inputs = SALE_INPUTS.model_copy(update={"goals": (*SALE_INPUTS.goals, again)})

    with pytest.raises(DuplicateAssetSaleError, match="Старый автомобиль"):
        build_ledger(inputs)


# A plan whose every number is flat: no indexation, a 100 000 surplus every month, retirement far
# away. The car (month 36, three years out) is a savings goal; the house (month 60, five years) is an
# investment goal and gets only the usual 12-month pre-saving.
ZERO_RATES = Rates(
    inflation_rate=0.0,
    expense_indexation_rate=0.0,
    income_indexation_rate=0.0,
    goal_indexation_rate=0.0,
    discount_rate=0.0,
    buffer_rate=0.0,
)
SAVINGS_CAR = GoalIn(
    goal_id=1,
    label="Автомобиль",
    kind="lump",
    amount_pv=2_400_000.0,
    pv_year=2026,
    target_year=2029,
)
HOUSE = GoalIn(goal_id=2, label="Дом", kind="lump", amount_pv=10_000_000.0, pv_year=2026, target_year=2031)
SAVINGS_INPUTS = PlanInputs(
    t0="2026-08",
    horizon_years=10,
    retirement_year=2035,
    buffer_lookahead_months=12,
    savings_horizon_years=5,
    rates=ZERO_RATES,
    assets=(AssetIn(label="Брокерский счёт", amount=1_000_000.0, currency="RUB", asset_class="portfolio"),),
    budget_items=(
        BudgetItemIn(kind="income", label="Зарплата", monthly_amount=300_000.0, end_rule="until_retirement"),
        BudgetItemIn(kind="expense", label="Расходы семьи", monthly_amount=200_000.0),
    ),
    goals=(
        SAVINGS_CAR,
        HOUSE,
        GoalIn(
            goal_id=3,
            label="Пассивный доход от портфеля",
            kind="retirement_income",
            amount_pv=100_000.0,
            pv_year=2026,
            target_year=2035,
        ),
    ),
)


# the same plan under the retirement rule. Both the car (month 36) and the house (month 60)
# come before retirement (2035), so both are saved for from month 0.
UNTIL_RETIREMENT = SAVINGS_INPUTS.model_copy(
    update={"savings_horizon_years": None, "reserves_until_retirement": True}
)


def test_under_the_retirement_rule_every_purchase_before_retirement_is_saved_for() -> None:
    ledger = build_ledger(UNTIL_RETIREMENT)
    flow = [ledger.portfolio_flow[month] for month in ledger.months]

    # 100 000 a month from month 0 against 12 400 000 ahead: nothing reaches the portfolio.
    assert flow[:36] == pytest.approx([0.0] * 36)
    assert ledger.buffer_balance[35] == pytest.approx(3_600_000.0)
    # The car month: 100 000 - 2 400 000 = -2 300 000 comes out of the buffer.
    assert flow[36] == pytest.approx(0.0)
    assert ledger.buffer_balance[36] == pytest.approx(1_300_000.0)
    # 23 more months of 100 000, then the house: 100 000 - 10 000 000 = -9 900 000,
    # 3 600 000 from the buffer, 6 300 000 from the portfolio.
    assert ledger.buffer_balance[59] == pytest.approx(3_600_000.0)
    assert flow[60] == pytest.approx(-6_300_000.0)
    assert flow[61] == pytest.approx(100_000.0)


def test_under_the_retirement_rule_the_buffer_does_not_save_for_the_pension() -> None:
    ledger = build_ledger(UNTIL_RETIREMENT)
    flow = [ledger.portfolio_flow[month] for month in ledger.months]

    # Retirement is month 108. The old rule saved the last year's 100 000 a month for the
    # pension (1 200 000 in the buffer at month 107, nothing invested in months 96..107); now
    # the surplus is invested and the portfolio pays the first pension month:
    # -200 000 expenses - 100 000 pension.
    assert flow[96:108] == pytest.approx([100_000.0] * 12)
    assert ledger.buffer_balance[107] == pytest.approx(0.0)
    assert flow[108] == pytest.approx(-300_000.0)


def test_the_old_rule_still_saves_the_last_year_for_the_pension() -> None:
    ledger = build_ledger(SAVINGS_INPUTS)
    flow = [ledger.portfolio_flow[month] for month in ledger.months]

    # Measured on the code before the retirement rule: the snapshot without the flag must keep these numbers.
    assert flow[96:108] == pytest.approx([0.0] * 12)
    assert ledger.buffer_balance[107] == pytest.approx(1_200_000.0)


def test_a_savings_goal_is_filled_from_the_first_month_and_never_touches_the_portfolio() -> None:
    ledger = build_ledger(SAVINGS_INPUTS)
    flow = [ledger.portfolio_flow[month] for month in ledger.months]

    # 2 400 000 at 100 000 a month: the buffer is full after month 23, the portfolio gets nothing
    # until then and the whole surplus from month 24.
    assert ledger.buffer_balance[0] == pytest.approx(100_000.0)
    assert ledger.buffer_balance[23] == pytest.approx(2_400_000.0)
    assert flow[:24] == pytest.approx([0.0] * 24)
    assert flow[24:36] == pytest.approx([100_000.0] * 12)
    # The purchase month: the buffer pays, the portfolio is untouched, the month's own surplus
    # stays in the buffer until the next month releases it.
    assert flow[36] == pytest.approx(0.0)
    assert ledger.buffer_balance[36] == pytest.approx(100_000.0)
    assert flow[37] == pytest.approx(200_000.0)


def test_an_investment_goal_gets_only_the_usual_twelve_month_pre_saving() -> None:
    house_only = SAVINGS_INPUTS.model_copy(update={"goals": SAVINGS_INPUTS.goals[1:]})
    ledger = build_ledger(house_only)
    flow = [ledger.portfolio_flow[month] for month in ledger.months]

    assert ledger.buffer_balance[:48] == pytest.approx([0.0] * 48)
    assert ledger.buffer_balance[59] == pytest.approx(1_200_000.0)
    # 10 000 000 less the month's surplus less the 1 200 000 saved: the portfolio pays the rest.
    assert flow[60] == pytest.approx(-8_700_000.0)


def test_a_savings_goal_the_surplus_cannot_reach_leaves_a_shortfall_for_the_portfolio() -> None:
    dearer = SAVINGS_CAR.model_copy(update={"amount_pv": 5_000_000.0})
    expensive = SAVINGS_INPUTS.model_copy(update={"goals": (dearer, *SAVINGS_INPUTS.goals[1:])})
    ledger = build_ledger(expensive)

    # 36 months of 100 000 (months 0..35) — 3 600 000 — against a 5 000 000 car: the month's own
    # 100 000 and the buffer cover 3 700 000, the portfolio pays 1 300 000.
    assert ledger.buffer_balance[35] == pytest.approx(3_600_000.0)
    assert ledger.portfolio_flow["2029-08"] == pytest.approx(-1_300_000.0)


def test_the_proceeds_of_a_replaced_asset_reduce_what_is_saved_for_a_savings_goal() -> None:
    old_car = AssetIn(
        label="Старый автомобиль",
        amount=1_000_000.0,
        currency="RUB",
        asset_class="non_working",
        growth_rate=0.0,
    )
    new_car = SAVINGS_CAR.model_copy(update={"replaces_asset": "Старый автомобиль"})
    replaced = SAVINGS_INPUTS.model_copy(
        update={"assets": (*SAVINGS_INPUTS.assets, old_car), "goals": (new_car, *SAVINGS_INPUTS.goals[1:])}
    )
    ledger = build_ledger(replaced)
    flow = [ledger.portfolio_flow[month] for month in ledger.months]

    # Only 1 400 000 has to be saved: full after month 13, the surplus invests from month 14.
    assert ledger.buffer_balance[13] == pytest.approx(1_400_000.0)
    assert flow[14] == pytest.approx(100_000.0)
    assert flow[36] == pytest.approx(0.0)


def test_without_a_savings_horizon_the_ledger_is_exactly_what_it_was() -> None:
    plain = build_ledger(SAVINGS_INPUTS.model_copy(update={"savings_horizon_years": None}))

    # The car is then an investment goal: pre-saved for 12 months like the house.
    assert plain.buffer_balance[:24] == pytest.approx([0.0] * 24)
    assert plain.buffer_balance[35] == pytest.approx(1_200_000.0)
    assert plain.portfolio_flow["2029-08"] == pytest.approx(-1_100_000.0)


def test_the_ledger_splits_the_buffer_by_purchase_under_the_retirement_rule() -> None:
    ledger = build_ledger(UNTIL_RETIREMENT)
    by_label = {part.goal_label: part.balance for part in ledger.buffer_by_goal}

    assert list(by_label) == ["Автомобиль", "Дом", None]
    # Month 35: 3 600 000 on hand — 2 400 000 is the car's, the other 1 200 000 the house's.
    assert by_label["Автомобиль"][35] == pytest.approx(2_400_000.0)
    assert by_label["Дом"][35] == pytest.approx(1_200_000.0)
    # After the car month the car's row is empty; month 59 is all house.
    assert by_label["Автомобиль"][36] == pytest.approx(0.0)
    assert by_label["Дом"][59] == pytest.approx(3_600_000.0)
    assert max(by_label[None]) == pytest.approx(0.0)


def test_no_split_without_the_retirement_rule() -> None:
    assert build_ledger(SAVINGS_INPUTS).buffer_by_goal == ()


def test_the_ledger_tracks_the_debt_and_the_principal_repaid_each_month() -> None:
    ledger = build_ledger(INPUTS)

    assert len(ledger.liability_balance) == len(ledger.months)
    assert len(ledger.principal_repaid) == len(ledger.months)
    # 1 000 000 at 12 %, 100 000 a month, from t0: 910 000 left after the first instalment.
    assert ledger.liability_balance[0] == pytest.approx(910_000.0)
    assert ledger.principal_repaid[0] == pytest.approx(90_000.0)
    assert ledger.liability_balance[1] == pytest.approx(819_100.0)
    # Eleven instalments clear it: month 10 is the last, month 11 onwards is debt-free.
    assert ledger.liability_balance[10] == pytest.approx(0.0, abs=1e-6)
    assert ledger.liability_balance[11] == 0.0 and ledger.principal_repaid[11] == 0.0
    # The principal repaid over the life of the loan is the loan.
    assert sum(ledger.principal_repaid) == pytest.approx(1_000_000.0)


def test_two_loans_add_up_in_the_track() -> None:
    second = INPUTS.liabilities[0].model_copy(update={"label": "Автокредит", "principal": 500_000.0})
    ledger = build_ledger(INPUTS.model_copy(update={"liabilities": (*INPUTS.liabilities, second)}))

    # 500 000 at 1 % a month paying 100 000: 5 000 interest, 95 000 principal, 405 000 left.
    assert ledger.liability_balance[0] == pytest.approx(910_000.0 + 405_000.0)
    assert ledger.principal_repaid[0] == pytest.approx(90_000.0 + 95_000.0)


def test_before_the_rule_the_expenses_run_beside_the_pension() -> None:
    # 2030-08 is month 48, the fourth anniversary: expenses 300 000 · 1.10^4, pension 200 000 · 1.09^4.
    ledger = build_ledger(INPUTS)

    assert ledger.portfolio_flow["2030-08"] == pytest.approx(-(300_000.0 * 1.1**4 + 200_000.0 * 1.09**4))


def test_a_snapshot_written_before_the_pension_expenses_rule_replays_the_old_ledger() -> None:
    """Legacy input control: a snapshot missing ``pension_replaces_expenses`` and each goal's
    ``amount_basis`` must build the doubled ledger it always did, not the new rule."""
    old = INPUTS.model_dump(mode="json")
    del old["pension_replaces_expenses"]
    for goal in old["goals"]:
        del goal["amount_basis"]

    ledger = build_ledger(PlanInputs.model_validate(old))

    assert _amounts([line for line in ledger.lines if line.month == "2030-08"], "expense") != []
    # 2030-08 is month 48, the fourth anniversary: expenses 300 000 · 1.10^4, pension 200 000 ·
    # 1.09^4 — both run at once, the doubling as it was before pension expense replacement.
    # -439 230 - 282 316.32 = -721 546.32
    assert ledger.portfolio_flow["2030-08"] == pytest.approx(-(300_000.0 * 1.1**4 + 200_000.0 * 1.09**4))


def test_under_the_rule_a_pension_sum_replaces_the_expenses_from_retirement() -> None:
    ledger = build_ledger(REPLACED)

    expense_months = sorted({line.month for line in ledger.lines if line.line_kind == "expense"})
    assert expense_months[-1] == "2029-07"  # retirement is 2029-08, month 36
    # The buffer is spent a year after retirement; the pension alone reaches the portfolio.
    assert ledger.portfolio_flow["2030-08"] == pytest.approx(-200_000.0 * 1.09**4)


def test_income_after_retirement_stays_income_and_reduces_the_withdrawal() -> None:
    """Retirement income rule: an income earned after retirement (a state pension, say) stays an
    ``income`` line — ``_kept_budget_lines`` only drops ``expense`` lines from retirement on, and
    must not sweep income away with them."""
    pension_income = BudgetItemIn(
        kind="income",
        label="Госпенсия",
        monthly_amount=30_000.0,
        start_month="2029-08",
    )
    inputs = REPLACED.model_copy(update={"budget_items": (*REPLACED.budget_items, pension_income)})
    ledger = build_ledger(inputs)

    august = [line for line in ledger.lines if line.month == "2030-08"]
    assert [line for line in august if line.line_kind == "expense"] == []
    income_lines = [line for line in august if line.line_kind == "income"]
    assert len(income_lines) == 1
    # Month 48 is 12 months after the 2029-08 start (month 36): value_at_month steps on each
    # anniversary, so n // 12 == 4 raises: 30 000 · 1.06^4 (income_indexation_rate default).
    income_amount = 30_000.0 * 1.06**4
    assert income_lines[0].amount == pytest.approx(income_amount)
    # The pension alone would leave -200 000 · 1.09^4 == -282 316.32; the income on top of it
    # reduces what the portfolio must supply that month by exactly its own amount.
    assert ledger.portfolio_flow["2030-08"] == pytest.approx(-200_000.0 * 1.09**4 + income_amount)


def test_the_flag_off_still_needs_the_expenses_for_a_share_pension() -> None:
    """``build_ledger`` must pass ``expenses=None`` when the flag is off, even for a plan that
    otherwise looks like SHARE — the loud error from expand_goals must still surface."""
    with pytest.raises(ValueError, match="share of the family expenses"):
        build_ledger(SHARE.model_copy(update={"pension_replaces_expenses": False}))


def test_under_the_rule_a_pension_share_is_that_share_of_the_expenses() -> None:
    ledger = build_ledger(SHARE)

    august = [
        line
        for line in ledger.lines
        if line.month == "2030-08" and line.line_kind in {"expense", "goal_outflow"}
    ]
    assert [(line.line_kind, line.goal_id) for line in august] == [("goal_outflow", 2)]
    assert august[0].amount == pytest.approx(-300_000.0 * 1.1**4)
    assert august[0].resolved_rate == pytest.approx(0.10)
    assert ledger.portfolio_flow["2030-08"] == pytest.approx(-300_000.0 * 1.1**4)


def test_a_share_takes_every_expense_item_of_the_month_each_at_its_own_rate() -> None:
    treatment = BudgetItemIn(
        kind="expense",
        label="Лечение",
        monthly_amount=20_000.0,
        indexation_rate=0.05,
        start_month="2030-08",
    )
    inputs = SHARE.model_copy(
        update={
            "budget_items": (*INPUTS.budget_items, treatment),
            "goals": (INPUTS.goals[0], SHARE.goals[1].model_copy(update={"amount_pv": 0.7})),
        }
    )
    ledger = build_ledger(inputs)

    def pension(month: str) -> LedgerLine:
        return next(
            line
            for line in ledger.lines
            if line.line_kind == "goal_outflow" and line.goal_id == 2 and line.month == month
        )

    # 2030-07, month 47: the family expenses alone, three raises at 10 %.
    assert pension("2030-07").amount == pytest.approx(-0.7 * 300_000.0 * 1.1**3)
    assert pension("2030-07").resolved_rate == pytest.approx(0.10)
    # 2030-08, month 48: the treatment starts after retirement and joins at its own 5 %.
    assert pension("2030-08").amount == pytest.approx(-0.7 * (300_000.0 * 1.1**4 + 20_000.0 * 1.05**4))
    assert pension("2030-08").resolved_rate is None


def test_the_rule_leaves_a_plan_without_a_pension_alone() -> None:
    no_pension = REPLACED.model_copy(update={"goals": (INPUTS.goals[0],)})

    assert len(build_ledger(no_pension).lines_of("expense")) == 60


def test_under_the_rule_every_line_is_still_accounted_for() -> None:
    """The count moves exactly as the rule says: the expense runs 36 months (0..35) instead of 60,
    and the pension keeps its 24 (36..59) beside the one car line."""
    ledger = build_ledger(REPLACED)

    accounted_for = {"income", "expense", "mortgage_payment", "goal_outflow", "reserve_topup"}
    accounted_lines = [line for line in ledger.lines if line.line_kind in accounted_for]
    assert len(accounted_lines) == 36 + 36 + 11 + 25 + 0

    total_in = sum(line.amount for line in accounted_lines)
    total_out = sum(ledger.portfolio_flow.values()) + ledger.buffer_balance[-1]
    assert total_in == pytest.approx(total_out)


def test_a_savings_asset_with_its_own_rate_fails_the_ledger() -> None:
    # A snapshot that bypassed the import still cannot carry a second reserve rate.
    rated = AssetIn(
        label="Облигации",
        amount=1_000_000.0,
        currency="RUB",
        asset_class="savings",
        growth_rate=0.148,
    )
    with pytest.raises(SavingsAssetRateError, match="Облигации"):
        build_ledger(INPUTS.model_copy(update={"assets": (*INPUTS.assets, rated)}))


SAVINGS_RATES = Rates(
    inflation_rate=0.0,
    expense_indexation_rate=0.0,
    income_indexation_rate=0.0,
    goal_indexation_rate=0.0,
    discount_rate=0.0,
    buffer_rate=0.12,
)
FLAT = GoalIn(
    goal_id=1,
    label="Квартира",
    kind="lump",
    amount_pv=2_000_000.0,
    pv_year=2026,
    target_year=2028,
)
# The purchase 2 000 000 in month 24 (2028-08); 1 000 000 already set aside, 20 000 saved a month,
# the reserve earning 12 % a year — every number below is f = 1.12 ** (1 / 12) compounding by hand.
SEEDED = PlanInputs(
    t0="2026-08",
    horizon_years=6,
    retirement_year=2031,
    buffer_lookahead_months=12,
    reserves_until_retirement=True,
    rates=SAVINGS_RATES,
    assets=(
        AssetIn(label="Брокерский счёт", amount=500_000.0, currency="RUB", asset_class="portfolio"),
        AssetIn(label="Облигации", amount=1_000_000.0, currency="RUB", asset_class="savings"),
    ),
    budget_items=(BudgetItemIn(kind="income", label="Профицит", monthly_amount=20_000.0),),
    goals=(FLAT,),
)


def _with_savings(amount: float, goals: tuple[GoalIn, ...] = (FLAT,)) -> PlanInputs:
    assets = (
        SEEDED.assets[0],
        AssetIn(label="Облигации", amount=amount, currency="RUB", asset_class="savings"),
    )
    return SEEDED.model_copy(update={"assets": assets, "goals": goals})


def test_savings_open_the_purchase_reserve_and_pay_the_purchase() -> None:
    ledger = build_ledger(SEEDED)
    flow = [ledger.portfolio_flow[key] for key in ledger.months]

    assert ledger.buffer_balance[0] == pytest.approx(1_020_000.0)
    assert ledger.buffer_balance[1] == pytest.approx(1_049_678.57, abs=0.01)
    assert ledger.buffer_balance[23] == pytest.approx(1_778_820.65, abs=0.01)
    # Nothing reaches the portfolio before the purchase: every surplus goes to the reserve.
    assert flow[:24] == pytest.approx([0.0] * 24)
    assert flow[24] == pytest.approx(-184_300.49, abs=0.01)
    assert ledger.buffer_balance[24] == pytest.approx(0.0)


def test_savings_beyond_the_purchase_go_to_the_portfolio_at_once() -> None:
    ledger = build_ledger(_with_savings(3_000_000.0))

    assert ledger.portfolio_flow["2026-08"] == pytest.approx(1_020_000.0)
    assert ledger.portfolio_flow["2026-09"] == pytest.approx(38_977.59, abs=0.01)


def test_savings_without_a_purchase_go_to_the_portfolio_in_t0() -> None:
    ledger = build_ledger(_with_savings(1_000_000.0, goals=()))

    assert ledger.portfolio_flow["2026-08"] == pytest.approx(1_020_000.0)
    assert ledger.buffer_balance[0] == pytest.approx(0.0)


def test_savings_cover_a_deficit_in_the_first_month() -> None:
    now = FLAT.model_copy(update={"amount_pv": 1_500_000.0, "target_year": 2026})
    ledger = build_ledger(_with_savings(1_000_000.0, goals=(now,)))

    assert ledger.portfolio_flow["2026-08"] == pytest.approx(-480_000.0)


def test_a_plan_without_savings_starts_the_reserve_at_zero_as_before() -> None:
    # A snapshot without a savings asset keeps its previous ledger: it is what it always was.
    without = SEEDED.model_copy(update={"assets": SEEDED.assets[:1]})
    replayed = PlanInputs.model_validate_json(without.model_dump_json())

    assert build_ledger(replayed).buffer_balance[0] == pytest.approx(20_000.0)
    assert build_ledger(replayed) == build_ledger(without)


def test_savings_beyond_the_need_leave_the_reserve_in_a_deficit_month_too() -> None:
    # 1 000 000 set aside, a 100 000 purchase in t0: the reserve pays 80 000 of it (20 000 is
    # the month's own surplus) and, needing nothing further, releases the other 920 000 at once.
    small = FLAT.model_copy(update={"amount_pv": 100_000.0, "target_year": 2026})
    ledger = build_ledger(_with_savings(1_000_000.0, goals=(small,)))

    assert ledger.portfolio_flow["2026-08"] == pytest.approx(920_000.0)
    assert ledger.buffer_balance[0] == pytest.approx(0.0)


def test_savings_keep_only_the_window_when_every_month_is_a_deficit() -> None:
    # No purchase, 10 000 spent a month: the reserve keeps the next 12 months' deficits,
    # 120 000, and the rest of 1 000 000 less this month's 10 000 goes to the portfolio in t0.
    spending = _with_savings(1_000_000.0, goals=()).model_copy(
        update={"budget_items": (BudgetItemIn(kind="expense", label="Расходы", monthly_amount=10_000.0),)}
    )
    ledger = build_ledger(spending)

    assert ledger.portfolio_flow["2026-08"] == pytest.approx(870_000.0)
    assert ledger.buffer_balance[0] == pytest.approx(120_000.0)
