"""Metrics over a hand-made wealth table: the numbers are checkable by eye."""

from __future__ import annotations

import pandas as pd
import pytest

from okama_planner.forecast.results import balance_percentiles, median_survival_years, terminal_percentiles

# Four scenarios over three months. Row = month, column = scenario.
WEALTH = pd.DataFrame(
    [
        [100.0, 200.0, 300.0, 400.0],
        [110.0, 0.0, 330.0, 440.0],
        [120.0, 0.0, 360.0, 480.0],
    ],
    index=pd.PeriodIndex(["2026-08", "2026-09", "2026-10"], freq="M"),
)


def test_percentiles_are_taken_across_scenarios_within_a_month() -> None:
    rows = balance_percentiles(WEALTH, percentiles=(50,))

    by_month = {month: value for month, _, value in rows}
    assert by_month["2026-08"] == pytest.approx(250.0)
    assert by_month["2026-09"] == pytest.approx(220.0)


def test_every_month_and_percentile_is_reported() -> None:
    rows = balance_percentiles(WEALTH, percentiles=(10, 50, 90))

    assert len(rows) == 9
    assert {percentile for _, percentile, _ in rows} == {10, 50, 90}
    assert [month for month, percentile, _ in rows if percentile == 10] == [
        "2026-08",
        "2026-09",
        "2026-10",
    ]


def test_terminal_percentiles_read_the_chronologically_last_month() -> None:
    terminal = terminal_percentiles(WEALTH, percentiles=(50,))

    assert terminal["p50"] == pytest.approx(240.0)


def test_terminal_percentiles_handles_unsorted_index() -> None:
    # Same data as WEALTH, but rows in a different order.
    # Chronologically last month (2026-10) is NOT in the last position.
    unsorted = pd.DataFrame(
        [
            [120.0, 0.0, 360.0, 480.0],
            [100.0, 200.0, 300.0, 400.0],
            [110.0, 0.0, 330.0, 440.0],
        ],
        index=pd.PeriodIndex(["2026-10", "2026-08", "2026-09"], freq="M"),
    )

    terminal = terminal_percentiles(unsorted, percentiles=(50,))

    # p50 of 2026-10 is 240.0, which must be returned even though
    # 2026-10 is not in the last position.
    assert terminal["p50"] == pytest.approx(240.0)


def test_median_survival_is_the_median_over_scenarios() -> None:
    survival = pd.Series([10.0, 12.0, 40.0, 60.0])

    assert median_survival_years(survival) == pytest.approx(26.0)
