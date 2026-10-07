"""A narrow FinPlan portfolio adapter for fixed monthly portfolio return observations.

This is not a market-data Portfolio: holdings, rebalancing and FX must already be
reflected in the supplied return series. Only FinPlan's forecasting interface is supported.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence

os.environ.setdefault("MPLBACKEND", "Agg")

import okama as ok  # noqa: E402 — set the backend before okama imports matplotlib
import pandas as pd  # noqa: E402 — imports after backend setup


class HistoryPortfolio(ok.Portfolio):
    """Use frozen observations without downloading currency or inflation histories."""

    def __init__(self, *, start_month: str, returns: Sequence[float], ccy: str) -> None:
        values = tuple(float(x) for x in returns)
        if len(values) < 3 or any(not math.isfinite(x) or x < -1 for x in values):
            raise ValueError("History needs at least three finite monthly returns >= -1")
        self._history = pd.Series(values, index=pd.period_range(start_month, periods=len(values), freq="M"))
        self._history_ccy = ccy
        self.first_date = self._history.index[0].to_timestamp()
        self.last_date = self._history.index[-1].to_timestamp()
        self._symbol = "frozen_history.PF"

    @property
    def ror(self) -> pd.Series:
        return self._history.copy()

    @property
    def currency(self) -> str:
        return self._history_ccy
