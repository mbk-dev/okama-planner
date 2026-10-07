"""Which parameters each stage draws from: the tail shape must not move the centre."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from scipy import stats

from okama_planner.forecast.distributions import DegenerateTailError, stage_parameters


class _WithRor:
    def __init__(self, ror: pd.Series) -> None:
        self.ror = ror


SAMPLE = pd.Series([0.01, -0.02, 0.03, 0.0, 0.015, -0.005, 0.04, -0.06, 0.02, 0.005] * 8)


def test_the_normal_is_left_to_okama_which_already_uses_the_sample_moments() -> None:
    assert stage_parameters(_WithRor(SAMPLE), "norm") is None


def test_the_lognormal_is_left_to_okama_too() -> None:
    """Its loc is pinned at -1 by okama; matching moments there is a different exercise."""
    assert stage_parameters(_WithRor(SAMPLE), "lognorm") is None


def test_the_t_keeps_the_sample_centre_and_spread_and_fits_only_the_tail() -> None:
    """A free t fit puts the centre near the median, which on a left-skewed sample is above the
    mean — asking for fat tails would quietly raise the expected return."""
    df, loc, scale = stage_parameters(_WithRor(SAMPLE), "t")

    assert df == pytest.approx(float(stats.t.fit(SAMPLE)[0]))
    assert loc == pytest.approx(float(SAMPLE.mean()))
    # Var(t) = scale² · df/(df−2), so this scale reproduces the sample's standard deviation.
    assert scale == pytest.approx(float(SAMPLE.std()) * math.sqrt((df - 2.0) / df))
    assert stats.t(df=df, loc=loc, scale=scale).std() == pytest.approx(float(SAMPLE.std()))


def test_a_tail_too_heavy_to_have_a_variance_is_refused() -> None:
    """df ≤ 2 means infinite variance: there is no scale that matches the sample's spread."""
    cauchy = pd.Series(stats.cauchy.rvs(size=400, random_state=0))

    with pytest.raises(DegenerateTailError, match="df"):
        stage_parameters(_WithRor(cauchy), "t")
