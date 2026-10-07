"""The buffer — the mechanic okama has no analogue for.

A deficit month is funded from cash set aside in earlier surplus months, not by selling the
portfolio. Monte Carlo punishes selling into a drawdown, so the difference in the probability of
success is material. The schedule is computed from the input alone and never from portfolio
returns, which is what makes the whole ledger identical across scenarios.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from okama_planner.ledger.calendar import month_key
from okama_planner.ledger.types import LedgerLine, ReservePurpose


@dataclass(frozen=True, slots=True)
class BufferResult:
    lines: tuple[LedgerLine, ...]
    balance: tuple[float, ...]
    portfolio_flow: tuple[float, ...]


def _target(
    other_flow: Sequence[float],
    savings: Sequence[float],
    month: int,
    lookahead_months: int,
    stop: int,
) -> float:
    """How much has to be on hand: the deficits of the coming window plus every savings outflow
    still ahead, however far — a savings goal is saved for from the first month of the plan. The
    window ends at ``stop``: from retirement on the buffer saves for nothing."""
    window = other_flow[month + 1 : min(month + 1 + lookahead_months, stop)]
    return -sum(value for value in window if value < 0.0) + sum(savings[month + 1 :])


def _cover_deficit(
    balance: float, deficit: float, target: float, release_excess: bool, key: str, lines: list[LedgerLine]
) -> tuple[float, float]:
    """Pay a deficit month from the buffer; return the new balance and what reaches the portfolio.

    Savings set aside before t0 (``release_excess``) may exceed what the buffer needs: the
    excess leaves in a deficit month too. Without them the rule stays as it was, so the runs
    stored before savings existed replay to the kopeck.
    """
    from_buffer = min(balance, deficit)
    balance -= from_buffer
    to_portfolio = -(deficit - from_buffer)
    if from_buffer:
        lines.append(LedgerLine(key, "buffer_out", "Резерв на покупку", -from_buffer))
    if release_excess and balance > target:
        released = balance - target
        balance = target
        to_portfolio += released
        lines.append(LedgerLine(key, "buffer_out", "Резерв на покупку", -released))
    return balance, to_portfolio


def run_buffer(
    free_flow: Sequence[float],
    t0: str,
    lookahead_months: int,
    buffer_rate: float,
    opening_balance: float = 0.0,
    savings_outflows: Sequence[float] | None = None,
    retirement_month: int | None = None,
) -> BufferResult:
    """Run the buffer over the free cash flow and return what reaches the portfolio.

    ``savings_outflows`` (positive, per month, already inside ``free_flow`` as outflows) are the
    purchases funded from savings rather than from the portfolio. They are taken out of the netted
    series before the window's deficits are summed and added back in full, so a savings goal
    counts the same whether it is 40 months or 4 months away, and a month's salary surplus still
    invests as usual.

    ``retirement_month`` closes the buffer: the window never looks at a deficit from that
    month on, and in that month whatever is left goes to the portfolio. From then on the free
    flow reaches the portfolio as it is — the pension is FinPlan's withdrawal stage, not a
    purchase. None keeps the rule of the snapshots written before it.
    """
    monthly_factor = (1.0 + buffer_rate) ** (1.0 / 12.0)
    savings = list(savings_outflows) if savings_outflows is not None else [0.0] * len(free_flow)
    if len(savings) != len(free_flow):
        raise ValueError(f"savings_outflows has {len(savings)} months, free_flow has {len(free_flow)}")
    other_flow = [free + saved for free, saved in zip(free_flow, savings, strict=True)]
    stop = len(free_flow) if retirement_month is None else retirement_month
    lines: list[LedgerLine] = []
    balances: list[float] = []
    flows: list[float] = []
    balance = opening_balance

    for month, free in enumerate(free_flow):
        if month > 0:
            balance *= monthly_factor
        key = month_key(t0, month)

        if retirement_month is not None and month >= retirement_month:
            if balance:
                lines.append(LedgerLine(key, "buffer_out", "Резерв на покупку", -balance))
            flows.append(free + balance)
            balance = 0.0
            balances.append(balance)
            continue

        target = _target(other_flow, savings, month, lookahead_months, stop)

        if free >= 0.0:
            needed = max(0.0, target - balance)
            into_buffer = min(free, needed)
            balance += into_buffer
            released = max(0.0, balance - target)
            balance -= released
            to_portfolio = free - into_buffer + released
            if into_buffer:
                lines.append(LedgerLine(key, "buffer_in", "Резерв на покупку", into_buffer))
            if released:
                lines.append(LedgerLine(key, "buffer_out", "Резерв на покупку", -released))
        else:
            balance, to_portfolio = _cover_deficit(balance, -free, target, bool(opening_balance), key, lines)

        balances.append(balance)
        flows.append(to_portfolio)

    return BufferResult(tuple(lines), tuple(balances), tuple(flows))


def split_buffer(
    balance: Sequence[float], purchases: Sequence[tuple[str, int, float]]
) -> tuple[ReservePurpose, ...]:
    """Split the pooled balance by purpose for the workbook.

    ``purchases`` are ``(goal label, month of the purchase, amount saved for it)``. At the end of
    each month the balance goes to the purchases still ahead, the earliest first (input order
    breaks a tie), each up to its amount; what is left is the rest. The parts add up to the
    balance by construction.
    """
    order = sorted(range(len(purchases)), key=lambda index: (purchases[index][1], index))
    parts: dict[int, list[float]] = {index: [] for index in order}
    rest: list[float] = []
    for month, total in enumerate(balance):
        left = total
        for index in order:
            _, due, amount = purchases[index]
            share = min(left, amount) if due > month else 0.0
            parts[index].append(share)
            left -= share
        rest.append(left)
    return (
        *(ReservePurpose(purchases[index][0], tuple(parts[index])) for index in order),
        ReservePurpose(None, tuple(rest)),
    )
