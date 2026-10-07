"""Per-goal outcomes.

The retirement stage withdraws every month, so a scenario can die of a drawdown rather than of a
goal. One number is not enough, and the two must not be confused:

* ``p_affordable`` — the share of scenarios whose balance the month *before* the goal covered
  the portfolio's own share of it: what the portfolio was actually asked to pay that month.
  The buffer pre-saves part of every lump goal — all of a savings goal, the deficit of an
  investment goal's month — and that part is a deposit, without market risk, so the goal's only
  uncertainty is the withdrawal. Nothing withdrawn: affordable in every scenario. This is what
  the client is shown, with an explicit caption.
* ``p_alive`` — the share of scenarios that reached that month with a positive balance. Internal:
  it explains why late goals sag, and is never reported as "the probability of this goal".
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from okama_planner.inputs import GoalIn, PlanInputs
from okama_planner.ledger.calendar import month_key, year_index
from okama_planner.ledger.goals import goal_month_index
from okama_planner.ledger.types import Ledger
from okama_planner.ledger.indexation import value_in_year
from okama_planner.rates import RateSubject, resolve_rate


@dataclass(frozen=True, slots=True)
class GoalOutcome:
    goal_id: int | None
    label: str
    month: str
    amount_nominal: float
    p_affordable: float
    p_alive: float


def _row(wealth: pd.DataFrame, month: str) -> pd.Series:
    return wealth.loc[pd.Period(month, freq="M")]


def p_alive(wealth: pd.DataFrame, month: str) -> float:
    """Share of scenarios that reached ``month`` with a positive balance."""
    return float((_row(wealth, month) > 0.0).mean())


def p_affordable(wealth: pd.DataFrame, month: str, amount: float) -> float:
    """Share of scenarios holding at least ``amount`` in ``month``."""
    return float((_row(wealth, month) >= amount).mean())


def _months_in(wealth: pd.DataFrame) -> set[str]:
    return {f"{period}" for period in wealth.index}


def _pension_outflow(ledger: Ledger, goal: GoalIn, month: str) -> float:
    """What the pension stream pays in ``month``, read off the ledger. A pension sized as a share of
    the family expenses has no amount of its own to index; for a sum the line holds the very
    number the indexation formula gives."""
    return -sum(
        (
            line.amount
            for line in ledger.lines
            if line.line_kind == "goal_outflow"
            and line.month == month
            and (line.goal_id == goal.goal_id if line.goal_id is not None else line.label == goal.label)
        ),
        0.0,
    )


def _portfolio_share(ledger: Ledger, month: str, amount: float, goal_label: str) -> float:
    """What the portfolio was asked to pay in ``month``, at most the goal's own amount: a savings
    goal the buffer covered costs the portfolio nothing; a shortfall shows as a withdrawal."""
    if goal_label in ledger.goal_portfolio_shares:
        return min(amount, ledger.goal_portfolio_shares[goal_label])
    return min(amount, max(0.0, -ledger.portfolio_flow.get(month, 0.0)))


def goal_outcomes(wealth: pd.DataFrame, inputs: PlanInputs, ledger: Ledger) -> tuple[GoalOutcome, ...]:
    """Measure every dated goal against the wealth paths, the month before it falls due.

    ``ledger`` is the run's own ledger: a lump goal — savings or investment alike — is measured on
    the withdrawal the portfolio made for it (``portfolio_flow`` in the goal's month, capped at the
    goal); the pension is a stream and is measured on its own monthly amount.
    """
    available = _months_in(wealth)
    outcomes: list[GoalOutcome] = []

    for goal in inputs.goals:
        if goal.kind == "retirement_income":
            n = year_index(inputs.t0, inputs.retirement_year)
        elif goal.target_year is None:
            continue
        else:
            n = goal_month_index(goal, inputs.t0)
        if n < 0:
            continue

        due = month_key(inputs.t0, n)
        before = month_key(inputs.t0, n - 1)
        if due not in available or before not in available:
            continue

        rate = resolve_rate(RateSubject.GOAL, goal.indexation_rate, inputs.rates)
        if goal.kind == "retirement_income":
            amount = _pension_outflow(ledger, goal, due)
        else:
            # The goal's own year, as the ledger prices it — not calendar_year(t0, n): the amount
            # is indexed by whole years and must not depend on the month the goal falls on.
            amount = value_in_year(goal.amount_pv, rate, goal.pv_year, goal.target_year)
        if goal.kind in {"lump", "reserve_topup"}:
            required = amount
            if goal.kind == "reserve_topup":
                transferred = -sum(
                    line.amount
                    for line in ledger.lines
                    if line.line_kind == "reserve_topup" and line.month == due
                )
                already_funded = ledger.reserve_balance[n] - transferred
                required = max(0.0, amount - already_funded)
            residual = _portfolio_share(ledger, due, required, goal.label)
            # Fully covered by the buffer: paid from the deposit whatever the portfolio did, even
            # in a scenario that is already dead — hence 1.0 outright, not "balance >= 0".
            affordable = 1.0 if residual == 0.0 else p_affordable(wealth, before, residual)
        else:
            affordable = p_affordable(wealth, before, amount)
        outcomes.append(
            GoalOutcome(
                goal_id=goal.goal_id,
                label=goal.label,
                month=due,
                amount_nominal=amount,
                p_affordable=affordable,
                # BOTH are measured in the month BEFORE the goal, and that is the whole point:
                # they are only comparable at the same moment. Measuring p_alive in the goal's own
                # month contaminates it — the goal's outflow is already subtracted there, so a
                # scenario that could afford the goal can read as "not alive" for a reason that
                # has nothing to do with survival. Both outcomes use the preceding month.
                p_alive=p_alive(wealth, before),
            )
        )
    return tuple(outcomes)
