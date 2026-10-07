"""Income and expense lines: indexed by their own resolved rate, cut off by their own end rule."""

from __future__ import annotations

import pytest

from okama_planner.inputs import BudgetItemIn, Rates
from okama_planner.ledger.budget import budget_lines

RATES = Rates(
    inflation_rate=0.09,
    expense_indexation_rate=0.10,
    income_indexation_rate=0.06,
    goal_indexation_rate=0.08,
    discount_rate=0.09,
    buffer_rate=0.0,
)
SALARY = BudgetItemIn(kind="income", label="Зарплата", monthly_amount=450_000.0, end_rule="until_retirement")
HOUSEHOLD = BudgetItemIn(kind="expense", label="Расходы семьи", monthly_amount=300_000.0)


def _lines(*items: BudgetItemIn, months: int = 36, retirement_index: int = 24):
    return budget_lines(items, t0="2026-08", months=months, retirement_index=retirement_index, rates=RATES)


def test_income_is_positive_and_indexed_by_the_income_rate() -> None:
    lines = [line for line in _lines(SALARY) if line.line_kind == "income"]

    assert lines[0].amount == pytest.approx(450_000.0)
    assert lines[0].resolved_rate == pytest.approx(0.06)
    assert lines[12].amount == pytest.approx(450_000.0 * 1.06)


def test_expense_is_negative_and_indexed_by_the_expense_rate() -> None:
    lines = [line for line in _lines(HOUSEHOLD) if line.line_kind == "expense"]

    assert lines[0].amount == pytest.approx(-300_000.0)
    assert lines[0].resolved_rate == pytest.approx(0.10)
    assert lines[12].amount == pytest.approx(-300_000.0 * 1.10)


def test_a_per_row_rate_overrides_the_run_rate() -> None:
    tuition = BudgetItemIn(kind="expense", label="Обучение", monthly_amount=50_000.0, indexation_rate=0.15)
    lines = [line for line in _lines(tuition) if line.label == "Обучение"]

    assert lines[0].resolved_rate == pytest.approx(0.15)
    assert lines[12].amount == pytest.approx(-50_000.0 * 1.15)


def test_until_retirement_stops_the_month_retirement_starts() -> None:
    lines = [line for line in _lines(SALARY) if line.line_kind == "income"]

    # retirement_index = 24, so the last salary is month 23 and month 24 has none.
    assert len(lines) == 24
    assert lines[-1].month == "2028-07"


def test_expenses_run_the_whole_horizon() -> None:
    lines = [line for line in _lines(HOUSEHOLD) if line.line_kind == "expense"]

    assert len(lines) == 36


def test_start_month_and_until_month_clip_the_stream() -> None:
    nursery = BudgetItemIn(
        kind="expense",
        label="Садик",
        monthly_amount=40_000.0,
        start_month="2027-02",
        end_rule="until_month",
        end_month="2027-05",
    )
    lines = [line for line in _lines(nursery) if line.label == "Садик"]

    assert [line.month for line in lines] == ["2027-02", "2027-03", "2027-04", "2027-05"]


def test_until_month_without_end_month_raises() -> None:
    broken = BudgetItemIn(
        kind="expense", label="Забытая дата", monthly_amount=10_000.0, end_rule="until_month"
    )
    with pytest.raises(ValueError, match=r"Забытая дата: end_rule 'until_month' needs an end_month"):
        _lines(broken)


def test_unknown_kind_raises() -> None:
    broken = BudgetItemIn(kind="nonsense", label="Битая строка", monthly_amount=10_000.0)
    with pytest.raises(ValueError, match=r"Битая строка: unknown budget kind 'nonsense'"):
        _lines(broken)


def test_start_month_before_t0_clamps_to_t0() -> None:
    early = BudgetItemIn(kind="expense", label="Уже шёл", monthly_amount=20_000.0, start_month="2026-01")
    lines = [line for line in _lines(early, months=12) if line.label == "Уже шёл"]

    # t0 is "2026-08", so the line starts there, not in "2026-01"
    assert lines[0].month == "2026-08"
    assert len(lines) == 12  # Full remaining span from t0


def test_start_month_after_horizon_produces_no_lines() -> None:
    future = BudgetItemIn(
        kind="expense", label="Будущая трата", monthly_amount=20_000.0, start_month="2030-01"
    )
    lines = [line for line in _lines(future, months=12) if line.label == "Будущая трата"]

    assert len(lines) == 0


def test_end_month_before_start_month_raises() -> None:
    backwards = BudgetItemIn(
        kind="expense",
        label="Перепутал даты",
        monthly_amount=15_000.0,
        start_month="2027-06",
        end_rule="until_month",
        end_month="2027-02",
    )
    with pytest.raises(ValueError, match=r"Перепутал даты: end_month 2027-02 is before start_month 2027-06"):
        _lines(backwards)


def test_both_dates_past_horizon_in_correct_order_produces_no_lines() -> None:
    future = BudgetItemIn(
        kind="expense",
        label="Аренда дачи",
        monthly_amount=50_000.0,
        start_month="2030-01",
        end_rule="until_month",
        end_month="2031-01",
    )
    # t0="2026-08", months=36 → horizon ends 2029-07
    # Both dates are beyond, but in the correct order: 2030-01 < 2031-01
    lines = [line for line in _lines(future, months=36) if line.label == "Аренда дачи"]

    assert len(lines) == 0  # No error, just zero lines


def test_end_month_past_horizon_clips_to_horizon() -> None:
    extends = BudgetItemIn(
        kind="expense",
        label="Долгая аренда",
        monthly_amount=30_000.0,
        start_month="2028-01",
        end_rule="until_month",
        end_month="2030-12",
    )
    # t0="2026-08", months=36 → horizon ends 2029-07
    # start_month is inside, end_month is beyond
    lines = [line for line in _lines(extends, months=36) if line.label == "Долгая аренда"]

    # Should produce lines from 2028-01 through 2029-07 (clipped to horizon)
    assert lines[0].month == "2028-01"
    assert lines[-1].month == "2029-07"
    assert len(lines) == 19  # Jan 2028 to Jul 2029 inclusive
