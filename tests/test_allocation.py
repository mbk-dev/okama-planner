"""Explicit allocation policies must be complete and reject silent money changes."""

import copy

import pytest

from okama_planner import ForecastRequest
from okama_planner.inputs import AssetIn, BudgetItemIn, GoalIn, PlanInputs, Rates


def strategy(asset: str = "A", month: str = "2026-01") -> list[dict]:
    return [{"start_month": month, "weights": [{"asset": asset, "weight": 1.0}]}]


def allocation(opening: float = 200, goals: tuple[int, ...] = (1, 2, 3)) -> dict:
    ids = ["household", *(f"g{i}" for i in goals)]
    return {
        "segments": [
            {
                "segment_id": key,
                "goal_id": None if key == "household" else int(key[1:]),
                "opening_amount": opening if key == "household" else 0,
                "currency": "USD",
                "strategy": strategy(),
                "completion": {"action": "retain"},
            }
            for key in ids
        ],
        "single_strategy": strategy(),
        "surplus_weights": [
            {
                "start_month": "2026-01",
                "weights": [{"segment_id": key, "weight": 1.0 if key == "household" else 0} for key in ids],
            }
        ],
        "household_segment_id": "household",
        "goal_funders": [{"goal_id": i, "segment_id": f"g{i}"} for i in goals],
        "event_priority": ["expense", "mortgage_payment", *(f"goal:{i}" for i in goals)],
        "funding_source_order": ["cash", "buffer", "segment"],
        "reserve_funding_source_order": ["cash", "segment"],
        "transfer_policy": "unrestricted",
        "transfer_order": ids,
        "buffer_policy": "retain",
        "purchase_execution": "all_or_nothing",
    }


def request(opening: float = 200, side: bool = False) -> dict:
    assets = [AssetIn(label="Capital", amount=opening, currency="USD", asset_class="portfolio")]
    if side:
        assets += [
            AssetIn(label="Buffer", amount=50, currency="USD", asset_class="savings"),
            AssetIn(label="Reserve", amount=100, currency="USD", asset_class="reserve", growth_rate=0),
        ]
    plan = PlanInputs(
        t0="2026-01",
        horizon_years=2,
        retirement_year=2027,
        buffer_lookahead_months=0,
        rates=Rates(
            **dict.fromkeys(
                [
                    "inflation_rate",
                    "expense_indexation_rate",
                    "income_indexation_rate",
                    "goal_indexation_rate",
                    "discount_rate",
                    "buffer_rate",
                ],
                0,
            )
        ),
        assets=tuple(assets),
        budget_items=(
            BudgetItemIn(
                kind="income", label="Salary", monthly_amount=100, end_rule="until_month", end_month="2026-01"
            ),
            BudgetItemIn(
                kind="expense", label="Living", monthly_amount=30, end_rule="until_month", end_month="2026-01"
            ),
        ),
        goals=(
            GoalIn(
                goal_id=1,
                label="Asset",
                kind="lump",
                amount_pv=80,
                pv_year=2026,
                target_year=2026,
                becomes_asset=True,
            ),
            GoalIn(goal_id=2, label="Consumption", kind="lump", amount_pv=20, pv_year=2026, target_year=2026),
            GoalIn(
                goal_id=3,
                label="Reserve target",
                kind="reserve_topup",
                amount_pv=110 if side else 10,
                pv_year=2026,
                target_year=2026,
            ),
        ),
    )
    return {
        "plan": plan.model_dump(mode="json"),
        "currency": "USD",
        "mc_number": 4,
        "seed": 7,
        "portfolio_mode": "per_goal",
        "joint_history": {
            "start_month": "2020-01",
            "currency": "USD",
            "method": "synchronized_bootstrap",
            "asset_returns": {"A": [0.0] * 12, "B": [0.0] * 12},
        },
        "allocation": allocation(opening),
    }


def test_new_request_validates_and_deeply_freezes_explicit_schedules() -> None:
    raw = request()
    value = ForecastRequest.model_validate(raw)
    raw["allocation"]["segments"][0]["strategy"][0]["weights"][0]["weight"] = 0.1
    assert value.allocation.segments[0].strategy[0].weights[0].weight == 1
    with pytest.raises(ValueError):
        value.allocation.segments[0].opening_amount = 0


@pytest.mark.parametrize(
    "field",
    [
        "single_strategy",
        "event_priority",
        "goal_funders",
        "transfer_policy",
        "transfer_order",
        "funding_source_order",
        "buffer_policy",
        "purchase_execution",
        "surplus_weights",
    ],
)
def test_missing_policy_is_rejected(field: str) -> None:
    raw = request()
    del raw["allocation"][field]
    with pytest.raises(ValueError):
        ForecastRequest.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    [
        "opening",
        "currency",
        "weights",
        "unknown_asset",
        "unknown_segment",
        "goal_funder",
        "null_goal",
        "duplicate_segment",
        "completion",
        "priority",
        "schedule",
        "savings",
        "holdings",
        "sample",
        "rebalancing",
        "future_history",
    ],
)
def test_inconsistent_allocation_is_rejected(change: str) -> None:
    raw = request()
    alloc = raw["allocation"]
    updates = {
        "opening": (alloc["segments"][0], "opening_amount", 201),
        "currency": (alloc["segments"][0], "currency", "EUR"),
        "weights": (alloc["single_strategy"][0]["weights"][0], "weight", 0.99),
        "unknown_asset": (alloc, "single_strategy", strategy("Missing")),
        "unknown_segment": (alloc["surplus_weights"][0]["weights"][0], "segment_id", "missing"),
        "goal_funder": (alloc["goal_funders"][0], "segment_id", "g2"),
        "null_goal": (raw["plan"]["goals"][0], "goal_id", None),
        "duplicate_segment": (alloc, "segments", alloc["segments"] + [copy.deepcopy(alloc["segments"][0])]),
        "completion": (
            alloc["segments"][1],
            "completion",
            {"action": "transfer_to", "destination": "missing"},
        ),
        "priority": (alloc, "event_priority", alloc["event_priority"][:-1]),
        "schedule": (alloc, "single_strategy", strategy(month="2026-02")),
        "savings": (raw["plan"], "savings_mode", "separate"),
        "holdings": (raw["plan"], "accumulation_holdings", [{"symbol": "A", "weight": 1}]),
        "sample": (
            raw,
            "return_samples",
            {
                k: {"start_month": "2020-01", "monthly_returns": [0] * 12}
                for k in ("accumulation", "withdrawal")
            },
        ),
        "rebalancing": (raw["plan"]["accumulation_rebalancing"], "period", "year"),
        "future_history": (raw["joint_history"], "start_month", "2026-01"),
    }
    target, field, value = updates[change]
    target[field] = value
    with pytest.raises(ValueError):
        ForecastRequest.model_validate(raw)


def test_zero_opening_allowed_for_joint_but_legacy_requires_capital() -> None:
    ForecastRequest.model_validate(request(0))
    raw = request(0)
    for field in ("joint_history", "allocation", "portfolio_mode"):
        raw.pop(field)
    with pytest.raises(ValueError, match="positive opening"):
        ForecastRequest.model_validate(raw)


@pytest.mark.parametrize("field", ["distribution", "match_moments"])
def test_joint_history_rejects_explicit_legacy_market_knobs(field: str) -> None:
    raw = request()
    raw[field] = "norm" if field == "distribution" else True
    with pytest.raises(ValueError, match="legacy"):
        ForecastRequest.model_validate(raw)


def test_future_loans_require_disbursement_contract() -> None:
    raw = request()
    raw["plan"]["liabilities"] = [
        {
            "label": "Future loan",
            "principal": 100,
            "annual_rate": 0,
            "monthly_payment": 20,
            "term_months": 5,
            "start_month": "2026-02",
        }
    ]
    with pytest.raises(ValueError, match="future loans"):
        ForecastRequest.model_validate(raw)


@pytest.mark.parametrize(
    "change",
    [
        "cycle",
        "duplicate_weight",
        "duplicate_surplus",
        "unknown_goal",
        "nan",
        "missing_reserve_policy",
        "duplicate_sources",
        "bool_amount",
    ],
)
def test_new_policy_corner_cases_are_rejected(change: str) -> None:
    raw = request()
    alloc = raw["allocation"]
    if change == "cycle":
        alloc["segments"][1]["completion"] = {"action": "transfer_to", "destination": "g2"}
        alloc["segments"][2]["completion"] = {"action": "transfer_to", "destination": "g1"}
    if change == "duplicate_weight":
        alloc["single_strategy"][0]["weights"] = [{"asset": "A", "weight": 0.5}] * 2
    if change == "duplicate_surplus":
        alloc["surplus_weights"].append(copy.deepcopy(alloc["surplus_weights"][0]))
    if change == "unknown_goal":
        raw["plan"]["goals"][0]["goal_id"] = 20
    if change == "nan":
        alloc["segments"][0]["opening_amount"] = float("nan")
    if change == "missing_reserve_policy":
        del alloc["reserve_funding_source_order"]
    if change == "duplicate_sources":
        alloc["reserve_funding_source_order"] = ["cash", "cash"]
    if change == "bool_amount":
        alloc["segments"][1]["opening_amount"] = False
    with pytest.raises(ValueError):
        ForecastRequest.model_validate(raw)
