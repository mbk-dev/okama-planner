"""The one place a NULL rate is resolved into a number.

Indexation and discounting are not obliged to equal inflation: a client's own inflation, a career
path and the price of a flat move independently. ``inflation_rate`` is reported, never applied.
"""

from __future__ import annotations

from enum import StrEnum

from okama_planner.inputs import Rates


class RateSubject(StrEnum):
    """What is being indexed. The subject, not the row type, selects the fallback."""

    INCOME = "income"
    EXPENSE = "expense"
    GOAL = "goal"
    ASSET_RESERVE = "asset_reserve"
    ASSET_NON_WORKING = "asset_non_working"


class MissingRateError(ValueError):
    """A rate that must be given explicitly was left empty."""


_FALLBACK: dict[RateSubject, str] = {
    RateSubject.INCOME: "income_indexation_rate",
    RateSubject.EXPENSE: "expense_indexation_rate",
    RateSubject.GOAL: "goal_indexation_rate",
    # A reserve fund exists to cover expenses, so it tracks the client's own inflation.
    RateSubject.ASSET_RESERVE: "expense_indexation_rate",
}


def resolve_rate(subject: RateSubject, explicit: float | None, rates: Rates) -> float:
    """Return the rate actually applied to a row. Store it in ``ledger_row.resolved_rate``."""
    if explicit is not None:
        return explicit
    field = _FALLBACK.get(subject)
    if field is None:
        raise MissingRateError(
            f"{subject.value}: a growth_rate must be given explicitly for non_working assets"
        )
    return float(getattr(rates, field))
