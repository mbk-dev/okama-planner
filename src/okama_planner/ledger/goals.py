"""Goals become ledger lines.

Three kinds, three shapes: a ``lump`` is one dated outflow, ``retirement_income`` is a monthly
withdrawal stream — a sum of its own, or a share of the family expenses it replaces from
retirement —, and ``reserve_topup`` moves money into the reserve fund rather than out of the
plan. A goal with ``becomes_asset`` also creates a non-working asset the month it is bought, and
one with ``replaces_asset`` sells an existing one that same month.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from okama_planner.inputs import GoalIn, PlanInputs, Rates
from okama_planner.ledger.calendar import calendar_year, month_index, month_key, parse_month, year_index
from okama_planner.ledger.indexation import value_in_year
from okama_planner.ledger.types import LedgerLine
from okama_planner.rates import RateSubject, resolve_rate


@dataclass(frozen=True, slots=True)
class AcquiredAsset:
    """A purchase that turns into owned property: in the net worth, out of the portfolio."""

    month_index: int
    label: str
    value: float
    growth_rate: float


@dataclass(frozen=True, slots=True)
class AssetSale:
    """An owned asset given up the month a goal is bought. Labels only: the expansion never sees
    the assets, so the ledger prices the sale (the asset's value that month, at its own rate)."""

    month_index: int
    asset_label: str
    goal_label: str


@dataclass(frozen=True, slots=True)
class GoalExpansion:
    lines: tuple[LedgerLine, ...] = ()
    acquired: tuple[AcquiredAsset, ...] = ()
    reserve_targets: tuple[tuple[int, float, int | None], ...] = ()
    sold: tuple[AssetSale, ...] = ()


def _retirement_stream(
    goal: GoalIn, t0: str, months: int, retirement_index: int, rate: float
) -> list[LedgerLine]:
    """The monthly withdrawals from retirement to the horizon, indexed every anniversary of t0."""
    base_year = calendar_year(t0, 0)
    lines: list[LedgerLine] = []
    for n in range(retirement_index, months):
        # Anchored to the t0 anniversary, not the Gregorian January:
        # amount(n) = base * (1 + rate) ** (n // 12), restated with an explicit year so
        # value_in_year can price a pv_year that differs from t0's own year.
        year = base_year + n // 12
        amount = value_in_year(goal.amount_pv, rate, goal.pv_year, year)
        lines.append(
            LedgerLine(
                month=month_key(t0, n),
                line_kind="goal_outflow",
                label=goal.label,
                amount=-amount,
                resolved_rate=rate,
                goal_id=goal.goal_id,
            )
        )
    return lines


def _expense_share_stream(
    goal: GoalIn, t0: str, expenses: Sequence[LedgerLine], retirement_index: int
) -> list[LedgerLine]:
    """The family expenses from retirement on, as the pension goal's stream: its share of every
    expense line of each month. Each item keeps its own indexation and dates, so a month's
    line records a rate only when all of that month's items share one."""
    by_month: dict[int, list[LedgerLine]] = {}
    for line in expenses:
        if line.line_kind != "expense":
            continue
        n = month_index(t0, line.month)
        if n >= retirement_index:
            by_month.setdefault(n, []).append(line)
    lines: list[LedgerLine] = []
    for n in sorted(by_month):
        items = by_month[n]
        rates = {line.resolved_rate for line in items}
        lines.append(
            LedgerLine(
                month=month_key(t0, n),
                line_kind="goal_outflow",
                label=goal.label,
                amount=goal.amount_pv * sum(line.amount for line in items),
                resolved_rate=rates.pop() if len(rates) == 1 else None,
                goal_id=goal.goal_id,
            )
        )
    return lines


def _retirement_income_lines(
    goal: GoalIn,
    t0: str,
    months: int,
    retirement_index: int,
    rate: float,
    expenses: Sequence[LedgerLine] | None,
) -> list[LedgerLine]:
    """A pension's stream, its own sum or a share of the family expenses it replaces."""
    if goal.amount_basis != "expense_share":
        return _retirement_stream(goal, t0, months, retirement_index, rate)
    if expenses is None:
        raise ValueError(
            f"{goal.label}: a pension sized as a share of the family expenses needs the "
            "expenses it replaces, and the pension-expenses rule is off in this plan"
        )
    return _expense_share_stream(goal, t0, expenses, retirement_index)


def is_savings_goal(goal: GoalIn, inputs: PlanInputs) -> bool:
    """Is this goal saved for (deposit, bonds) rather than invested for?

    Only a dated ``lump`` goal. Under the retirement rule — any purchase before the year of
    retirement: after it there is no salary to save from. Without the retirement rule — a purchase fewer than
    ``savings_horizon_years`` from t0, strictly fewer; ``None`` switches that rule off.
    ``reserve_topup`` already is a savings vehicle and ``retirement_income`` is the portfolio's job.
    """
    if goal.kind != "lump" or goal.target_year is None:
        return False
    if inputs.reserves_until_retirement:
        # By month, as the buffer closes: a goal dated in the retirement year but before
        # t0's month of it still falls before retirement. Without target_month this is the year
        # comparison it always was.
        return goal_month_index(goal, inputs.t0) < year_index(inputs.t0, inputs.retirement_year)
    if inputs.savings_horizon_years is None:
        return False
    return goal_month_index(goal, inputs.t0) < 12 * inputs.savings_horizon_years


def goal_month_index(goal: GoalIn, t0: str) -> int:
    """The month a dated goal falls on, counted from t0: its target_month of target_year,
    or t0's own month of that year when no month is given."""
    n = year_index(t0, goal.target_year)
    if goal.target_month is None:
        return n
    return n + goal.target_month - parse_month(t0)[1]


def _target_index(goal: GoalIn, t0: str) -> int:
    """The month a dated goal falls on, counted from t0; loud when undated or before the start."""
    if goal.target_year is None:
        raise ValueError(f"{goal.label}: a {goal.kind} goal needs a target_year")
    n = goal_month_index(goal, t0)
    if n < 0:
        if goal.target_month is None:
            base_year = calendar_year(t0, 0)
            raise ValueError(
                f"{goal.label}: target_year {goal.target_year} precedes the plan start ({base_year})"
            )
        raise ValueError(
            f"{goal.label}: {goal.target_year}-{goal.target_month:02d} precedes the plan start {t0}"
        )
    return n


def expand_goals(
    goals: Sequence[GoalIn],
    t0: str,
    months: int,
    retirement_index: int,
    rates: Rates,
    expenses: Sequence[LedgerLine] | None = None,
) -> GoalExpansion:
    """Turn every goal into its ledger shape, dropping anything past the horizon.

    ``expenses`` are the budget's lines when the pension replaces the family expenses: a
    pension sized as their share is built from them. None — the rule is off in this plan.
    """
    lines: list[LedgerLine] = []
    acquired: list[AcquiredAsset] = []
    reserve_targets: list[tuple[int, float]] = []
    sold: list[AssetSale] = []

    for goal in goals:
        rate = resolve_rate(RateSubject.GOAL, goal.indexation_rate, rates)
        if goal.replaces_asset is not None and goal.kind != "lump":
            raise ValueError(
                f"{goal.label}: replaces_asset is only meaningful on a lump goal — a "
                f"{goal.kind} goal has no purchase month to sell the asset in"
            )

        if goal.kind == "retirement_income":
            lines.extend(_retirement_income_lines(goal, t0, months, retirement_index, rate, expenses))
            continue

        n = _target_index(goal, t0)
        if n >= months:
            continue
        amount = value_in_year(goal.amount_pv, rate, goal.pv_year, goal.target_year)

        if goal.kind == "reserve_topup":
            # Not an outflow: the money moves from free cash flow into the reserve fund.
            reserve_targets.append((n, amount, goal.goal_id))
            continue

        if goal.kind != "lump":
            raise ValueError(f"{goal.label}: unknown goal kind {goal.kind!r}")

        lines.append(
            LedgerLine(
                month=month_key(t0, n),
                line_kind="goal_outflow",
                label=goal.label,
                amount=-amount,
                resolved_rate=rate,
                goal_id=goal.goal_id,
            )
        )
        if goal.becomes_asset:
            acquired.append(AcquiredAsset(month_index=n, label=goal.label, value=amount, growth_rate=rate))
        if goal.replaces_asset is not None:
            sold.append(AssetSale(month_index=n, asset_label=goal.replaces_asset, goal_label=goal.label))

    return GoalExpansion(tuple(lines), tuple(acquired), tuple(reserve_targets), tuple(sold))
