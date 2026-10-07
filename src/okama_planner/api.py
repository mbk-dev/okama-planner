"""Stateless forecast API; no registry, database, workbook or filesystem side effects."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict
from importlib.metadata import version
from typing import Any, Literal

os.environ.setdefault("MPLBACKEND", "Agg")

import okama as ok  # noqa: E402 — set the headless backend before importing okama
import pandas as pd  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, model_validator  # noqa: E402

from okama_planner.forecast.goal_results import goal_outcomes  # noqa: E402
from okama_planner.forecast.plan import build_finplan  # noqa: E402
from okama_planner.forecast.portfolios import annual_parameters  # noqa: E402
from okama_planner.forecast.results import (  # noqa: E402
    balance_percentiles,
    median_survival_years,
    terminal_percentiles,
)
from okama_planner.horizon import effective_horizon_years  # noqa: E402
from okama_planner.inputs import PlanInputs  # noqa: E402
from okama_planner.history import HistoryPortfolio  # noqa: E402
from okama_planner.ledger.build import build_ledger  # noqa: E402
from okama_planner.ledger.mortgage import liability_track  # noqa: E402

PERCENTILES = (10, 25, 50, 75, 90)
_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class ReturnSample(BaseModel):
    """Contiguous monthly portfolio total returns, already expressed in the plan currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    start_month: str = Field(pattern=_MONTH)
    monthly_returns: tuple[float, ...] = Field(min_length=12)

    @model_validator(mode="after")
    def valid_returns(self) -> ReturnSample:
        if any(not math.isfinite(x) or x < -1 for x in self.monthly_returns):
            raise ValueError("Monthly returns must be finite and at least -1")
        return self


class StageSamples(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    accumulation: ReturnSample
    withdrawal: ReturnSample


class ForecastRequest(BaseModel):
    """Full standalone request. Asset amounts and cash flows use a single explicit currency."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan: PlanInputs
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    mc_number: int = Field(default=1000, ge=1, le=10000, strict=True)
    seed: int = Field(default=0, ge=0, strict=True)
    distribution: Literal["norm", "lognorm", "t"] = "norm"
    match_moments: bool = True
    return_samples: StageSamples | None = None

    @model_validator(mode="after")
    def valid_plan(self) -> ForecastRequest:
        plan = self.plan
        pd.Period(plan.t0, freq="M")
        effective_horizon_years(plan)
        if plan.buffer_lookahead_months < 0:
            raise ValueError("Buffer lookahead must not be negative")
        if sum(a.amount for a in plan.assets if a.asset_class == "portfolio") <= 0:
            raise ValueError("okama FinPlan requires positive opening portfolio capital")
        if any(a.currency != self.currency for a in plan.assets):
            raise ValueError("Mixed asset currencies require an FX model, which is not supported")
        _validate_structure(plan)
        _validate_values(plan)
        if self.return_samples is not None and (plan.accumulation_holdings or plan.withdrawal_holdings):
            raise ValueError("Provide frozen stage samples or holdings, not both")
        return self


def _validate_structure(plan: PlanInputs) -> None:
    _validate_categories(plan)
    for item in plan.budget_items:
        if item.end_rule not in {"none", "until_retirement", "until_month"}:
            raise ValueError(f"{item.label}: unknown budget end_rule {item.end_rule!r}")
    for goal in plan.goals:
        if goal.target_month is not None and not 1 <= goal.target_month <= 12:
            raise ValueError(f"{goal.label}: target_month must be between 1 and 12")
    for loan in plan.liabilities:
        if (
            not all(math.isfinite(x) for x in (loan.principal, loan.annual_rate, loan.monthly_payment))
            or loan.principal < 0
            or loan.annual_rate < 0
            or loan.monthly_payment <= 0
        ):
            raise ValueError(f"{loan.label}: invalid liability amounts or rate")
    labels = [g.label for g in plan.goals]
    ids = [g.goal_id for g in plan.goals if g.goal_id is not None]
    if len(set(labels)) != len(labels) or len(set(ids)) != len(ids):
        raise ValueError("Goal labels and non-null IDs must be unique")


def _validate_categories(plan: PlanInputs) -> None:
    for goal in plan.goals:
        if goal.kind not in {"lump", "reserve_topup", "retirement_income"}:
            raise ValueError(f"{goal.label}: unknown goal kind {goal.kind!r}")
        if goal.amount_basis not in {"amount", "expense_share"}:
            raise ValueError(f"{goal.label}: unknown amount_basis {goal.amount_basis!r}")
        if goal.amount_basis == "expense_share" and goal.kind != "retirement_income":
            raise ValueError("expense_share is supported only for retirement_income")


def _validate_values(plan: PlanInputs) -> None:
    rates = list(plan.rates.model_dump().values())
    rates.extend(a.growth_rate for a in plan.assets if a.growth_rate is not None)
    rates.extend(b.indexation_rate for b in plan.budget_items if b.indexation_rate is not None)
    rates.extend(g.indexation_rate for g in plan.goals if g.indexation_rate is not None)
    if any(not math.isfinite(r) or r <= -1 for r in rates):
        raise ValueError("Rates must be finite and greater than -1")
    amounts = [a.amount for a in plan.assets]
    amounts.extend(b.monthly_amount for b in plan.budget_items)
    amounts.extend(g.amount_pv for g in plan.goals)
    if any(not math.isfinite(a) or a < 0 for a in amounts):
        raise ValueError("Amounts must be finite and nonnegative")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def forecast(request: ForecastRequest | dict[str, Any]) -> dict[str, Any]:
    """Return household flows, goal outcomes, forecast metrics, chart series and provenance."""
    request = ForecastRequest.model_validate(request)
    inputs = request.plan
    ledger = build_ledger(inputs)
    portfolios = None
    if request.return_samples is not None:
        portfolios = (
            HistoryPortfolio(
                start_month=request.return_samples.accumulation.start_month,
                returns=request.return_samples.accumulation.monthly_returns,
                ccy=request.currency,
            ),
            HistoryPortfolio(
                start_month=request.return_samples.withdrawal.start_month,
                returns=request.return_samples.withdrawal.monthly_returns,
                ccy=request.currency,
            ),
        )
    if portfolios:
        updates = {}
        for name, portfolio in zip(("accumulation", "withdrawal"), portfolios, strict=True):
            pin = f"{portfolio.last_date:%Y-%m}"
            declared = getattr(inputs, f"{name}_last_date_pin")
            if declared and declared != pin:
                raise ValueError(f"{name} history ends at {pin}, conflicting with pin {declared}")
            if pd.Period(pin, freq="M") > pd.Period(inputs.t0, freq="M"):
                raise ValueError(f"{name} history {pin} follows plan start {inputs.t0}")
            updates[f"{name}_last_date_pin"] = pin
        inputs = inputs.model_copy(update=updates)
    plan = build_finplan(
        inputs,
        ledger,
        mc_number=request.mc_number,
        seed=request.seed,
        distribution=request.distribution,
        ccy=request.currency,
        match_moments=request.match_moments,
        accumulation_portfolio=portfolios[0] if portfolios else None,
        withdrawal_portfolio=portfolios[1] if portfolios else None,
    )
    wealth = plan.monte_carlo_wealth(include_negative_values=False)
    metrics = {
        "probability_of_success": float(plan.probability_of_success()),
        "median_survival_years": median_survival_years(plan.monte_carlo_survival_period()),
        **{f"terminal_{k}": v for k, v in terminal_percentiles(wealth, PERCENTILES).items()},
    }
    stages = []
    for stage in plan.stages:
        returns = stage.portfolio.ror
        mean, risk = annual_parameters(stage.portfolio)
        stages.append(
            {
                "name": stage.name,
                "mean_return_annual": mean,
                "risk_annual": risk,
                "history_first_month": str(returns.index[0]),
                "history_last_month": str(returns.index[-1]),
                "history_sha256": _digest({str(k): float(v) for k, v in returns.items()}),
            }
        )
    portfolio_chart: dict[str, dict[str, Any]] = {}
    for month, percentile, value in balance_percentiles(wealth, PERCENTILES):
        portfolio_chart.setdefault(month, {"month": month})[f"p{percentile}"] = value
    capital_chart = []
    for row in portfolio_chart.values():
        if row["month"] in ledger.portfolio_flow:
            n = ledger.months.index(row["month"])
            outside = (
                ledger.buffer_balance[n]
                + ledger.reserve_balance[n]
                + ledger.non_working_balance[n]
                - ledger.liability_balance[n]
            )
        else:
            outside = sum(
                a.amount for a in inputs.assets if a.asset_class in {"savings", "reserve", "non_working"}
            )
            outside -= sum(liability_track(loan, row["month"], 1)[0][0] for loan in inputs.liabilities)
        capital_chart.append(
            {"month": row["month"], **{f"p{p}": row[f"p{p}"] + outside for p in PERCENTILES}}
        )
    return {
        "schema_version": "1.0",
        "currency": request.currency,
        "portfolio_mode": "single",
        "metrics": metrics,
        "goals": [asdict(x) for x in goal_outcomes(wealth, inputs, ledger)],
        "ledger": asdict(ledger),
        "portfolio_flow": dict(ledger.portfolio_flow),
        "charts": {"portfolio": list(portfolio_chart.values()), "capital": capital_chart},
        "provenance": {
            "input_sha256": _digest(request.model_dump(mode="json")),
            "seed": request.seed,
            "mc_number": request.mc_number,
            "distribution": request.distribution,
            "match_moments": request.match_moments,
            "okama_version": ok.__version__,
            "numpy_version": version("numpy"),
            "pandas_version": version("pandas"),
            "scipy_version": version("scipy"),
            "data_source": "provided_stage_samples" if portfolios else "okama_api",
            "stages": stages,
        },
    }
