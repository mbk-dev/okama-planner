"""A fictional RUB/USD/EUR family with a common budget and joint synthetic histories."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from okama_planner import MulticurrencyRequest, forecast
from okama_planner.charts import export_charts
from okama_planner.reports import export_report
from portfolio_modes import synthetic_family


def synthetic_multicurrency() -> dict:
    """Illustrate mechanics, not market assumptions or investment recommendations."""
    template = synthetic_family()
    household = copy.deepcopy(template["plan"])
    household.update(assets=[], goals=[], liabilities=[])
    for item in household["budget_items"]:
        item["monthly_amount"] *= 100
    groups = []
    definitions = [
        (
            "ruble",
            "RUB",
            14000000,
            "single",
            [
                {
                    "goal_id": 1,
                    "label": "Synthetic pension",
                    "kind": "retirement_income",
                    "amount_pv": 1,
                    "amount_basis": "expense_share",
                    "pv_year": 2026,
                },
            ],
        ),
        (
            "dollar",
            "USD",
            200000,
            "single",
            [
                {
                    "goal_id": 2,
                    "label": "Synthetic property",
                    "kind": "lump",
                    "amount_pv": 100000,
                    "pv_year": 2026,
                    "target_year": 2028,
                    "target_month": 7,
                    "becomes_asset": True,
                },
            ],
        ),
        (
            "euro",
            "EUR",
            100000,
            "per_goal",
            [
                {
                    "goal_id": 3,
                    "label": "Synthetic education",
                    "kind": "lump",
                    "amount_pv": 20000,
                    "pv_year": 2026,
                    "target_year": 2027,
                },
                {
                    "goal_id": 4,
                    "label": "Synthetic second education",
                    "kind": "lump",
                    "amount_pv": 25000,
                    "pv_year": 2026,
                    "target_year": 2028,
                },
            ],
        ),
    ]
    for key, currency, opening, mode, goals in definitions:
        native = copy.deepcopy(template)
        native.update(currency=currency, portfolio_mode=mode)
        native["plan"].update(
            budget_items=[],
            persons=[],
            goals=goals,
            assets=[
                {
                    "label": "Synthetic investments",
                    "amount": opening,
                    "currency": currency,
                    "asset_class": "portfolio",
                }
            ],
        )
        native["joint_history"]["currency"] = currency
        allocation = native["allocation"]
        strategy = copy.deepcopy(allocation["single_strategy"])
        ids = ["household", *[f"goal-{g['goal_id']}" for g in goals]]
        allocation.update(
            segments=[
                {
                    "segment_id": segment,
                    "goal_id": None if n == 0 else goals[n - 1]["goal_id"],
                    "opening_amount": 0 if n == 0 else opening / len(goals),
                    "currency": currency,
                    "strategy": strategy,
                    "completion": {"action": "retain"},
                }
                for n, segment in enumerate(ids)
            ],
            surplus_weights=[
                {
                    "start_month": household["t0"],
                    "weights": [
                        {"segment_id": segment, "weight": 0 if n == 0 else 1 / len(goals)}
                        for n, segment in enumerate(ids)
                    ],
                }
            ],
            goal_funders=[{"goal_id": g["goal_id"], "segment_id": f"goal-{g['goal_id']}"} for g in goals],
            event_priority=["expense", "mortgage_payment", *[f"goal:{g['goal_id']}" for g in goals]],
            transfer_order=ids,
        )
        groups.append({"group_id": key, "request": native})
    return {
        "currency": "RUB",
        "household": household,
        "groups": groups,
        "fx": {
            "start_month": "2020-01",
            "opening_rates": {"RUB": 1, "USD": 100, "EUR": 110},
            "monthly_returns": {
                "USD": [-0.01, 0.02, -0.005, 0.01, 0.015, -0.01, 0.005, 0.01, -0.01, 0.005, 0.02, -0.01] * 3,
                "EUR": [-0.005, 0.015, -0.01, 0.005, 0.01, -0.005, 0.01, 0.015, -0.005, 0.0, 0.015, -0.005]
                * 3,
            },
        },
        "contribution_schedule": [
            {"start_month": "2026-01", "weights": {"ruble": 0.2, "dollar": 0.4, "euro": 0.4}}
        ],
        "household_funding_order": ["ruble", "dollar", "euro"],
        "conversion_fee_rate": 0.002,
        "seed": 714,
        "mc_number": 500,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "tmp" / "multicurrency")
    parser.add_argument("--images", action="store_true", help="Also create PNG/SVG and embed PNG in Excel")
    args = parser.parse_args()
    request = MulticurrencyRequest.model_validate(synthetic_multicurrency())
    result = forecast(request)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, value in [("request", request.model_dump(mode="json")), ("result", result)]:
        (args.output_dir / f"{name}.json").write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    export_charts(result, args.output_dir)
    images = {}
    if args.images:
        for image_format in ("png", "svg"):
            export_charts(result, args.output_dir, format=image_format)
            log_paths = export_charts(result, args.output_dir / "log", format=image_format, logarithmic=True)
            for path in log_paths:
                relative = path.relative_to(args.output_dir / "log")
                target = args.output_dir / relative.parent / f"{path.stem}_log{path.suffix}"
                path.replace(target)
        for group in [None, *result["currency_groups"]]:
            prefix = "" if group is None else f"{group['group_id']}/"
            for key in ["portfolio", "capital", "portfolio_log", "capital_log"]:
                images[prefix + key] = args.output_dir / f"{prefix}{key}.png"
    export_report(
        [
            {
                "label": "Synthetic multicurrency family",
                "request": request.model_dump(mode="json"),
                "result": result,
            }
        ],
        args.output_dir / "multicurrency.xlsx",
        chart_images=images,
    )
    print(f"Joint success probability: {result['metrics']['probability_of_success']:.2%}")
    print(f"Reports saved to {args.output_dir}")


if __name__ == "__main__":
    main()
