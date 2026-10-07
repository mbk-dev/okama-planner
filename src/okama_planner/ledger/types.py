"""The ledger's own data types. Frozen: the ledger is a value, not a mutable accumulator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LedgerLine:
    """One row of the monthly ledger. Amounts are nominal; three different things share this
    shape, and summing every ``line_kind`` in a month double-counts:

    - ``income``, ``expense``, ``mortgage_payment``, ``goal_outflow``, ``reserve_topup`` and
      ``asset_sale`` are household cash flows — positive is money the household receives
      (a salary, the proceeds of a sold car), negative is money it pays.
    - ``buffer_in``/``buffer_out`` are the BUFFER's own bookkeeping, not a household flow: money
      moving into or out of that side account (positive in, negative out), signed from the
      buffer's point of view.
    - ``portfolio_flow`` is not a further flow to add — it RESTATES the household lines, net of
      the buffer, as what actually reaches the portfolio that month. A prior ``monthly_totals()``
      helper that summed every ``line_kind`` per month was deleted for exactly this reason: there
      is no sign convention under which that sum means anything.
    """

    month: str
    line_kind: str
    label: str
    amount: float
    resolved_rate: float | None = None
    #: The goal a ``goal_outflow``/``reserve_topup`` line belongs to; None on other kinds
    #: and on ledgers replayed from runs stored before the column existed.
    goal_id: int | None = None


@dataclass(frozen=True, slots=True)
class ReservePurpose:
    """The part of the buffer's month-end balance set aside for one purchase.

    ``goal_label`` None is what is left over: the budget deficits the buffer's window covers.
    A display split in pooled mode; actual independent account balances in separate mode.
    The forecast reads the net portfolio flow, not these balances.
    """

    goal_label: str | None
    balance: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class ReserveTask:
    """A funded coverage obligation, including late or impossible completion."""

    start_month: str
    deadline_month: str | None
    completed_month: str | None
    expected_completion_month: str | None
    remaining: float
    deadline_violated: bool
    required: float


@dataclass(frozen=True, slots=True)
class Ledger:
    """The whole cash-flow register of one run, plus the balances it tracks outside the portfolio."""

    t0: str
    months: tuple[str, ...]
    lines: tuple[LedgerLine, ...] = ()
    portfolio_flow: dict[str, float] = field(default_factory=dict)
    buffer_balance: tuple[float, ...] = ()
    reserve_balance: tuple[float, ...] = ()
    non_working_balance: tuple[float, ...] = ()
    #: The debt outstanding at the end of each month and the principal repaid in it. Not
    #: lines: the full payment is already a ``mortgage_payment`` line, and a second line for its
    #: principal part would double-count the household's outflow.
    liability_balance: tuple[float, ...] = ()
    principal_repaid: tuple[float, ...] = ()
    #: The buffer's balance by purpose, purchases in order of their months and the rest last.
    #: Empty for a snapshot written before the retirement rule: its window also saves for
    #: investment goals, and the rest would print them as budget deficits.
    buffer_by_goal: tuple[ReservePurpose, ...] = ()
    #: Separate accounts attribute only their own purchase shortfall, excluding household bills.
    #: Empty keeps the historic pooled affordability rule.
    goal_portfolio_shares: dict[str, float] = field(default_factory=dict)

    reserve_coverage: tuple[float, ...] = ()
    reserve_required: tuple[float, ...] = ()
    reserve_income_funding: tuple[float, ...] = ()
    reserve_portfolio_funding: tuple[float, ...] = ()
    reserve_tasks: tuple[ReserveTask, ...] = ()

    def lines_of(self, line_kind: str) -> tuple[LedgerLine, ...]:
        return tuple(line for line in self.lines if line.line_kind == line_kind)
