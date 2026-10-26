"""Advisor planning history, retained losslessly in the canonical Planner database.

These typed records let existing advisory calculations use the same client registry.
New public request snapshots live in planner_* tables, not a second database.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


def _enum(enum_cls: type[StrEnum]) -> sa.Enum:
    """Store an enum by its value.

    SQLAlchemy persists enum *names* by default; the values are what the rest of the
    application, the YAML input files and the snapshot JSON all speak.
    """
    return sa.Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


def _now() -> datetime:
    return datetime.now(UTC)


class Sex(StrEnum):
    """Kept because client documents are written in Russian, where wording agrees with it."""

    FEMALE = "female"
    MALE = "male"


class ContactChannel(StrEnum):
    """A way to reach a client, and the answer to «где основная переписка»."""

    EMAIL = "email"
    PHONE = "phone"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    MAX = "max"


class PersonRole(StrEnum):
    CLIENT = "client"
    SPOUSE = "spouse"
    CHILD = "child"


class AssetClass(StrEnum):
    """What an asset does in the forecast — the field that moves the result most."""

    PORTFOLIO = "portfolio"
    RESERVE = "reserve"
    NON_WORKING = "non_working"
    THIRD_PARTY = "third_party"
    #: Money already set aside for purchases: it opens the purchase reserve and grows at
    #: ``buffer_rate``, outside the portfolio (#75).
    SAVINGS = "savings"


class BudgetKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class EndRule(StrEnum):
    NONE = "none"
    UNTIL_RETIREMENT = "until_retirement"
    UNTIL_MONTH = "until_month"


class GoalKind(StrEnum):
    LUMP = "lump"
    RETIREMENT_INCOME = "retirement_income"
    RESERVE_TOPUP = "reserve_topup"


class AmountBasis(StrEnum):
    """What a goal's ``amount_pv`` is measured in (#67): money, or a share of the family expenses."""

    AMOUNT = "amount"
    EXPENSE_SHARE = "expense_share"


class PortfolioRole(StrEnum):
    ACCUMULATION = "accumulation"
    WITHDRAWAL = "withdrawal"


class Client(Base):
    """One version of a client's input data. The human behind it is ``ClientRegistry``."""

    __tablename__ = "client"
    __table_args__ = (sa.UniqueConstraint("registry_id", "version", name="uq_client_registry_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int] = mapped_column(sa.ForeignKey("client_registry.id"))
    version: Mapped[int]
    #: SHA-256 of the client part of the file this version was imported from.
    source_digest: Mapped[str]
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class MeetingFormat(StrEnum):
    """How the advisor and client meet."""

    IN_PERSON = "in_person"
    ONLINE = "online"
    PHONE = "phone"


class ClientMeeting(Base):
    """A dated meeting belongs to the identity, independent of plan versions."""

    __tablename__ = "client_meeting"
    __table_args__ = (
        sa.CheckConstraint("length(trim(goal)) > 0", name="ck_meeting_goal"),
        sa.CheckConstraint("format IN ('in_person', 'online', 'phone')", name="ck_meeting_format"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int] = mapped_column(sa.ForeignKey("client_registry.id"), index=True)
    goal: Mapped[str]
    date: Mapped[date]
    time: Mapped[time | None] = mapped_column(default=None)
    format: Mapped[MeetingFormat] = mapped_column(_enum(MeetingFormat))
    notes: Mapped[str] = mapped_column(sa.Text, default="", server_default=sa.text("''"))


class Person(Base):
    """A family member. Drives the age rows in the workbook and the wording about deadlines."""

    __tablename__ = "person"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    name: Mapped[str]
    birth_year: Mapped[int]
    role: Mapped[PersonRole] = mapped_column(_enum(PersonRole))


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    label: Mapped[str]
    amount: Mapped[float]
    currency: Mapped[str] = mapped_column(default="RUB")
    asset_class: Mapped[AssetClass] = mapped_column(_enum(AssetClass))
    growth_rate: Mapped[float | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)


class Liability(Base):
    __tablename__ = "liability"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    label: Mapped[str]
    principal: Mapped[float]
    annual_rate: Mapped[float]
    monthly_payment: Mapped[float]
    term_months: Mapped[int]
    start_month: Mapped[str]
    note: Mapped[str | None] = mapped_column(default=None)


class BudgetItem(Base):
    __tablename__ = "budget_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    kind: Mapped[BudgetKind] = mapped_column(_enum(BudgetKind))
    label: Mapped[str]
    monthly_amount: Mapped[float]
    indexation_rate: Mapped[float | None] = mapped_column(default=None)
    start_month: Mapped[str | None] = mapped_column(default=None)
    end_rule: Mapped[EndRule] = mapped_column(_enum(EndRule), default=EndRule.NONE)
    end_month: Mapped[str | None] = mapped_column(default=None)


class Goal(Base):
    __tablename__ = "goal"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    label: Mapped[str]
    kind: Mapped[GoalKind] = mapped_column(_enum(GoalKind))
    amount_pv: Mapped[float]
    #: What ``amount_pv`` is measured in. A pension may be a share of the family expenses (1.0 is
    #: all of them) instead of a sum; every goal stored before #67 is a sum.
    amount_basis: Mapped[AmountBasis] = mapped_column(
        _enum(AmountBasis), default=AmountBasis.AMOUNT, server_default=AmountBasis.AMOUNT.value
    )
    pv_year: Mapped[int]
    target_year: Mapped[int | None] = mapped_column(default=None)
    #: Month of ``target_year`` the goal falls on (#76); None — t0's month, as before.
    target_month: Mapped[int | None] = mapped_column(default=None)
    priority: Mapped[int] = mapped_column(default=1)
    becomes_asset: Mapped[bool] = mapped_column(default=False)
    can_defer: Mapped[bool] = mapped_column(default=False)
    can_resize: Mapped[bool] = mapped_column(default=False)
    indexation_rate: Mapped[float | None] = mapped_column(default=None)
    #: Label of a non_working asset of the same client, sold the month the goal is bought.
    replaces_asset: Mapped[str | None] = mapped_column(default=None)
    #: The caption of this purchase's reserve row in the workbook (#74), e.g. «Резерв на покупку
    #: дома (облигации на ИИС)». None prints «Резерв на покупку: <label>».
    reserve_label: Mapped[str | None] = mapped_column(default=None)
    note: Mapped[str | None] = mapped_column(default=None)


DEFAULT_REBALANCING_PERIOD = "month"


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    label: Mapped[str]
    role: Mapped[PortfolioRole] = mapped_column(_enum(PortfolioRole))
    currency: Mapped[str] = mapped_column(default="RUB")
    last_date_pin: Mapped[str]
    #: The rebalancing strategy, a property of the investment decision — not of the run.
    # The server default is what the migration gave the portfolios that already existed;
    # declaring it here too keeps a created-from-models schema identical to a migrated one.
    rebalancing_period: Mapped[str] = mapped_column(
        default=DEFAULT_REBALANCING_PERIOD, server_default=DEFAULT_REBALANCING_PERIOD
    )
    abs_deviation: Mapped[float | None] = mapped_column(default=None)
    rel_deviation: Mapped[float | None] = mapped_column(default=None)


class PortfolioHolding(Base):
    __tablename__ = "portfolio_holding"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(sa.ForeignKey("portfolio.id"))
    symbol: Mapped[str]
    weight: Mapped[float]


class AdjustmentAction(StrEnum):
    """The three levers that bring a plan to feasibility."""

    DEFER = "defer"
    RESIZE = "resize"
    DROP = "drop"


class RunStatus(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


class Distribution(StrEnum):
    NORM = "norm"
    LOGNORM = "lognorm"
    T = "t"


class Scenario(Base):
    __tablename__ = "scenario"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(sa.ForeignKey("client.id"))
    label: Mapped[str]
    is_base: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_now)


class GoalAdjustment(Base):
    """A scenario is the base goals plus this delta — never a copy of the goal set."""

    __tablename__ = "goal_adjustment"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(sa.ForeignKey("scenario.id"))
    goal_id: Mapped[int] = mapped_column(sa.ForeignKey("goal.id"))
    action: Mapped[AdjustmentAction] = mapped_column(_enum(AdjustmentAction))
    new_target_year: Mapped[int | None] = mapped_column(default=None)
    new_amount_pv: Mapped[float | None] = mapped_column(default=None)


class PlanRun(Base):
    """One Monte Carlo run. ``inputs_snapshot`` makes it reproducible a year later."""

    __tablename__ = "plan_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(sa.ForeignKey("scenario.id"))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    status: Mapped[RunStatus] = mapped_column(_enum(RunStatus), default=RunStatus.PENDING)

    t0: Mapped[str]
    horizon_years: Mapped[int]
    withdrawal_years: Mapped[int | None] = mapped_column(default=None)
    retirement_year: Mapped[int]
    seed: Mapped[int]
    mc_number: Mapped[int]
    distribution: Mapped[Distribution] = mapped_column(_enum(Distribution), default=Distribution.NORM)
    #: Whether the tail fit kept the sample's own centre and spread. It qualifies ``distribution``
    #: rather than standing beside it: under ``norm`` it changes nothing, and under ``t`` it is
    #: worth twenty points of the plan's probability (#59), so a replay must not guess it.
    match_moments: Mapped[bool] = mapped_column(default=True, server_default=sa.text("1"))
    buffer_lookahead_months: Mapped[int] = mapped_column(default=12)
    #: Goals fewer than this many years from t0 are saved for, not invested for; NULL = rule off.
    savings_horizon_years: Mapped[int | None] = mapped_column(default=None)

    inflation_rate: Mapped[float]
    expense_indexation_rate: Mapped[float]
    income_indexation_rate: Mapped[float]
    goal_indexation_rate: Mapped[float]
    discount_rate: Mapped[float]
    buffer_rate: Mapped[float]

    accumulation_portfolio_id: Mapped[int | None] = mapped_column(sa.ForeignKey("portfolio.id"), default=None)
    withdrawal_portfolio_id: Mapped[int | None] = mapped_column(sa.ForeignKey("portfolio.id"), default=None)

    okama_version: Mapped[str | None] = mapped_column(default=None)
    inputs_snapshot: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    #: A complete stored forecast of the earliest retirement year found by this run's sweep.
    #: Excel reads its chart series; the source run remains the source of every printed table.
    retirement_projection_run_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("plan_run.id"), default=None, index=True
    )


class LineKind(StrEnum):
    """Every line of the monthly ledger. ``PORTFOLIO_FLOW`` is the series handed to okama."""

    INCOME = "income"
    EXPENSE = "expense"
    MORTGAGE_PAYMENT = "mortgage_payment"
    GOAL_OUTFLOW = "goal_outflow"
    RESERVE_TOPUP = "reserve_topup"
    ASSET_SALE = "asset_sale"
    BUFFER_IN = "buffer_in"
    BUFFER_OUT = "buffer_out"
    PORTFOLIO_FLOW = "portfolio_flow"


class SweepKind(StrEnum):
    EARLIEST_YEAR = "earliest_year"
    """The earliest year the portfolio pays the goal — years at or past the savings horizon."""
    EARLIEST_SAVINGS_YEAR = "earliest_savings_year"
    """The earliest year the goal is saved for on deposit — years under the savings horizon (#46)."""
    MAX_AMOUNT = "max_amount"
    RETIREMENT_YEAR = "retirement_year"
    PLAN_AFTER_SAVINGS = "plan_after_savings"
    """The whole plan's probability with the goal placed in its savings year (spec §6, #50).

    A probability, not a year or an amount: saving for the goal keeps the money out of the
    portfolio, and this is what that costs the rest of the plan.
    """


class LedgerRow(Base):
    """The cash flows, in the database. Amounts are nominal, but ``line_kind`` splits into three
    things that must not be summed together (see ``lfp.ledger.types.LedgerLine`` for the full
    breakdown): household flows (``income``, ``expense``, ``mortgage_payment``, ``goal_outflow``,
    ``reserve_topup``, ``asset_sale``); the BUFFER's own bookkeeping (``buffer_in``/``buffer_out``,
    signed from the buffer's point of view, not the household's); and ``portfolio_flow``, which
    RESTATES the household flows rather than adding another one. Summing every kind in a month
    double-counts.
    """

    __tablename__ = "ledger_row"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_run_id: Mapped[int] = mapped_column(sa.ForeignKey("plan_run.id"), index=True)
    month: Mapped[str] = mapped_column(index=True)
    line_kind: Mapped[LineKind] = mapped_column(_enum(LineKind))
    label: Mapped[str]
    amount: Mapped[float]
    resolved_rate: Mapped[float | None] = mapped_column(default=None)
    goal_id: Mapped[int | None] = mapped_column(sa.ForeignKey("goal.id"), default=None)


class RunMetric(Base):
    __tablename__ = "run_metric"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_run_id: Mapped[int] = mapped_column(sa.ForeignKey("plan_run.id"), index=True)
    key: Mapped[str]
    value: Mapped[float]


class RunBalancePercentile(Base):
    __tablename__ = "run_balance_percentile"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_run_id: Mapped[int] = mapped_column(sa.ForeignKey("plan_run.id"), index=True)
    month: Mapped[str] = mapped_column(index=True)
    percentile: Mapped[int]
    value: Mapped[float]


class RunGoalResult(Base):
    """``p_affordable`` goes to the client; ``p_alive`` explains why late goals sag."""

    __tablename__ = "run_goal_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_run_id: Mapped[int] = mapped_column(sa.ForeignKey("plan_run.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(sa.ForeignKey("goal.id"), default=None)
    month: Mapped[str] = mapped_column(default="")
    amount_nominal: Mapped[float] = mapped_column(default=0.0)
    p_affordable: Mapped[float] = mapped_column(default=0.0)
    p_alive: Mapped[float] = mapped_column(default=0.0)


class SweepResult(Base):
    __tablename__ = "sweep_result"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_run_id: Mapped[int] = mapped_column(sa.ForeignKey("plan_run.id"), index=True)
    goal_id: Mapped[int | None] = mapped_column(sa.ForeignKey("goal.id"), default=None)
    kind: Mapped[SweepKind] = mapped_column(_enum(SweepKind))
    threshold: Mapped[float] = mapped_column(default=0.0)
    value: Mapped[float] = mapped_column(default=0.0)
    note: Mapped[str | None] = mapped_column(default=None)


class RunLedgerState(Base):
    """Stored deterministic balances and reserve tasks; never reconstructed for new policies."""

    __tablename__ = "run_ledger_state"

    plan_run_id: Mapped[int] = mapped_column(sa.ForeignKey("plan_run.id"), primary_key=True)
    payload: Mapped[dict] = mapped_column(sa.JSON)


class ClientIntakeNote(Base):
    __tablename__ = "client_intake_note"
    __table_args__ = (sa.UniqueConstraint("source_key", "content_digest", name="uq_intake_source_content"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int | None]
    source_key: Mapped[str]
    content_digest: Mapped[str]
    content: Mapped[str] = mapped_column(sa.Text)
    imported_at: Mapped[datetime] = mapped_column(sa.DateTime)
