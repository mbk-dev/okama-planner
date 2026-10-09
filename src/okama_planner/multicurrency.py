"""Native-currency goal groups financed by one household budget and shared FX paths."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from okama_planner.api import ForecastRequest, _validate_structure, _validate_values
from okama_planner.horizon import effective_horizon_years
from okama_planner.inputs import PlanInputs
from okama_planner.scenarios import JointHistory, JointScenarios, sample_joint_returns


class CurrencyGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    group_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    request: ForecastRequest


class FXHistory(BaseModel):
    """Opening quotes and monthly changes in base-currency units per foreign unit."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    start_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    opening_rates: dict[str, float]
    monthly_returns: dict[str, tuple[float, ...]]

    @model_validator(mode="after")
    def valid_values(self) -> FXHistory:
        if any(not math.isfinite(v) or v <= 0 for v in self.opening_rates.values()):
            raise ValueError("Opening FX rates must be finite and positive")
        if any(not math.isfinite(v) or v <= -1 for values in self.monthly_returns.values() for v in values):
            raise ValueError("FX return factors must remain finite and positive")
        return self


class CurrencyContribution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    start_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    weights: dict[str, float]


class MulticurrencyRequest(BaseModel):
    """One budget, explicitly owned native accounts, and synchronized market/FX history."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    household: PlanInputs
    groups: tuple[CurrencyGroup, ...] = Field(min_length=1)
    fx: FXHistory
    contribution_schedule: tuple[CurrencyContribution, ...] = Field(min_length=1)
    household_funding_order: tuple[str, ...]
    conversion_fee_rate: float = Field(ge=0, lt=1, allow_inf_nan=False)
    mc_number: int = Field(ge=1, le=10000, strict=True)
    seed: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def valid_groups(self) -> MulticurrencyRequest:
        household = self.household
        _validate_structure(household)
        _validate_values(household)
        if household.goals or household.assets or household.liabilities:
            raise ValueError(
                "Household owns the budget/persons; assets, liabilities and goals belong to groups"
            )
        effective_horizon_years(household)
        ids = [g.group_id for g in self.groups]
        currencies = [g.request.currency for g in self.groups]
        if len(ids) != len(set(ids)) or len(currencies) != len(set(currencies)):
            raise ValueError("Group IDs and currencies must be unique")
        if set(self.household_funding_order) != set(ids) or len(self.household_funding_order) != len(ids):
            raise ValueError("Household funding order must contain each currency group exactly once")
        if set(self.fx.opening_rates) != {self.currency, *currencies}:
            raise ValueError("Opening FX quotes must cover exactly the base and group currencies")
        if self.fx.opening_rates[self.currency] != 1:
            raise ValueError("Base-currency FX quote must equal one")
        if set(self.fx.monthly_returns) != set(currencies) - {self.currency}:
            raise ValueError("FX history must cover exactly the foreign group currencies")
        self._validate_histories()
        self._validate_contributions()
        return self

    def _validate_histories(self) -> None:
        goals = []
        lengths = set()
        for group in self.groups:
            native = group.request
            plan = native.plan
            if native.joint_history is None:
                raise ValueError("Currency groups require native joint_history and explicit allocation")
            if plan.budget_items:
                raise ValueError("Group budget items would duplicate the household budget")
            if (plan.t0, effective_horizon_years(plan), plan.retirement_year) != (
                self.household.t0,
                effective_horizon_years(self.household),
                self.household.retirement_year,
            ):
                raise ValueError("Currency groups must share household start, horizon and retirement")
            if native.joint_history.start_month != self.fx.start_month:
                raise ValueError("Asset and FX history start months must align")
            lengths.update(len(v) for v in native.joint_history.asset_returns.values())
            goals.extend(g.goal_id for g in plan.goals)
        lengths.update(len(v) for v in self.fx.monthly_returns.values())
        if len(lengths) != 1:
            raise ValueError("Asset and FX history lengths must align")
        if len(goals) != len(set(goals)):
            raise ValueError("Goal IDs must be unique across currency groups")

    def _validate_contributions(self) -> None:
        household = self.household
        years = effective_horizon_years(household)
        ids = [g.group_id for g in self.groups]
        start = pd.Period(household.t0, freq="M")
        dates = [pd.Period(s.start_month, freq="M") for s in self.contribution_schedule]
        if dates[0] != start or any(a >= b for a, b in zip(dates[:-1], dates[1:], strict=True)):
            raise ValueError("Contribution dates must start at t0 and ascend strictly")
        if dates[-1] >= start + 12 * years:
            raise ValueError("Contribution dates must stay within the plan horizon")
        for step in self.contribution_schedule:
            if set(step.weights) != set(ids):
                raise ValueError("Contribution weights must reference each currency group")
            if any(not math.isfinite(w) or w < 0 for w in step.weights.values()) or not math.isclose(
                sum(step.weights.values()), 1, abs_tol=1e-12, rel_tol=0
            ):
                raise ValueError("Contribution weights must be nonnegative and sum to one")


def sample_multicurrency(
    request: MulticurrencyRequest,
) -> tuple[dict[str, JointScenarios], dict[str, np.ndarray], JointScenarios]:
    """Draw the same historical row for every native asset and FX change."""
    data = {}
    for group in request.groups:
        data.update(
            {
                f"group/{group.group_id}/{asset}": values
                for asset, values in group.request.joint_history.asset_returns.items()
            }
        )
    data.update({f"fx/{currency}": values for currency, values in request.fx.monthly_returns.items()})
    history = JointHistory(
        start_month=request.fx.start_month,
        currency=request.currency,
        method="synchronized_bootstrap",
        asset_returns=data,
    )
    months = 12 * effective_horizon_years(request.household)
    common = sample_joint_returns(history, months=months, paths=request.mc_number, seed=request.seed)
    groups = {}
    for group in request.groups:
        assets = tuple(sorted(group.request.joint_history.asset_returns))
        indices = [common.assets.index(f"group/{group.group_id}/{asset}") for asset in assets]
        groups[group.group_id] = JointScenarios(
            assets,
            common.returns[:, :, indices],
            common.row_indices,
            common.history_sha256,
        )
    quotes = {request.currency: np.ones((months + 1, request.mc_number))}
    for currency, opening in request.fx.opening_rates.items():
        if currency == request.currency:
            continue
        values = common.returns[:, :, common.assets.index(f"fx/{currency}")]
        with np.errstate(over="raise", invalid="raise", under="raise"):
            try:
                quotes[currency] = np.vstack(
                    (np.full(request.mc_number, opening), opening * np.cumprod(1 + values, axis=0))
                )
            except FloatingPointError as error:
                raise ValueError("Simulated FX quotes must stay finite and positive") from error
        if not np.isfinite(quotes[currency]).all() or np.any(quotes[currency] <= 0):
            raise ValueError("Simulated FX quotes must stay finite and positive")
    return groups, quotes, common


def forecast_multicurrency(request: MulticurrencyRequest | dict[str, Any]) -> dict[str, Any]:
    """Run a validated multi-currency snapshot without downloading market data."""
    from okama_planner.multicurrency_engine import multicurrency_result

    parsed = MulticurrencyRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, MulticurrencyRequest) else request,
    )
    return multicurrency_result(parsed)
