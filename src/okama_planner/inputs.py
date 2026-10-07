"""Frozen input models for a standalone financial plan.

A plan replays from JSON alone; no model holds a database session.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


_FROZEN = ConfigDict(frozen=True, extra="forbid")


class Rates(BaseModel):
    """The six run-level rates. None is derived from another; all are required."""

    model_config = _FROZEN

    inflation_rate: float
    expense_indexation_rate: float
    income_indexation_rate: float
    goal_indexation_rate: float
    discount_rate: float
    buffer_rate: float


class PersonIn(BaseModel):
    model_config = _FROZEN

    name: str
    birth_year: int
    role: str


class AssetIn(BaseModel):
    model_config = _FROZEN

    label: str
    amount: float
    currency: str
    asset_class: str
    growth_rate: float | None = None


class LiabilityIn(BaseModel):
    model_config = _FROZEN

    label: str
    principal: float
    annual_rate: float
    monthly_payment: float
    term_months: int
    start_month: str


class BudgetItemIn(BaseModel):
    model_config = _FROZEN

    kind: str
    label: str
    monthly_amount: float
    indexation_rate: float | None = None
    start_month: str | None = None
    end_rule: str = "none"
    end_month: str | None = None


class GoalIn(BaseModel):
    model_config = _FROZEN

    goal_id: int | None
    label: str
    kind: str
    amount_pv: float
    #: What ``amount_pv`` is measured in: ``amount`` — money (a pension: a month's worth), or
    #: ``expense_share`` — a pension's share of the family expenses.
    amount_basis: str = "amount"
    pv_year: int
    target_year: int | None = None
    #: Month of ``target_year`` the goal falls on; None — t0's month.
    target_month: int | None = None
    priority: int = 1
    becomes_asset: bool = False
    can_defer: bool = False
    can_resize: bool = False
    indexation_rate: float | None = None
    #: Label of a ``non_working`` asset sold the month this goal is bought (a car replaced by
    #: a car). Lives on the goal, not the asset, so a deferred goal takes the sale with it.
    replaces_asset: str | None = None
    #: The caption of this purchase's reserve row; None — the default caption.
    reserve_label: str | None = None


class HoldingIn(BaseModel):
    model_config = _FROZEN

    symbol: str
    weight: float


class RebalancingIn(BaseModel):
    """How a stage portfolio is brought back to its target weights.

    The default is okama's own: monthly rebalancing without a deviation corridor.
    """

    model_config = _FROZEN

    period: str = "month"
    abs_deviation: float | None = None
    rel_deviation: float | None = None


class PlanInputs(BaseModel):
    """Everything one run needs, serialisable without a database."""

    model_config = _FROZEN

    t0: str
    horizon_years: int
    #: Fixed years from retirement to the modelled end; None keeps the legacy total-horizon rule.
    withdrawal_years: StrictInt | None = None
    retirement_year: int
    buffer_lookahead_months: int
    #: A lump goal fewer than this many years from t0 is a SAVINGS goal: the buffer saves for it
    #: from the first month (a deposit, bonds) and it never draws on the portfolio. None — the
    #: rule is off and every goal is an investment goal (snapshots written before the field).
    savings_horizon_years: int | None = None
    #: From retirement the family expenses become the pension goal's stream instead of running
    #: beside it. False is the rule of the snapshots written before the field: the expenses
    #: run the whole horizon and the pension is withdrawn on top of them.
    pension_replaces_expenses: bool = False
    #: Every dated purchase before retirement is saved for in the buffer, and the buffer saves
    #: for nothing from retirement on. False is the rule of the snapshots written before
    #: the field: ``savings_horizon_years`` picks the savings goals and the buffer's window looks
    #: past retirement.
    reserves_until_retirement: bool = False
    #: Missing in old snapshots: preserve the pooled reserve exactly.
    savings_mode: Literal["pooled", "separate"] = "pooled"
    goal_savings_rates: dict[str, float] = Field(default_factory=dict)
    rates: Rates
    persons: tuple[PersonIn, ...] = ()
    assets: tuple[AssetIn, ...] = ()
    liabilities: tuple[LiabilityIn, ...] = ()
    budget_items: tuple[BudgetItemIn, ...] = ()
    goals: tuple[GoalIn, ...] = ()
    accumulation_last_date_pin: str = ""
    withdrawal_last_date_pin: str = ""
    accumulation_holdings: tuple[HoldingIn, ...] = ()
    withdrawal_holdings: tuple[HoldingIn, ...] = ()
    accumulation_rebalancing: RebalancingIn = RebalancingIn()
    withdrawal_rebalancing: RebalancingIn = RebalancingIn()

    @field_validator("goal_savings_rates")
    @classmethod
    def validate_savings_rates(cls, value: dict[str, float]) -> dict[str, float]:
        for label, rate in value.items():
            if not math.isfinite(rate) or rate <= -1.0:
                raise ValueError(f"{label}: savings rate must be finite and greater than -1")
        return value
