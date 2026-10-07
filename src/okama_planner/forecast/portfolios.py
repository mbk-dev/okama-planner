"""Building the two stage portfolios.

Portfolios are cached for the life of the process to reuse downloaded return histories
across independent calculations with the same portfolio specification.

``last_date`` pins the historical sample, independently of the forecast start. The caller checks
that returned histories match their pins; ``DatedFinPlan`` keeps cash-flow dates at the chosen start.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import lru_cache

os.environ.setdefault("MPLBACKEND", "Agg")

import okama as ok  # noqa: E402  (the matplotlib backend must be set before okama imports it)

DEFAULT_REBALANCING_PERIOD = "month"
from okama_planner.inputs import HoldingIn, RebalancingIn  # noqa: E402  (after the backend setup)


@lru_cache(maxsize=32)
def build_portfolio(
    symbols: tuple[str, ...],
    weights: tuple[float, ...],
    ccy: str,
    last_date: str,
    rebalancing_period: str = DEFAULT_REBALANCING_PERIOD,
    abs_deviation: float | None = None,
    rel_deviation: float | None = None,
) -> ok.Portfolio:
    """A portfolio with its ``last_date`` pinned, cached on its full specification.

    The rebalancing strategy is part of that specification: okama rebalances monthly by default,
    and the same weights rebalanced yearly are a different return series. Scalars rather
    than a ``Rebalance`` object, so the cache key stays hashable and comparable.
    """
    if len(symbols) != len(weights):
        raise ValueError(f"{len(symbols)} symbols against {len(weights)} weights")
    if not last_date or not last_date.strip():
        raise ValueError("last_date must not be blank")
    return ok.Portfolio(
        list(symbols),
        weights=list(weights),
        ccy=ccy,
        last_date=last_date,
        rebalancing_strategy=ok.Rebalance(
            period=rebalancing_period,
            abs_deviation=abs_deviation,
            rel_deviation=rel_deviation,
        ),
    )


def from_holdings(
    holdings: Sequence[HoldingIn],
    ccy: str,
    last_date: str,
    rebalancing: RebalancingIn | None = None,
) -> ok.Portfolio:
    """Build the portfolio described by a snapshot's holdings and its rebalancing strategy."""
    if not holdings:
        raise ValueError("a portfolio needs at least one holding")
    strategy = rebalancing if rebalancing is not None else RebalancingIn()
    return build_portfolio(
        tuple(holding.symbol for holding in holdings),
        tuple(holding.weight for holding in holdings),
        ccy,
        last_date,
        strategy.period,
        strategy.abs_deviation,
        strategy.rel_deviation,
    )


#: okama annualises monthly figures over twelve months (``settings._MONTHS_PER_YEAR``).
MONTHS_PER_YEAR = 12


def annual_parameters(portfolio: ok.Portfolio) -> tuple[float, float]:
    """The annual return and risk the Monte Carlo actually draws from.

    For ``norm`` okama estimates the distribution from the portfolio's whole monthly return
    history — ``mu = ror.mean()``, ``sigma = ror.std()``
    (``_resolve_params_for_normal`` in ``okama/portfolios/mc.py``) — and draws every month of every
    path from it. Annualised here by okama's own two formulas (``Float.annualize_return`` and
    ``Float.annualize_risk``), so the workbook states the numbers behind the forecast and not a
    neighbouring statistic: ``Portfolio.mean_return_annual`` is a different number;
    the history's CAGR is a third statistic.
    """
    mu = float(portfolio.ror.mean())
    sigma = float(portfolio.ror.std())
    annual_return = (1.0 + mu) ** MONTHS_PER_YEAR - 1.0
    annual_risk = (
        (sigma**2 + (1.0 + mu) ** 2) ** MONTHS_PER_YEAR - (1.0 + mu) ** (2 * MONTHS_PER_YEAR)
    ) ** 0.5
    return annual_return, annual_risk
