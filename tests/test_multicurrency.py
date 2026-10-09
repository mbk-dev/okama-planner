"""Multi-currency requests preserve the single ownership of household flows."""

import copy
import importlib

import pytest

from test_allocation import allocation, request


def multicurrency_request() -> dict:
    groups = []
    for group_id, currency in [("ruble", "RUB"), ("dollar", "USD")]:
        raw = request(100)
        raw["currency"] = currency
        raw["plan"]["assets"][0]["currency"] = currency
        raw["plan"]["goals"] = []
        raw["plan"]["budget_items"] = []
        raw["allocation"] = allocation(100, ())
        for segment in raw["allocation"]["segments"]:
            segment["currency"] = currency
        raw["joint_history"]["currency"] = currency
        raw["joint_history"]["asset_returns"] = {"A": [0.0] * 12}
        groups.append({"group_id": group_id, "request": raw})
    household = copy.deepcopy(groups[0]["request"]["plan"])
    household.update(assets=[], liabilities=[], goals=[], budget_items=[
        {"kind": "income", "label": "Salary", "monthly_amount": 1000},
        {"kind": "expense", "label": "Living", "monthly_amount": 500},
    ])
    return {
        "currency": "RUB", "household": household, "groups": groups,
        "fx": {"start_month": groups[0]["request"]["joint_history"]["start_month"],
               "opening_rates": {"RUB": 1.0, "USD": 100.0},
               "monthly_returns": {"USD": [0.0] * 12}},
        "contribution_schedule": [{"start_month": household["t0"],
                                   "weights": {"ruble": .5, "dollar": .5}}],
        "household_funding_order": ["ruble", "dollar"],
        "conversion_fee_rate": 0.0, "seed": 17, "mc_number": 10,
    }


def test_native_groups_and_common_budget_have_distinct_ownership() -> None:
    module = importlib.import_module("okama_planner.multicurrency")
    parsed = module.MulticurrencyRequest.model_validate(multicurrency_request())
    assert parsed.groups[1].request.currency == "USD"
    assert parsed.household.budget_items[0].monthly_amount == 1000


@pytest.mark.parametrize("change,match", [
    ("duplicate_currency", "currenc"), ("duplicate_income", "budget"),
    ("missing_fx", "FX"), ("invalid_fx", "positive"),
    ("bad_shares", "sum"), ("unaligned_history", "align"),
])
def test_invalid_currency_groups_fail_explicitly(change: str, match: str) -> None:
    raw = multicurrency_request()
    if change == "duplicate_currency":
        raw["groups"].append(copy.deepcopy(raw["groups"][1]))
        raw["groups"][-1]["group_id"] = "other"
    elif change == "duplicate_income":
        raw["groups"][1]["request"]["plan"]["budget_items"] = raw["household"]["budget_items"]
    elif change == "missing_fx":
        del raw["fx"]["monthly_returns"]["USD"]
    elif change == "invalid_fx":
        raw["fx"]["opening_rates"]["USD"] = 0
    elif change == "bad_shares":
        raw["contribution_schedule"][0]["weights"]["dollar"] = .6
    else:
        raw["fx"]["start_month"] = "2010-01"
    module = importlib.import_module("okama_planner.multicurrency")
    with pytest.raises(ValueError, match=match):
        module.MulticurrencyRequest.model_validate(raw)
