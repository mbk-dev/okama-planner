"""Independent purchase accounts, funded by available household income, never by each other."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from okama_planner.inputs import PlanInputs
from okama_planner.ledger.buffer import BufferResult, run_buffer
from okama_planner.ledger.calendar import month_key
from okama_planner.ledger.types import LedgerLine, ReservePurpose


@dataclass(slots=True)
class _Account:
    label: str
    goal_id: int | None
    due: int
    amount: float
    rate: float
    balance: float
    contribution: float

    @property
    def factor(self) -> float:
        return (1.0 + self.rate) ** (1.0 / 12.0)


def _accounts(
    inputs: PlanInputs,
    purchases: Sequence[tuple[str, int, float]],
    opening: float,
) -> tuple[list[_Account], float]:
    goals = {goal.label: goal for goal in inputs.goals}
    specs = []
    for label, due, amount in purchases:
        rate = inputs.goal_savings_rates.get(label, inputs.rates.buffer_rate)
        if not math.isfinite(rate) or rate <= -1.0:
            raise ValueError(f"{label}: savings rate must be finite and greater than -1")
        factor = (1.0 + rate) ** (1.0 / 12.0)
        present = amount / factor**due
        specs.append((label, due, amount, rate, factor, present))
    total_present = sum(spec[5] for spec in specs)
    assigned = min(opening, total_present)
    accounts = []
    for label, due, amount, rate, factor, present in specs:
        initial = assigned * present / total_present
        # End-of-month deposits from month 0 to due-1; all earn at least one month's income.
        future = max(0.0, amount - initial * factor**due)
        annuity = sum(factor**k for k in range(1, due + 1))
        accounts.append(
            _Account(
                label,
                goals[label].goal_id,
                due,
                amount,
                rate,
                initial,
                future / annuity if due else 0.0,
            )
        )
    return accounts, opening - assigned


def run_goal_savings(
    inputs: PlanInputs,
    free_flow: Sequence[float],
    purchases: Sequence[tuple[str, int, float]],
    opening_balance: float,
    retirement_month: int,
) -> tuple[BufferResult, tuple[ReservePurpose, ...], dict[str, float]]:
    """Keep goals separate and pass unfunded purchase amounts to the portfolio on their due date.

    Short income funds the planned deposits pro rata. No goal account pays a household deficit;
    the ordinary expense buffer gets only unassigned opening savings and residual income.
    """
    accounts, excess = _accounts(inputs, purchases, opening_balance)
    targets = [0.0] * len(free_flow)
    for _, due, amount in purchases:
        targets[due] += amount
    expense_flow = [free + target for free, target in zip(free_flow, targets, strict=True)]
    paid = [0.0] * len(free_flow)
    balances: dict[str, list[float]] = {account.label: [] for account in accounts}
    lines: list[LedgerLine] = []
    shortfalls: dict[str, float] = {}
    for month, free in enumerate(expense_flow):
        active = [account for account in accounts if month < account.due]
        desired = sum(account.contribution for account in active)
        fraction = min(1.0, max(0.0, free) / desired) if desired else 0.0
        key = month_key(inputs.t0, month)
        for account in accounts:
            if month > 0 and month <= account.due:
                account.balance *= account.factor
            if month < account.due:
                deposit = account.contribution * fraction
                account.balance += deposit
                expense_flow[month] -= deposit
                if deposit:
                    lines.append(
                        LedgerLine(
                            key,
                            "buffer_in",
                            account.label,
                            deposit,
                            account.rate,
                            account.goal_id,
                        )
                    )
            elif month == account.due:
                # A tenth of a kopeck covers accumulated float error without hiding money debt.
                if math.isclose(account.balance, account.amount, rel_tol=0.0, abs_tol=0.001):
                    account.balance = account.amount
                shortfalls[account.label] = max(0.0, account.amount - account.balance)
                paid[month] += account.balance
                if account.balance:
                    lines.append(
                        LedgerLine(
                            key,
                            "buffer_out",
                            account.label,
                            -account.balance,
                            account.rate,
                            account.goal_id,
                        )
                    )
                account.balance = 0.0
            balances[account.label].append(account.balance)

    expenses = run_buffer(
        expense_flow,
        inputs.t0,
        inputs.buffer_lookahead_months,
        inputs.rates.buffer_rate,
        opening_balance=excess,
        retirement_month=retirement_month,
    )
    lines.extend(replace(line, label="Резерв на расходы") for line in expenses.lines)
    parts = (
        *(ReservePurpose(account.label, tuple(balances[account.label])) for account in accounts),
        ReservePurpose(None, expenses.balance),
    )
    result = BufferResult(
        lines=tuple(lines),
        balance=tuple(sum(part.balance[n] for part in parts) for n in range(len(free_flow))),
        portfolio_flow=tuple(
            flow - target + payment
            for flow, target, payment in zip(expenses.portfolio_flow, targets, paid, strict=True)
        ),
    )
    return result, parts, _portfolio_shares(accounts, shortfalls, result.portfolio_flow)


def _portfolio_shares(
    accounts: Sequence[_Account],
    shortfalls: dict[str, float],
    flows: Sequence[float],
) -> dict[str, float]:
    """Attribute purchase-month withdrawals to unfunded goals after the month's available cash.

    Several simultaneous shortfalls share the needed portfolio payment pro rata. Household bills
    never turn a fully funded goal into a withdrawal, even if the portfolio pays those bills.
    """
    totals: dict[int, float] = {}
    for account in accounts:
        totals[account.due] = totals.get(account.due, 0.0) + shortfalls[account.label]
    return {
        account.label: (
            shortfalls[account.label]
            / totals[account.due]
            * min(totals[account.due], max(0.0, -flows[account.due]))
            if totals[account.due]
            else 0.0
        )
        for account in accounts
    }
