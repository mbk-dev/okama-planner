"""Month arithmetic anchored to t0.

``t0`` is the pinned ``last_date`` of the portfolios. Calendar year ``Y`` maps to the month
``Y-<month of t0>``, so "in five years" is exactly ``t0 + 60`` months.
"""

from __future__ import annotations

import re

_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def parse_month(value: str) -> tuple[int, int]:
    """Split a ``"YYYY-MM"`` key into ``(year, month)``."""
    match = _MONTH_RE.match(value)
    if match is None:
        raise ValueError(f"month must look like 'YYYY-MM', got {value!r}")
    return int(match.group(1)), int(match.group(2))


def month_key(t0: str, n: int) -> str:
    """The ``"YYYY-MM"`` key of the month ``n`` months after ``t0``."""
    year, month = parse_month(t0)
    total = (year * 12 + month - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_index(t0: str, month: str) -> int:
    """How many months ``month`` is after ``t0``. Negative if before."""
    base_year, base_month = parse_month(t0)
    year, month_number = parse_month(month)
    return (year * 12 + month_number) - (base_year * 12 + base_month)


def year_index(t0: str, year: int) -> int:
    """The month number a calendar year maps to — its ``t0`` month."""
    base_year, _ = parse_month(t0)
    return (year - base_year) * 12


def calendar_year(t0: str, n: int) -> int:
    """The calendar year the month ``n`` falls in."""
    return parse_month(month_key(t0, n))[0]


def horizon_months(horizon_years: int) -> int:
    return horizon_years * 12
