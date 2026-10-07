"""Compare a fictional family on one shared cube; optionally replay two supplied requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from okama_planner import compare_portfolio_modes, with_portfolio_mode
from okama_planner.reports import export_report


def synthetic_family() -> dict:
    """All amounts and histories are fictional USD assumptions, not market observations."""
    def strategy(growth: float, month: str = "2026-01") -> dict:
        return {"start_month": month, "weights": [
            {"asset": "Synthetic growth", "weight": growth},
            {"asset": "Synthetic defensive", "weight": 1.0 - growth},
        ]}

    ids = ["household", "home", "pension"]
    return {
        "currency": "USD", "mc_number": 500, "seed": 707, "portfolio_mode": "per_goal",
        "plan": {
            "t0": "2026-01", "horizon_years": 6, "retirement_year": 2029,
            "buffer_lookahead_months": 0, "pension_replaces_expenses": True,
            "rates": {"inflation_rate": 0.02, "expense_indexation_rate": 0.02,
                      "income_indexation_rate": 0.02, "goal_indexation_rate": 0.02,
                      "discount_rate": 0.02, "buffer_rate": 0.0},
            "persons": [{"name": "Synthetic adult 1", "birth_year": 1970, "role": "adult"},
                        {"name": "Synthetic adult 2", "birth_year": 1972, "role": "adult"},
                        {"name": "Synthetic child", "birth_year": 2012, "role": "child"}],
            "assets": [{"label": "Synthetic investments", "amount": 140000,
                        "currency": "USD", "asset_class": "portfolio"}],
            "liabilities": [],
            "budget_items": [
                {"kind": "income", "label": "Synthetic salary 1", "monthly_amount": 3000,
                 "end_rule": "until_retirement"},
                {"kind": "income", "label": "Synthetic salary 2", "monthly_amount": 1500,
                 "end_rule": "until_retirement"},
                {"kind": "expense", "label": "Synthetic family living", "monthly_amount": 3000},
            ],
            "goals": [
                {"goal_id": 1, "label": "Synthetic home", "kind": "lump", "amount_pv": 100000,
                 "pv_year": 2026, "target_year": 2028, "target_month": 7, "becomes_asset": True},
                {"goal_id": 2, "label": "Synthetic pension", "kind": "retirement_income",
                 "amount_pv": 3000, "pv_year": 2026},
            ],
        },
        "joint_history": {
            "currency": "USD", "start_month": "2020-01", "method": "synchronized_bootstrap",
            "asset_returns": {
                "Synthetic growth": [0.035, -0.04, 0.02, 0.01, -0.025, 0.03,
                                     0.015, -0.01, 0.025, 0.005, -0.03, 0.045] * 3,
                "Synthetic defensive": [0.002, 0.003, 0.001, 0.002, 0.001, 0.002,
                                        0.003, 0.001, 0.002, 0.002, 0.001, 0.002] * 3,
            },
        },
        "allocation": {
            "segments": [
                {"segment_id": key, "goal_id": goal, "opening_amount": amount, "currency": "USD",
                 "strategy": steps, "completion": completion}
                for key, goal, amount, steps, completion in [
                    ("household", None, 0, [strategy(0.0)], {"action": "retain"}),
                    ("home", 1, 70000, [strategy(0.0)],
                     {"action": "transfer_to", "destination": "pension"}),
                    ("pension", 2, 70000, [strategy(1.0), strategy(0.5, "2029-01")],
                     {"action": "retain"}),
                ]
            ],
            "single_strategy": [strategy(0.7), strategy(0.4, "2029-01")],
            "surplus_weights": [
                {"start_month": month, "weights": [
                    {"segment_id": key, "weight": weight} for key, weight in zip(ids, weights, strict=True)
                ]} for month, weights in [("2026-01", [0.0, 0.7, 0.3]), ("2028-08", [0.0, 0.0, 1.0])]
            ],
            "household_segment_id": "household",
            "goal_funders": [{"goal_id": 1, "segment_id": "home"},
                             {"goal_id": 2, "segment_id": "pension"}],
            "event_priority": ["expense", "mortgage_payment", "goal:1", "goal:2"],
            "funding_source_order": ["cash", "buffer", "segment"],
            "reserve_funding_source_order": ["cash", "segment"],
            "transfer_policy": "ordered", "transfer_order": ["household", "home", "pension"],
            "buffer_policy": "retain", "purchase_execution": "all_or_nothing",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--single-request", type=Path)
    parser.add_argument("--per-goal-request", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "tmp" / "portfolio-modes")
    args = parser.parse_args()
    if bool(args.single_request) != bool(args.per_goal_request):
        parser.error("Supply --single-request and --per-goal-request together")
    if args.single_request:
        single = json.loads(args.single_request.read_text())
        per_goal = json.loads(args.per_goal_request.read_text())
    else:
        per_goal = synthetic_family()
        single = with_portfolio_mode(per_goal, portfolio_mode="single").model_dump(mode="json")
    comparison = compare_portfolio_modes(single, per_goal)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [("single-request", single), ("per-goal-request", per_goal),
                        ("single-result", comparison["baseline"]),
                        ("per-goal-result", comparison["variant"]), ("comparison", comparison)]:
        (args.output_dir / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    export_report([
        {"label": "Single pooled", "request": single, "result": comparison["baseline"]},
        {"label": "Goal portfolios", "request": per_goal, "result": comparison["variant"]},
    ], args.output_dir / "portfolio-modes.xlsx")
    print("Comparison JSON and workbook saved in the selected output directory.")


if __name__ == "__main__":
    main()
