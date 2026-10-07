"""What each stage's Monte Carlo draws from.

okama estimates a distribution's parameters from the portfolio's whole monthly history. For the
normal that is the sample mean and standard deviation — the centre of the data. For Student's t it
is a maximum-likelihood fit of all three parameters, and there is a trap in it: the t's fitted
location is robust and lands near the sample *median*, which on a left-skewed return series sits
above the mean. Choosing 't' to be honest about fat tails would then also raise the expected
return, and the plan would come out more optimistic, not less.

So the tail shape is fitted and nothing else: df from the data, the centre and the spread from the
sample's own moments. What changes against a normal run is then the shape alone, which is the
question a plan actually asks — what do fat tails cost me.
"""

from __future__ import annotations

import math
from typing import Any

from scipy import stats


class DegenerateTailError(ValueError):
    """The fitted tail has no finite variance, so no scale can match the sample's spread."""


def stage_parameters(portfolio: Any, distribution: str) -> tuple[float, ...] | None:
    """The ``distribution_parameters`` for one stage, or None to leave the fit to okama.

    ``norm`` needs nothing: okama already uses the sample moments. ``lognorm`` is left alone too —
    okama pins its location at -1, and matching moments under that constraint is a different
    exercise from this one.
    """
    if distribution != "t":
        return None
    ror = portfolio.ror
    df = float(stats.t.fit(ror)[0])
    if df <= 2.0:
        raise DegenerateTailError(
            f"the fitted df is {df:.2f}: a Student's t with df <= 2 has no finite variance, "
            "so the sample's spread cannot be preserved — check the return series"
        )
    mean, sd = float(ror.mean()), float(ror.std())
    return df, mean, sd * math.sqrt((df - 2.0) / df)
