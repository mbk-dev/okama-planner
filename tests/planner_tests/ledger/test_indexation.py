"""A line is indexed once a year, on the anniversary of t0."""

from __future__ import annotations

import pytest

from okama_planner.ledger.indexation import value_at_month, value_in_year


def test_the_first_twelve_months_carry_the_base_amount() -> None:
    assert value_at_month(100_000.0, 0.10, 0) == pytest.approx(100_000.0)
    assert value_at_month(100_000.0, 0.10, 11) == pytest.approx(100_000.0)


def test_the_amount_steps_up_on_the_anniversary() -> None:
    assert value_at_month(100_000.0, 0.10, 12) == pytest.approx(110_000.0)
    assert value_at_month(100_000.0, 0.10, 25) == pytest.approx(121_000.0)


def test_pv_to_fv_over_five_years() -> None:
    # 13 000 000 in 2026 money, bought in 2031, goals indexed at 9%.
    assert value_in_year(13_000_000.0, 0.09, 2026, 2031) == pytest.approx(13_000_000.0 * 1.09**5)
    assert value_in_year(13_000_000.0, 0.09, 2026, 2031) == pytest.approx(20_002_111.41, abs=0.01)


def test_a_zero_rate_leaves_the_amount_alone() -> None:
    assert value_in_year(500_000.0, 0.0, 2026, 2060) == pytest.approx(500_000.0)


def test_a_year_before_the_base_year_discounts() -> None:
    assert value_in_year(100.0, 0.10, 2026, 2025) == pytest.approx(100.0 / 1.10)
