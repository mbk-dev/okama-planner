"""Metrics computed from the Monte Carlo output.

Everything here takes a DataFrame, not a plan, so it can be checked against a table written by
hand. ``monte_carlo_wealth`` gives ``(period_months + 1, mc_number)``: one row per month, one
column per scenario, the first row being the opening balance one month before t0.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def _month_key(period: object) -> str:
    return f"{period}"


def balance_percentiles(wealth: pd.DataFrame, percentiles: Sequence[int]) -> list[tuple[str, int, float]]:
    """``(month, percentile, value)`` — the distribution across scenarios within each month."""
    rows: list[tuple[str, int, float]] = []
    for percentile in percentiles:
        series = wealth.quantile(percentile / 100.0, axis=1)
        rows.extend((_month_key(index), percentile, float(value)) for index, value in series.items())
    return rows


def terminal_percentiles(wealth: pd.DataFrame, percentiles: Sequence[int]) -> dict[str, float]:
    """The balance distribution at the end of the horizon, keyed ``"p50"`` and so on."""
    last = wealth.loc[wealth.index.max()]
    return {f"p{percentile}": float(last.quantile(percentile / 100.0)) for percentile in percentiles}


def median_survival_years(survival: pd.Series) -> float:
    """Median years of positive balance across scenarios. Input must already be in years."""
    return float(survival.median())
