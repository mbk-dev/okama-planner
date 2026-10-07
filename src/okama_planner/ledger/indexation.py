"""Annual indexation on the anniversary of t0.

One rule serves every indexed line: the value in calendar year ``Y`` is
``base * (1 + rate) ** (Y - base_year)``. A lump-sum goal is the case ``Y = target_year``.
"""

from __future__ import annotations


def value_in_year(base: float, rate: float, base_year: int, year: int) -> float:
    """The amount ``base``, stated in ``base_year`` money, expressed in ``year`` money."""
    return base * (1.0 + rate) ** (year - base_year)


def value_at_month(base: float, rate: float, n: int) -> float:
    """The amount in the month ``n`` months after t0, stepping up on each anniversary."""
    return base * (1.0 + rate) ** (n // 12)
