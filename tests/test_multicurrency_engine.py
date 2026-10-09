"""Hand-computed household and native currency financing scenarios."""

import importlib

import pytest

from test_multicurrency import multicurrency_request


def run(raw: dict) -> dict:
    from okama_planner.multicurrency import MulticurrencyRequest

    module = importlib.import_module("okama_planner.multicurrency_engine")
    return module.multicurrency_result(MulticurrencyRequest.model_validate(raw))


def monthly_budget(raw: dict, income: float, expense: float) -> None:
    for item, amount in zip(raw["household"]["budget_items"], (income, expense), strict=True):
        item.update(monthly_amount=amount, end_rule="until_month", end_month="2026-01")


def native(result: dict, group_id: str) -> dict:
    return next(g["result"] for g in result["currency_groups"] if g["group_id"] == group_id)


def test_one_household_budget_converts_1000_rubles_to_10_dollars() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 1000, 0)
    raw["contribution_schedule"][0]["weights"] = {"ruble": 0, "dollar": 1}
    result = run(raw)
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 110
    assert result["charts"]["portfolio"][-1]["p50"] == 11100
    assert result["actual"]["monthly_summaries"][1]["income_mean"] == 1000
    transfer = result["actual"]["fx_transfers"][0]
    assert transfer["native_amount_mean"] == 10
    assert transfer["base_amount_mean"] == 1000
    assert transfer["fx_rate_mean"] == 100


def test_conversion_fee_is_internal_and_conserves_household_money() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 1000, 0)
    raw["conversion_fee_rate"] = 0.1
    raw["contribution_schedule"][0]["weights"] = {"ruble": 0, "dollar": 1}
    result = run(raw)
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 109
    assert result["charts"]["capital"][-1]["p50"] == 11000
    assert result["actual"]["fx_transfers"][0]["fee_base_mean"] == 100


def test_household_shortage_withdraws_foreign_currency_with_fee() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 1000)
    raw["household_funding_order"] = ["dollar", "ruble"]
    raw["conversion_fee_rate"] = 0.1
    result = run(raw)
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == pytest.approx(100 - 1000 / 90)
    assert native(result, "ruble")["charts"]["portfolio"][-1]["p50"] == 100
    assert result["metrics"]["probability_of_success"] == 1
    row = result["actual"]["fx_transfers"][0]
    assert row["direction"] == "withdrawal"
    assert row["fee_base_mean"] == pytest.approx(1000 / 9)


def test_household_unmet_expenses_are_counted_once() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 20000)
    result = run(raw)
    assert result["metrics"]["unmet_mean"] == 9900
    assert result["metrics"]["probability_of_success"] == 0
    assert result["charts"]["portfolio"][-1]["p50"] == 0


def add_goal(raw: dict, index: int, goal_id: int, amount: float, **options: object) -> dict:
    from test_allocation import allocation

    group = raw["groups"][index]["request"]
    goal = {
        "goal_id": goal_id,
        "label": f"Goal {goal_id}",
        "kind": "lump",
        "amount_pv": amount,
        "pv_year": 2026,
        "target_year": 2026,
        **options,
    }
    group["plan"]["goals"].append(goal)
    group["allocation"] = allocation(100, tuple(g["goal_id"] for g in group["plan"]["goals"]))
    for segment in group["allocation"]["segments"]:
        segment["currency"] = group["currency"]
    return group


def test_native_modes_preserve_goal_isolation_and_no_cross_currency_rescue() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    group = add_goal(raw, 0, 1, 150)
    result = run(raw)
    assert result["goals"][0]["p_funded"] == 0
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 100
    assert native(result, "ruble")["charts"]["portfolio"][-1]["p50"] == 100
    group["plan"]["goals"][0]["amount_pv"] = 50
    group["allocation"]["transfer_policy"] = "none"
    group["allocation"]["transfer_order"] = []
    assert run(raw)["goals"][0]["p_funded"] == 0
    group["portfolio_mode"] = "single"
    pooled = run(raw)
    assert pooled["goals"][0]["p_funded"] == 1
    assert native(pooled, "ruble")["charts"]["portfolio"][-1]["p50"] == 50


def test_joint_success_and_aggregate_quantiles_use_identical_paths() -> None:
    import numpy as np

    from okama_planner.multicurrency import MulticurrencyRequest, sample_multicurrency

    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["mc_number"] = 100
    add_goal(raw, 0, 1, 120)
    add_goal(raw, 1, 2, 120)
    raw["groups"][0]["request"]["joint_history"]["asset_returns"]["A"] = [1, -0.5] * 6
    raw["groups"][1]["request"]["joint_history"]["asset_returns"]["A"] = [-0.5, 1] * 6
    result = run(raw)
    assert 0 < result["goals"][0]["p_funded"] < 1
    assert 0 < result["goals"][1]["p_funded"] < 1
    assert result["metrics"]["probability_of_success"] == 0
    for group in raw["groups"]:
        group["request"]["plan"]["goals"] = []
        group["request"]["allocation"]["goal_funders"] = []
        group["request"]["allocation"]["event_priority"] = ["expense", "mortgage_payment"]
        group["request"]["allocation"]["segments"] = group["request"]["allocation"]["segments"][:1]
        group["request"]["allocation"]["surplus_weights"][0]["weights"] = [
            {"segment_id": "household", "weight": 1}
        ]
        group["request"]["allocation"]["transfer_order"] = ["household"]
    raw["fx"]["monthly_returns"]["USD"] = [1, -0.5] * 6
    _, quotes, scenarios = sample_multicurrency(MulticurrencyRequest.model_validate(raw))
    rub = 100 * np.cumprod(1 + scenarios.returns[:, :, scenarios.assets.index("group/ruble/A")], axis=0)
    usd = 100 * np.cumprod(1 + scenarios.returns[:, :, scenarios.assets.index("group/dollar/A")], axis=0)
    expected = rub + usd * quotes["USD"][1:]
    result = run(raw)
    assert result["charts"]["portfolio"][-1]["p50"] == pytest.approx(np.percentile(expected[-1], 50))
    assert result["charts"]["portfolio"][1]["p50"] == pytest.approx(np.percentile(expected[0], 50))


def test_purchase_replacement_reserve_and_completion_conserve_native_capital() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    group = add_goal(raw, 1, 1, 80, becomes_asset=True, replaces_asset="Old asset")
    group["plan"]["assets"].append(
        {
            "label": "Old asset",
            "amount": 30,
            "currency": "USD",
            "asset_class": "non_working",
            "growth_rate": 0,
        }
    )
    add_goal(raw, 1, 2, 20, kind="reserve_topup")
    group["allocation"]["segments"][1]["completion"] = {"action": "transfer_to", "destination": "household"}
    result = native(run(raw), "dollar")
    last = result["actual"]["monthly_summaries"][-1]
    assert last["portfolio_mean"] == 30
    assert last["reserve_mean"] == 20
    assert last["non_working_mean"] == 80
    assert last["capital_mean"] == 130
    assert result["metrics"]["probability_of_success"] == 1


@pytest.mark.parametrize("replace", [False, True])
def test_expense_share_pension_uses_household_spending_and_scenario_quote(replace: bool) -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["household"]["budget_items"][1].update(monthly_amount=100, start_month="2027-01", end_month="2027-01")
    raw["household"]["pension_replaces_expenses"] = replace
    group = add_goal(raw, 1, 1, 0.5, kind="retirement_income", amount_basis="expense_share")
    group["plan"]["goals"][0].pop("target_year")
    group["plan"]["pension_replaces_expenses"] = True
    raw["fx"]["monthly_returns"]["USD"] = [1.0] * 12
    result = run(raw)
    goal = next(e for e in result["actual"]["event_funding"] if e["goal_id"] == 1)
    assert goal["month"] == "2027-01"
    assert goal["required_base_mean"] == 50
    assert goal["required_mean"] == pytest.approx(50 / (100 * 2**13))
    household = [
        e for e in result["actual"]["event_funding"] if e["kind"] == "expense" and e["month"] == "2027-01"
    ]
    assert len(household) == (0 if replace else 1)
    assert result["actual"]["monthly_summaries"][13]["expense_mean"] == (0 if replace else 100)


def test_native_loan_precedes_contributions_and_uses_common_cash_only_once() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 1000, 0)
    raw["contribution_schedule"][0]["weights"] = {"ruble": 1, "dollar": 0}
    raw["conversion_fee_rate"] = 0.1
    group = raw["groups"][1]["request"]
    group["plan"]["liabilities"] = [
        {
            "label": "Loan",
            "principal": 9,
            "annual_rate": 0,
            "monthly_payment": 9,
            "term_months": 1,
            "start_month": "2026-01",
        }
    ]
    result = run(raw)
    assert native(result, "ruble")["charts"]["portfolio"][-1]["p50"] == 100
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 100
    debt = next(e for e in result["actual"]["event_funding"] if e["kind"] == "mortgage_payment")
    assert debt["funded_mean"] == 9
    assert native(result, "dollar")["actual"]["monthly_summaries"][-1]["liability_mean"] == 0
    transfer = next(t for t in result["actual"]["fx_transfers"] if t["reason"] == "mortgage_payment")
    assert transfer["fee_base_mean"] == 100


def test_joint_success_keeps_native_failure_mask_when_fx_quote_is_tiny() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["fx"]["opening_rates"]["USD"] = 1e-12
    add_goal(raw, 1, 1, 150)
    result = run(raw)
    assert result["goals"][0]["p_funded"] == 0
    assert result["metrics"]["probability_of_success"] == 0


def test_dated_contributions_use_current_month_fx_not_opening_quote() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 1000, 0)
    raw["household"]["budget_items"][0]["end_month"] = "2026-02"
    raw["contribution_schedule"] = [
        {"start_month": "2026-01", "weights": {"ruble": 1, "dollar": 0}},
        {"start_month": "2026-02", "weights": {"ruble": 0, "dollar": 1}},
    ]
    raw["fx"]["monthly_returns"]["USD"] = [1] * 12
    result = run(raw)
    assert native(result, "ruble")["charts"]["portfolio"][-1]["p50"] == 1100
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 102.5
    dollar = next(t for t in result["actual"]["fx_transfers"] if t["group_id"] == "dollar")
    assert dollar["month"] == "2026-02"
    assert dollar["fx_rate_mean"] == 400


def test_native_debt_rescue_uses_other_groups_after_own_native_accounts() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["groups"][0]["request"]["plan"]["assets"][0]["amount"] = 1000
    raw["groups"][0]["request"]["allocation"]["segments"][0]["opening_amount"] = 1000
    group = raw["groups"][1]["request"]
    group["plan"]["liabilities"] = [
        {
            "label": "Loan",
            "principal": 109,
            "annual_rate": 0,
            "monthly_payment": 109,
            "term_months": 1,
            "start_month": "2026-01",
        }
    ]
    raw["conversion_fee_rate"] = 0.1
    result = run(raw)
    assert native(result, "ruble")["charts"]["portfolio"][-1]["p50"] == 0
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 0
    assert native(result, "dollar")["actual"]["monthly_summaries"][-1]["liability_mean"] == 0
    assert result["metrics"]["probability_of_success"] == 1


def test_native_pension_flag_does_not_suppress_common_expenses() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["household"]["budget_items"][1].update(monthly_amount=50, start_month="2027-01", end_month="2027-01")
    group = add_goal(raw, 1, 1, 1, kind="retirement_income")
    group["plan"]["goals"][0].pop("target_year")
    group["plan"]["pension_replaces_expenses"] = True
    result = run(raw)
    assert result["actual"]["monthly_summaries"][13]["expense_mean"] == 50
    assert native(result, "ruble")["charts"]["portfolio"][-1]["p50"] == 50
    assert native(result, "dollar")["charts"]["portfolio"][-1]["p50"] == 88


def test_effective_household_ledger_omits_pension_replaced_expenses() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["household"]["budget_items"][1].update(monthly_amount=100, start_month="2027-01", end_month="2027-01")
    raw["household"]["pension_replaces_expenses"] = True
    group = add_goal(raw, 1, 1, 0.5, kind="retirement_income", amount_basis="expense_share")
    group["plan"]["goals"][0].pop("target_year")
    group["plan"]["pension_replaces_expenses"] = True
    result = run(raw)
    assert not [
        line
        for line in result["household_ledger"]["lines"]
        if line["month"] == "2027-01" and line["line_kind"] == "expense"
    ]
    assert result["household_ledger"]["portfolio_flow"]["2027-01"] == 0
    dollar = native(result, "dollar")
    assert dollar["ledger_requirement_basis"] == "common_budget_expense_share_converted_per_path"
    assert dollar["goals"][0]["amount_nominal"] == 0.5


def test_native_result_discloses_original_input_and_coupled_fx_context() -> None:
    import json

    from okama_planner.api import ForecastRequest, _digest

    raw = multicurrency_request()
    monthly_budget(raw, 1000, 0)
    result = run(raw)
    dollar = native(result, "dollar")
    assert dollar["provenance"]["input_sha256"] == _digest(
        ForecastRequest.model_validate(raw["groups"][1]["request"]).model_dump(mode="json")
    )
    assert dollar["provenance"]["household_input_sha256"] == result["provenance"]["input_sha256"]
    assert dollar["actual"]["fx_transfers"][0]["native_amount_mean"] == 5
    assert dollar["actual"]["monthly_summaries"][1]["contribution_mean"] == 5
    assert json.loads(json.dumps(result, allow_nan=False))["schema_version"] == "2.0"


def test_share_pension_completes_when_household_expense_stream_ends() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 0, 0)
    raw["household"]["budget_items"][1].update(monthly_amount=100, start_month="2027-01", end_month="2027-01")
    raw["household"]["pension_replaces_expenses"] = True
    group = add_goal(raw, 1, 1, 1, kind="retirement_income", amount_basis="expense_share")
    group["plan"]["goals"][0].pop("target_year")
    group["plan"]["pension_replaces_expenses"] = True
    add_goal(raw, 1, 2, 50, target_year=2027, target_month=2)
    group["allocation"]["transfer_policy"] = "none"
    group["allocation"]["transfer_order"] = []
    group["allocation"]["segments"][0]["opening_amount"] = 0
    group["allocation"]["segments"][1]["opening_amount"] = 100
    group["allocation"]["segments"][1]["completion"] = {"action": "transfer_to", "destination": "g2"}
    result = native(run(raw), "dollar")
    pension_events = [e for e in result["actual"]["event_funding"] if e["goal_id"] == 1]
    assert [(e["month"], e["required_mean"]) for e in pension_events] == [("2027-01", 1)]
    assert result["actual"]["transfers"] == [
        {"month": "2027-01", "source": "g1", "destination": "g2", "reason": "completion", "amount_mean": 99}
    ]
    assert next(g for g in result["goals"] if g["goal_id"] == 2)["p_funded"] == 1


def test_share_pension_planned_buffer_uses_current_fx_for_future_base_requirements() -> None:
    raw = multicurrency_request()
    monthly_budget(raw, 2000, 0)
    raw["household"]["budget_items"][0].update(start_month="2026-12", end_month="2026-12")
    raw["household"]["budget_items"][1].update(monthly_amount=100, start_month="2027-01", end_month="2027-01")
    raw["household"]["pension_replaces_expenses"] = True
    raw["contribution_schedule"][0]["weights"] = {"ruble": 0, "dollar": 1}
    group = add_goal(raw, 1, 1, 1, kind="retirement_income", amount_basis="expense_share")
    group["plan"]["goals"][0].pop("target_year")
    group["plan"].update(
        pension_replaces_expenses=True, reserves_until_retirement=False, buffer_lookahead_months=1
    )
    group["allocation"]["buffer_policy"] = "planned_targets"
    raw["fx"]["monthly_returns"]["USD"] = [0.1, -0.1] * 6
    result = run(raw)
    december = native(result, "dollar")["actual"]["monthly_summaries"][12]
    import numpy as np

    from okama_planner.multicurrency import MulticurrencyRequest, sample_multicurrency

    _, quotes, _ = sample_multicurrency(MulticurrencyRequest.model_validate(raw))
    assert december["buffer_mean"] == pytest.approx(np.mean(100 / quotes["USD"][12]))
    assert december["buffer"]["p10"] != december["buffer"]["p90"]


def test_planned_share_pension_buffer_survives_subsequent_portfolio_loss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np

    import okama_planner.multicurrency_engine as engine
    from okama_planner.multicurrency import MulticurrencyRequest, sample_multicurrency
    from okama_planner.scenarios import JointScenarios

    raw = multicurrency_request()
    monthly_budget(raw, 100, 0)
    raw["household"]["budget_items"][0].update(start_month="2026-12", end_month="2026-12")
    raw["household"]["budget_items"][1].update(monthly_amount=100, start_month="2027-01", end_month="2027-01")
    raw["household"]["pension_replaces_expenses"] = True
    raw["contribution_schedule"][0]["weights"] = {"ruble": 0, "dollar": 1}
    group = add_goal(raw, 1, 1, 1, kind="retirement_income", amount_basis="expense_share")
    group["plan"]["goals"][0].pop("target_year")
    group["plan"].update(
        pension_replaces_expenses=True, reserves_until_retirement=False, buffer_lookahead_months=1
    )
    group["allocation"]["buffer_policy"] = "planned_targets"
    scenarios, quotes, common = sample_multicurrency(MulticurrencyRequest.model_validate(raw))
    dollar = scenarios["dollar"]
    returns = np.zeros_like(dollar.returns)
    returns[12] = -1
    scenarios["dollar"] = JointScenarios(dollar.assets, returns, dollar.row_indices, dollar.history_sha256)
    monkeypatch.setattr(engine, "sample_multicurrency", lambda request: (scenarios, quotes, common))
    result = native(run(raw), "dollar")
    assert result["actual"]["monthly_summaries"][12]["buffer_mean"] == 1
    assert result["charts"]["portfolio"][13]["p50"] == 0
    assert result["goals"][0]["p_full_stream"] == 1
    assert result["actual"]["event_funding"][0]["funding_sources"]["buffer"] == 1
