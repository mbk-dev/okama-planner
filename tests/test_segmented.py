"""Actual source-event funding must conserve assets and never buy on credit implicitly."""

import numpy as np
import pytest

from okama_planner import ForecastRequest, forecast
from okama_planner.scenarios import sample_joint_returns
from test_allocation import allocation, request, strategy


def simulate(raw: dict):
    from okama_planner.segmented import simulate_segments

    value = ForecastRequest.model_validate(raw)
    cube = sample_joint_returns(value.joint_history, months=24, paths=value.mc_number, seed=value.seed)
    return simulate_segments(value, cube)


@pytest.mark.parametrize(
    ("side", "portfolio", "buffer", "reserve", "capital"),
    [(False, 160, 0, 10, 250), (True, 190, 20, 110, 400)],
)
def test_hand_computed_source_events_no_double_count(side, portfolio, buffer, reserve, capital) -> None:
    result = simulate(request(side=side))
    np.testing.assert_allclose(result.portfolio[1], portfolio)
    np.testing.assert_allclose(result.buffer[1], buffer)
    np.testing.assert_allclose(result.reserve[1], reserve)
    np.testing.assert_allclose(result.non_working[1], 80)
    np.testing.assert_allclose(result.capital[1], capital)
    assert len(result.events) == 4  # living, two purchases, reserve; not portfolio_flow/buffer bookkeeping
    assert all(np.all(event.unmet == 0) for event in result.events)


def test_unfunded_indivisible_purchase_creates_no_asset_and_keeps_cash() -> None:
    raw = request(0)
    raw["plan"]["budget_items"][0]["monthly_amount"] = 100
    result = simulate(raw)
    bought = next(x for x in result.events if x.goal_id == 1)
    np.testing.assert_allclose(bought.funded, 0)
    np.testing.assert_allclose(bought.unmet, 80)
    np.testing.assert_allclose(result.non_working[1], 0)
    np.testing.assert_allclose(result.reserve[1], 10)
    np.testing.assert_allclose(result.portfolio[1], 40)


def test_reserve_balance_only_contains_actual_funded_topup() -> None:
    raw = request(0, side=True)
    result = simulate(raw)
    np.testing.assert_allclose(result.reserve[1], 100)
    np.testing.assert_allclose(result.non_working[1], 80)
    assert np.all(next(x for x in result.events if x.goal_id == 3).unmet == 10)


@pytest.mark.parametrize(
    ("opening", "bought", "property_value", "portfolio"), [(0, False, 40, 0), (50, True, 80, 10)]
)
def test_replacement_sale_is_atomic_with_funded_purchase(opening, bought, property_value, portfolio) -> None:
    raw = request(opening)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [raw["plan"]["goals"][0]]
    raw["plan"]["goals"][0]["replaces_asset"] = "Old asset"
    raw["plan"]["assets"].append(
        {
            "label": "Old asset",
            "amount": 40,
            "currency": "USD",
            "asset_class": "non_working",
            "growth_rate": 0,
        }
    )
    raw["allocation"] = allocation(opening, (1,))
    result = simulate(raw)
    np.testing.assert_allclose(result.non_working[1], property_value)
    np.testing.assert_allclose(result.portfolio[1], portfolio)
    np.testing.assert_allclose(result.events[0].funded, 80 if bought else 0)


def test_transfers_conserve_total_and_respect_none_policy() -> None:
    raw = request(100)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [raw["plan"]["goals"][0]]
    raw["allocation"] = allocation(100, (1,))
    funded = simulate(raw)
    np.testing.assert_allclose(funded.portfolio[1], 20)
    np.testing.assert_allclose(funded.transfers[0].amount, 80)
    assert funded.transfers[0].source == "household" and funded.transfers[0].destination == "g1"
    raw["allocation"]["transfer_policy"] = "none"
    raw["allocation"]["transfer_order"] = []
    isolated = simulate(raw)
    np.testing.assert_allclose(isolated.portfolio[1], 100)
    np.testing.assert_allclose(isolated.events[0].unmet, 80)


def test_completed_segment_transfers_remainder_once_and_redirects_later_surplus() -> None:
    raw = request(200)
    raw["plan"]["budget_items"] = [raw["plan"]["budget_items"][0]]
    raw["plan"]["budget_items"][0]["end_month"] = "2026-02"
    raw["plan"]["goals"] = [raw["plan"]["goals"][0]]
    raw["allocation"] = allocation(200, (1,))
    raw["allocation"]["segments"][0]["opening_amount"] = 0
    raw["allocation"]["segments"][1]["opening_amount"] = 200
    raw["allocation"]["segments"][1]["completion"] = {"action": "transfer_to", "destination": "household"}
    raw["allocation"]["surplus_weights"][0]["weights"] = [{"segment_id": "g1", "weight": 1}]
    result = simulate(raw)
    np.testing.assert_allclose(result.segment_balances[1, :, 1], 0)
    np.testing.assert_allclose(result.segment_balances[1, :, 0], 220)
    np.testing.assert_allclose(result.segment_balances[2, :, 0], 320)
    assert len([x for x in result.transfers if x.reason == "completion"]) == 1


def test_unpaid_mortgage_keeps_principal_and_accrues_interest() -> None:
    raw = request(0)
    raw["plan"]["goals"] = []
    raw["plan"]["budget_items"] = []
    raw["allocation"] = allocation(0, ())
    raw["plan"]["liabilities"] = [
        {
            "label": "Loan",
            "principal": 100,
            "annual_rate": 0.12,
            "monthly_payment": 20,
            "term_months": 5,
            "start_month": "2026-01",
        }
    ]
    result = simulate(raw)
    np.testing.assert_allclose(result.liability[0], 100)
    np.testing.assert_allclose(result.liability[1], 101)
    np.testing.assert_allclose(result.liability[2], 102.01)
    assert len(result.events) == 24  # payment remains due after the planned payoff
    np.testing.assert_allclose(result.capital[1], -101)


def test_pension_goal_success_covers_full_stream_not_only_first_month() -> None:
    raw = request(100)
    raw["plan"]["goals"] = [
        {"goal_id": 1, "label": "Pension", "kind": "retirement_income", "amount_pv": 20, "pv_year": 2026}
    ]
    raw["plan"]["budget_items"] = []
    raw["allocation"] = allocation(100, (1,))
    result = forecast(raw)
    assert result["goals"][0]["p_funded"] == 0
    assert result["goals"][0]["p_full_stream"] == 0
    assert result["goals"][0]["unmet_mean"] == 140
    assert result["metrics"]["probability_of_success"] == 0


def test_dated_strategy_changes_exact_month_before_flows() -> None:
    raw = request(100)
    raw["plan"]["goals"] = []
    raw["plan"]["budget_items"] = []
    raw["allocation"] = allocation(100, ())
    raw["joint_history"]["asset_returns"] = {"A": [0.1] * 12, "B": [0] * 12}
    raw["allocation"]["segments"][0]["strategy"] = strategy() + strategy("B", "2026-02")
    result = simulate(raw)
    np.testing.assert_allclose(result.portfolio[0], 100)
    np.testing.assert_allclose(result.portfolio[1], 110)
    np.testing.assert_allclose(result.portfolio[2], 110)


def test_replacement_funding_sources_sum_to_paid_amount_not_sale_plus_cash_twice() -> None:
    raw = request(50)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [raw["plan"]["goals"][0]]
    raw["plan"]["goals"][0]["replaces_asset"] = "Old asset"
    raw["plan"]["assets"].append(
        {
            "label": "Old asset",
            "amount": 40,
            "currency": "USD",
            "asset_class": "non_working",
            "growth_rate": 0,
        }
    )
    raw["allocation"] = allocation(50, (1,))
    event = simulate(raw).events[0]
    np.testing.assert_allclose(sum(event.funding_sources.values()), 80)
    np.testing.assert_allclose(event.funding_sources["asset_sale:Old asset"], 40)
    np.testing.assert_allclose(event.funding_sources["cash"], 0)


def test_planned_buffer_targets_are_only_funded_from_actual_cash_and_released() -> None:
    raw = request(0)
    raw["plan"]["goals"] = []
    raw["plan"]["budget_items"] = [
        {
            "kind": "income",
            "label": "Salary",
            "monthly_amount": 5,
            "end_rule": "until_month",
            "end_month": "2026-01",
        },
        {
            "kind": "expense",
            "label": "Future need",
            "monthly_amount": 10,
            "start_month": "2026-02",
            "end_rule": "until_month",
            "end_month": "2026-02",
        },
    ]
    raw["plan"]["buffer_lookahead_months"] = 1
    raw["allocation"] = allocation(0, ())
    raw["allocation"]["buffer_policy"] = "planned_targets"
    result = simulate(raw)
    np.testing.assert_allclose(result.buffer[1], 5)
    np.testing.assert_allclose(result.portfolio[1], 0)
    np.testing.assert_allclose(result.events[0].funded, 5)
    np.testing.assert_allclose(result.events[0].unmet, 5)
    np.testing.assert_allclose(result.buffer[2], 0)


def test_existing_loan_opening_balance_accounts_for_payments_before_t0() -> None:
    raw = request(200)
    raw["plan"]["goals"] = []
    raw["plan"]["budget_items"] = []
    raw["allocation"] = allocation(200, ())
    raw["plan"]["liabilities"] = [
        {
            "label": "Existing loan",
            "principal": 100,
            "annual_rate": 0,
            "monthly_payment": 20,
            "term_months": 5,
            "start_month": "2025-11",
        }
    ]
    result = simulate(raw)
    np.testing.assert_allclose(result.liability[0], 60)
    np.testing.assert_allclose(result.liability[1], 40)
    np.testing.assert_allclose(result.portfolio[1], 180)
    np.testing.assert_allclose(result.capital[1], 140)


def test_completion_chain_redirects_surplus_to_final_active_destination() -> None:
    raw = request(200)
    raw["plan"]["goals"] = raw["plan"]["goals"][:2]
    raw["plan"]["budget_items"] = [raw["plan"]["budget_items"][0]]
    raw["plan"]["budget_items"][0]["end_month"] = "2026-02"
    raw["allocation"] = allocation(200, (1, 2))
    raw["allocation"]["segments"][0]["opening_amount"] = 0
    raw["allocation"]["segments"][1]["opening_amount"] = 100
    raw["allocation"]["segments"][2]["opening_amount"] = 100
    raw["allocation"]["segments"][1]["completion"] = {"action": "transfer_to", "destination": "g2"}
    raw["allocation"]["segments"][2]["completion"] = {"action": "transfer_to", "destination": "household"}
    raw["allocation"]["event_priority"] = ["expense", "mortgage_payment", "goal:2", "goal:1"]
    raw["allocation"]["surplus_weights"][0]["weights"] = [{"segment_id": "g1", "weight": 1}]
    result = simulate(raw)
    np.testing.assert_allclose(result.segment_balances[1, :, 0], 200)
    np.testing.assert_allclose(result.segment_balances[2, :, 0], 300)
    np.testing.assert_allclose(result.segment_balances[2, :, 1:], 0)


def test_nonfinite_actual_states_fail_explicitly() -> None:
    raw = request(200)
    raw["joint_history"]["asset_returns"]["A"] = [1e200] * 12
    with pytest.raises(ValueError, match="finite"):
        simulate(raw)


def test_same_label_properties_and_acquired_names_are_not_lost() -> None:
    raw = request(100)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [raw["plan"]["goals"][0]]
    raw["allocation"] = allocation(100, (1,))
    raw["plan"]["assets"] += [
        {
            "label": "acquired:1",
            "amount": 10,
            "currency": "USD",
            "asset_class": "non_working",
            "growth_rate": 0,
        },
        {
            "label": "acquired:1",
            "amount": 15,
            "currency": "USD",
            "asset_class": "non_working",
            "growth_rate": 0,
        },
    ]
    result = simulate(raw)
    np.testing.assert_allclose(result.non_working[0], 25)
    np.testing.assert_allclose(result.non_working[1], 105)
    np.testing.assert_allclose(result.capital[1], 125)


def test_pension_completion_after_last_required_event_redirects_later_surplus() -> None:
    raw = request(100)
    raw["plan"]["pension_replaces_expenses"] = True
    raw["plan"]["goals"] = [
        {
            "goal_id": 1,
            "kind": "retirement_income",
            "label": "Pension",
            "amount_basis": "expense_share",
            "amount_pv": 1,
            "pv_year": 2026,
        }
    ]
    raw["plan"]["budget_items"] = [
        {
            "kind": "expense",
            "label": "Need",
            "monthly_amount": 10,
            "start_month": "2027-01",
            "end_rule": "until_month",
            "end_month": "2027-01",
        },
        {
            "kind": "income",
            "label": "Later surplus",
            "monthly_amount": 20,
            "start_month": "2027-02",
            "end_rule": "until_month",
            "end_month": "2027-02",
        },
    ]
    raw["allocation"] = allocation(100, (1,))
    raw["allocation"]["segments"][0]["opening_amount"] = 0
    raw["allocation"]["segments"][1]["opening_amount"] = 100
    raw["allocation"]["segments"][1]["completion"] = {"action": "transfer_to", "destination": "household"}
    raw["allocation"]["surplus_weights"][0]["weights"] = [{"segment_id": "g1", "weight": 1}]
    result = simulate(raw)
    np.testing.assert_allclose(result.segment_balances[13, :, 1], 0)
    np.testing.assert_allclose(result.segment_balances[13, :, 0], 90)
    np.testing.assert_allclose(result.segment_balances[14, :, 0], 110)
    assert len([t for t in result.transfers if t.reason == "completion"]) == 1
