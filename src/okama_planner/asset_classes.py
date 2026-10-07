"""Asset roles in a household plan, independent of any storage model."""

from enum import StrEnum


class AssetClass(StrEnum):
    PORTFOLIO = "portfolio"
    RESERVE = "reserve"
    NON_WORKING = "non_working"
    THIRD_PARTY = "third_party"
    SAVINGS = "savings"
