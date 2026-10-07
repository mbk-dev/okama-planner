"""Amortisation of a fixed-payment loan.

The payment is fixed in nominal terms and is never indexed — that mix of an indexed household
budget and a flat mortgage payment is why the ledger, not okama, does the indexing.
"""

from __future__ import annotations

from dataclasses import dataclass

from okama_planner.inputs import LiabilityIn
from okama_planner.ledger.calendar import month_index, month_key
from okama_planner.ledger.types import LedgerLine


class PaymentTooSmallError(ValueError):
    """The monthly payment does not even cover the interest, so the loan never closes."""


@dataclass(frozen=True, slots=True)
class Instalment:
    """One month of a loan: the payment, how it splits, and the debt left after it."""

    payment: float
    interest: float
    principal: float
    balance: float


def amortisation_table(
    principal: float, annual_rate: float, monthly_payment: float, *, max_months: int | None = None
) -> tuple[Instalment, ...]:
    """Every instalment from the first month to payoff, the last one partial.

    Runs until the debt is actually cleared. The contractual term is deliberately not an input:
    cutting the schedule at ``term_months`` would drop whatever balance the payment had not covered
    by then. The loop terminates because
    the payment exceeds the interest, so the balance strictly falls every month.
    """
    monthly_rate = annual_rate / 12.0
    if monthly_payment <= principal * monthly_rate:
        raise PaymentTooSmallError(
            f"payment {monthly_payment} never covers interest {principal * monthly_rate} on {principal}"
        )

    table: list[Instalment] = []
    balance = principal
    while balance > 0.0 and (max_months is None or len(table) < max_months):
        interest = balance * monthly_rate
        owed = balance + interest
        if owed <= monthly_payment:
            table.append(Instalment(payment=owed, interest=interest, principal=balance, balance=0.0))
            break
        if owed - monthly_payment >= balance:
            raise PaymentTooSmallError("payment does not reduce the balance at float precision")
        table.append(
            Instalment(
                payment=monthly_payment,
                interest=interest,
                principal=monthly_payment - interest,
                balance=owed - monthly_payment,
            )
        )
        balance = owed - monthly_payment
    return tuple(table)


def amortisation_schedule(principal: float, annual_rate: float, monthly_payment: float) -> tuple[float, ...]:
    """Payments from the first month to payoff, the last one partial (see ``amortisation_table``)."""
    return tuple(
        instalment.payment for instalment in amortisation_table(principal, annual_rate, monthly_payment)
    )


def liability_track(
    liability: LiabilityIn, t0: str, months: int
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The debt at the end of every month of the horizon, and the principal repaid in it.

    Both zero before ``start_month`` (the loan is not taken yet) and after payoff. A loan that
    started before ``t0`` enters mid-schedule: its earlier instalments are simply not in the plan.
    """
    offset = month_index(t0, liability.start_month)
    table = amortisation_table(
        liability.principal,
        liability.annual_rate,
        liability.monthly_payment,
        max_months=max(0, months - offset),
    )
    balance = [0.0] * months
    repaid = [0.0] * months
    for step, instalment in enumerate(table):
        n = offset + step
        if 0 <= n < months:
            balance[n] = instalment.balance
            repaid[n] = instalment.principal
    return tuple(balance), tuple(repaid)


def mortgage_lines(liability: LiabilityIn, t0: str, months: int) -> tuple[LedgerLine, ...]:
    """The loan's payment stream as ledger lines, clipped to the horizon."""
    offset = month_index(t0, liability.start_month)
    schedule = (
        row.payment
        for row in amortisation_table(
            liability.principal,
            liability.annual_rate,
            liability.monthly_payment,
            max_months=max(0, months - offset),
        )
    )
    lines: list[LedgerLine] = []
    for step, payment in enumerate(schedule):
        n = offset + step
        if n < 0 or n >= months:
            continue
        lines.append(
            LedgerLine(
                month=month_key(t0, n),
                line_kind="mortgage_payment",
                label=liability.label,
                amount=-payment,
                resolved_rate=None,
            )
        )
    return tuple(lines)
