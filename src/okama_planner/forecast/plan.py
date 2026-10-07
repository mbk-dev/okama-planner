"""From the ledger to a FinPlan.

The whole plan reduces to one ledger and two slices of it: both stages use ``TimeSeriesStrategy``,
because ``IndexationStrategy`` cannot carry a lump sum, and a goal dated after retirement would
therefore be inexpressible.
"""

from __future__ import annotations

import os

os.environ.setdefault("MPLBACKEND", "Agg")

import okama as ok  # noqa: E402 — the matplotlib backend must be set before okama imports it
import pandas as pd  # noqa: E402 — imports after the matplotlib backend setup

from okama_planner.forecast.distributions import stage_parameters  # noqa: E402 — imports scipy after the backend setup
from okama_planner.forecast.portfolios import from_holdings  # noqa: E402 — from_holdings transitively imports okama
from okama_planner.horizon import InvalidPlanHorizonError, accumulation_years, effective_horizon_years
from okama_planner.inputs import PlanInputs
from okama_planner.ledger.calendar import year_index
from okama_planner.ledger.types import Ledger


EmptyStageError = InvalidPlanHorizonError


def initial_investment(inputs: PlanInputs) -> float:
    """The opening balance: the sum of the ``portfolio`` class assets, and nothing else.

    ``FinPlan.initial_investment`` is the only source of the opening balance; the
    ``initial_investment`` of each stage's strategy is ignored by okama.
    """
    return sum(asset.amount for asset in inputs.assets if asset.asset_class == "portfolio")


def stage_periods(inputs: PlanInputs) -> tuple[int, int]:
    """Length of each stage in whole years, as ``FinPlanStage.period`` expects."""
    accumulation = accumulation_years(inputs)
    total = effective_horizon_years(inputs)
    return accumulation, total - accumulation


def split_cashflows(ledger: Ledger, retirement_index: int) -> tuple[dict[str, float], dict[str, float]]:
    """Split the portfolio flow at the retirement month, which belongs to the withdrawal stage."""
    accumulation: dict[str, float] = {}
    withdrawal: dict[str, float] = {}
    for n, month in enumerate(ledger.months):
        target = accumulation if n < retirement_index else withdrawal
        target[month] = ledger.portfolio_flow[month]
    return accumulation, withdrawal


def retirement_index(inputs: PlanInputs) -> int:
    """The month number the withdrawal stage opens on."""
    return year_index(inputs.t0, inputs.retirement_year)


class T0MismatchError(RuntimeError):
    """A history pin drifted, follows the start, or the forecast start itself drifted."""


class DatedFinPlan(ok.FinPlan):
    """Keep Monte Carlo dates independent of the history used to fit its returns."""

    def __init__(self, *, start_month: str, **kwargs: object) -> None:
        self._start_date = pd.Period(start_month, freq="M").to_timestamp()
        super().__init__(**kwargs)

    @property
    def t0(self) -> pd.Timestamp:
        return self._start_date


def _strategy(portfolio: ok.Portfolio, series: dict[str, float]) -> ok.TimeSeriesStrategy:
    strategy = ok.TimeSeriesStrategy(portfolio)
    strategy.time_series_dic = dict(series)
    # The ledger already indexes nominal amounts. Prevent okama indexing them a second time.
    strategy.time_series_discounted_values = True
    return strategy


def build_finplan(
    inputs: PlanInputs,
    ledger: Ledger,
    *,
    mc_number: int,
    seed: int,
    distribution: str = "norm",
    ccy: str = "RUB",
    match_moments: bool = True,
    accumulation_portfolio: ok.Portfolio | None = None,
    withdrawal_portfolio: ok.Portfolio | None = None,
) -> ok.FinPlan:
    """Assemble the two-stage plan over one ledger.

    ``match_moments`` keeps a fat-tailed run comparable to a normal one: the tail shape is fitted,
    the centre and the spread stay the sample's own. Turning it off hands the fit back to okama and
    exposes the unconstrained fit; its expected return may differ from the normal sample mean.
    """
    accumulation_portfolio = (
        accumulation_portfolio
        if accumulation_portfolio is not None
        else from_holdings(
            inputs.accumulation_holdings,
            ccy,
            inputs.accumulation_last_date_pin,
            inputs.accumulation_rebalancing,
        )
    )
    withdrawal_portfolio = (
        withdrawal_portfolio
        if withdrawal_portfolio is not None
        else from_holdings(
            inputs.withdrawal_holdings,
            ccy,
            inputs.withdrawal_last_date_pin,
            inputs.withdrawal_rebalancing,
        )
    )

    for stage_name, portfolio, pin in (
        ("accumulation", accumulation_portfolio, inputs.accumulation_last_date_pin),
        ("withdrawal", withdrawal_portfolio, inputs.withdrawal_last_date_pin),
    ):
        actual = f"{portfolio.last_date:%Y-%m}"
        if actual != pin:
            raise T0MismatchError(
                f"the {stage_name} portfolio's last_date is {actual} but its history pin is {pin}; "
                "a portfolio's last_date is stale — fix the data, do not shift the plan"
            )
        if pd.Period(pin, freq="M") > pd.Period(inputs.t0, freq="M"):
            raise T0MismatchError(f"the {stage_name} history {pin} follows the plan start {inputs.t0}")

    parameters = {
        name: stage_parameters(portfolio, distribution) if match_moments else None
        for name, portfolio in (
            ("accumulation", accumulation_portfolio),
            ("withdrawal", withdrawal_portfolio),
        )
    }

    accumulation_years, withdrawal_years = stage_periods(inputs)
    accumulation_flow, withdrawal_flow = split_cashflows(ledger, retirement_index(inputs))

    plan = DatedFinPlan(
        start_month=inputs.t0,
        stages=[
            ok.FinPlanStage(
                accumulation_portfolio,
                period=accumulation_years,
                cashflow_parameters=_strategy(accumulation_portfolio, accumulation_flow),
                distribution=distribution,
                distribution_parameters=parameters["accumulation"],
                name="accumulation",
            ),
            ok.FinPlanStage(
                withdrawal_portfolio,
                period=withdrawal_years,
                cashflow_parameters=_strategy(withdrawal_portfolio, withdrawal_flow),
                distribution=distribution,
                distribution_parameters=parameters["withdrawal"],
                name="withdrawal",
            ),
        ],
        initial_investment=initial_investment(inputs),
        mc_number=mc_number,
        seed=seed,
        # Always explicit: left out, okama substitutes the first stage's inflation CAGR.
        discount_rate=inputs.rates.discount_rate,
    )

    # Assert the adapter's date before any simulated cash flows are consumed.
    actual_t0 = f"{plan.t0:%Y-%m}"
    if actual_t0 != inputs.t0:
        raise T0MismatchError(
            f"plan t0 is {actual_t0} but the plan declares {inputs.t0}; "
            "a portfolio's last_date is stale — fix the data, do not shift the plan"
        )
    return plan
