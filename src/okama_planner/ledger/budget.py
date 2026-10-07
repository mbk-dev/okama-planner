"""Household income and expense streams.

Income stops at its end rule — ``until_retirement`` cuts it the month retirement starts.
Expenses run the whole horizon here; `build_ledger` drops them from the
retirement month of a plan with a pension goal, where they become that goal's stream.
"""

from __future__ import annotations

from collections.abc import Sequence

from okama_planner.inputs import BudgetItemIn, Rates
from okama_planner.ledger.calendar import month_index, month_key
from okama_planner.ledger.indexation import value_at_month
from okama_planner.ledger.types import LedgerLine
from okama_planner.rates import RateSubject, resolve_rate

_SUBJECT = {"income": RateSubject.INCOME, "expense": RateSubject.EXPENSE}


def _last_month(item: BudgetItemIn, t0: str, months: int, retirement_index: int) -> int:
    """The last month number, inclusive, this item is paid in."""
    if item.end_rule == "until_retirement":
        return min(months, retirement_index) - 1
    if item.end_rule == "until_month":
        if item.end_month is None:
            raise ValueError(f"{item.label}: end_rule 'until_month' needs an end_month")
        return min(months - 1, month_index(t0, item.end_month))
    return months - 1


def budget_lines(
    items: Sequence[BudgetItemIn], t0: str, months: int, retirement_index: int, rates: Rates
) -> tuple[LedgerLine, ...]:
    """Expand every budget item into one indexed line per month it is active."""
    lines: list[LedgerLine] = []
    for item in items:
        subject = _SUBJECT.get(item.kind)
        if subject is None:
            raise ValueError(f"{item.label}: unknown budget kind {item.kind!r}")
        rate = resolve_rate(subject, item.indexation_rate, rates)
        sign = 1.0 if item.kind == "income" else -1.0
        first = 0 if item.start_month is None else max(0, month_index(t0, item.start_month))
        last = _last_month(item, t0, months, retirement_index)
        if (
            item.end_rule == "until_month"
            and item.end_month is not None
            and item.start_month is not None
            and month_index(t0, item.end_month) < month_index(t0, item.start_month)
        ):
            raise ValueError(
                f"{item.label}: end_month {item.end_month} is before start_month {item.start_month}"
            )
        for n in range(first, last + 1):
            lines.append(
                LedgerLine(
                    month=month_key(t0, n),
                    line_kind=item.kind,
                    label=item.label,
                    amount=sign * value_at_month(item.monthly_amount, rate, n),
                    resolved_rate=rate,
                )
            )
    return tuple(lines)
