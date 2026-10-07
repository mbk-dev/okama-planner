"""Time is anchored to t0, the pinned last_date of the portfolios — never to today."""

from __future__ import annotations

import pytest

from okama_planner.ledger.calendar import (
    calendar_year,
    horizon_months,
    month_index,
    month_key,
    parse_month,
    year_index,
)


def test_parse_month() -> None:
    assert parse_month("2026-08") == (2026, 8)


def test_a_malformed_month_fails_loudly() -> None:
    with pytest.raises(ValueError, match="2026/08"):
        parse_month("2026/08")


def test_month_key_walks_forward_across_the_year_boundary() -> None:
    assert month_key("2026-08", 0) == "2026-08"
    assert month_key("2026-08", 4) == "2026-12"
    assert month_key("2026-08", 5) == "2027-01"
    assert month_key("2026-08", 12) == "2027-08"


def test_month_index_is_the_inverse_of_month_key() -> None:
    assert month_index("2026-08", "2026-08") == 0
    assert month_index("2026-08", "2031-08") == 60


def test_a_goal_year_maps_to_the_month_of_t0() -> None:
    # "in five years" is exactly t0 + 60 months.
    assert year_index("2026-08", 2031) == 60
    assert month_key("2026-08", year_index("2026-08", 2031)) == "2031-08"


def test_calendar_year_of_a_month_number() -> None:
    assert calendar_year("2026-08", 0) == 2026
    assert calendar_year("2026-08", 4) == 2026
    assert calendar_year("2026-08", 5) == 2027


def test_horizon_months() -> None:
    assert horizon_months(60) == 720
