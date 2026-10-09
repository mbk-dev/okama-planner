"""Create complete synthetic national-currency editions with independent success validation."""

import argparse
import json
import math
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font

from okama_planner import forecast
from okama_planner.charts import export_charts
from okama_planner.localization import LANGUAGES, translate
from okama_planner.reports import ReportBrand, export_report

DEFAULT_CURRENCIES = {"en": "USD", "ru": "RUB", "zh": "CNY", "de": "EUR", "es": "EUR"}
# Fictional amounts: opening, income, expenses, reserve, apartment, car, savings,
# loan, payment, car goal, home goal. No client amounts or FX conversions.
SYNTHETIC_AMOUNTS = {
    "USD": (100000, 15000, 5000, 100000, 180000, 60000, 10000, 25000, 300, 130000, 400000),
    "EUR": (90000, 12000, 4000, 80000, 160000, 50000, 9000, 20000, 250, 110000, 350000),
    "CNY": (750000, 100000, 35000, 700000, 1200000, 400000, 70000, 180000, 2200, 950000, 2800000),
    "RUB": (11000000, 1400000, 480000, 10000000, 19000000, 6000000, 900000,
            2600000, 32000, 14000000, 42000000),
}


def build_request(
    currency: str, snapshots: dict[str, Any], *, language: str = "en",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Author a complete fictional household using offline base-currency return samples."""
    metadata = deepcopy(snapshots["currencies"][currency])
    if metadata["risk_free_rate"] is None:
        raise ValueError(f"{currency} policy rate requires an explicit dated reference in the snapshot")
    request = json.loads((Path(__file__).parent / "baseline-request.json").read_text())
    opening, income, expenses, reserve, apartment, car, savings, loan, payment, car_goal, home_goal = (
        SYNTHETIC_AMOUNTS[currency]
    )
    metadata["amount_method"] = (
        "Independently authored synthetic amounts; no FX conversion; not a client plan"
    )
    metadata["savings_method"] = (
        "Separate car/home savings accounts at the dated reference rate; this public adaptation "
        "does not reproduce a private custom bond-purchase/reserve policy."
    )
    metadata["portfolio_method"] = (
        "Same USD asset mix in every currency, with historical returns measured in the plan currency. "
        "Currency exposure is unhedged; this is not a reproduction of a domestic RUB portfolio."
    )
    request.update(currency=currency, seed=707, mc_number=5000, distribution="norm", match_moments=True)
    plan = request["plan"]
    plan.update(t0="2026-10", retirement_year=2040, withdrawal_years=30, horizon_years=44,
                buffer_lookahead_months=12, savings_horizon_years=10, reserves_until_retirement=True,
                savings_mode="separate", pension_replaces_expenses=True,
                accumulation_last_date_pin="2026-09", withdrawal_last_date_pin="2026-09")
    for key in plan["rates"]:
        plan["rates"][key] = (metadata["risk_free_rate"] if key == "buffer_rate"
                              else metadata["inflation_rate"])
    plan["assets"] = [
        {"label": translate(label, language), "amount": amount, "currency": currency,
         "asset_class": asset_class, "growth_rate": growth}
        for label, amount, asset_class, growth in (
            ("Synthetic invested capital", opening, "portfolio", None),
            ("Emergency reserve balance", reserve, "reserve", metadata["risk_free_rate"]),
            ("Apartment", apartment, "non_working", metadata["inflation_rate"]),
            ("Current car", car, "non_working", -.10),
            ("Long-term savings", savings, "savings", None),
        )
    ]
    plan["liabilities"] = [
        {"label": translate("Mortgage", language), "principal": loan, "annual_rate": .05,
         "monthly_payment": payment, "term_months": 120, "start_month": "2026-10"},
    ]
    plan["persons"] = [{"name": translate("Participant 1", language), "birth_year": 1995, "role": "adult"}]
    plan["budget_items"] = [
        {"kind": "income", "label": translate("Employment income", language),
         "monthly_amount": income, "end_rule": "until_retirement"},
        {"kind": "expense", "label": translate("Household expenses", language), "monthly_amount": expenses},
    ]
    plan["goals"] = [
        {"goal_id": 1, "label": translate("Car", language), "kind": "lump", "amount_pv": car_goal,
         "pv_year": 2026, "target_year": 2029, "target_month": 10, "becomes_asset": True,
         "replaces_asset": translate("Current car", language)},
        {"goal_id": 2, "label": translate("Home purchase", language), "kind": "lump", "amount_pv": home_goal,
         "pv_year": 2026, "target_year": 2031, "target_month": 10, "becomes_asset": True},
        {"goal_id": 3, "label": translate("Early retirement", language), "kind": "retirement_income",
         "amount_pv": 1, "amount_basis": "expense_share", "pv_year": 2026},
    ]
    plan["goal_savings_rates"] = {
        goal["label"]: metadata["risk_free_rate"] for goal in plan["goals"][:2]
    }
    request["return_samples"] = {
        stage: {"start_month": portfolio["start_month"], "monthly_returns": portfolio["monthly_returns"]}
        for stage, portfolio in metadata["portfolios"].items()
    }
    return request, metadata


def calibrate_request(
    request: dict[str, Any], *, parameter: str = "opening_capital", target_success: float = .90,
    selection_margin: float = .02, mc_number: int = 5000, selection_seed: int = 707,
    validation_seed: int = 1707, max_multiplier: float = 32,
    evaluator: Callable[[dict[str, Any]], dict[str, Any]] = forecast,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Increase one disclosed lever on fixed draws and validate once on independent draws.

    Stop at the first passing candidate. Never select a seed, reduce spending,
    change goals, or edit results. Failure aborts report generation.
    """
    if parameter not in {"opening_capital", "income"}:
        raise ValueError("Calibration parameter must be opening_capital or income")
    if not 0 < target_success <= target_success + selection_margin <= 1:
        raise ValueError("Success target and selection margin must be within (0, 1]")
    if (isinstance(mc_number, bool) or not isinstance(mc_number, int) or mc_number < 2000
            or validation_seed == selection_seed or not math.isfinite(max_multiplier) or max_multiplier < 1):
        raise ValueError("Use at least 2000 paths, different fixed seeds and a finite multiplier >= 1")
    candidate = deepcopy(request)
    candidate.update(seed=selection_seed, mc_number=mc_number)
    section = "assets" if parameter == "opening_capital" else "budget_items"
    selected = next(item for item in candidate["plan"][section] if (
        item.get("asset_class") == "portfolio" if parameter == "opening_capital"
        else item.get("kind") == "income"
    ))
    field = "amount" if parameter == "opening_capital" else "monthly_amount"
    baseline = selected[field]
    if not math.isfinite(baseline) or baseline <= 0:
        raise ValueError("Calibration requires a positive finite baseline")
    multiplier = 1.0
    attempts = []
    while True:
        selected[field] = baseline if multiplier == 1 else math.ceil(baseline * multiplier / 100) * 100
        result = evaluator(candidate)
        probability = result["metrics"]["probability_of_success"]
        attempts.append({"value": selected[field], "probability": probability})
        if probability >= target_success + selection_margin:
            break
        if multiplier >= max_multiplier:
            raise ValueError(f"Calibration limit {max_multiplier} reached below the selection target")
        multiplier = min(multiplier * 1.25, max_multiplier)
    candidate["seed"] = validation_seed
    validated = evaluator(candidate)
    validation_probability = validated["metrics"]["probability_of_success"]
    if validation_probability < target_success:
        raise ValueError(f"Independent validation {validation_probability:.3%} is below {target_success:.3%}")
    metadata = {
        "parameter": parameter, "baseline_value": baseline, "calibrated_value": selected[field],
        "target_success": target_success, "selection_target": target_success + selection_margin,
        "selection_probability": probability, "validation_probability": validation_probability,
        "selection_seed": selection_seed, "validation_seed": validation_seed, "mc_number": mc_number,
        "distribution": candidate["distribution"], "match_moments": candidate["match_moments"],
        "max_multiplier": max_multiplier, "attempts": attempts,
    }
    return candidate, validated, metadata


def _metadata(path: Path, metadata: dict[str, Any], language: str) -> None:
    """Append reproducible economic assumptions without altering saved forecast values."""
    book = load_workbook(path)
    sheet = book[translate("Assumptions", language)]
    rows = [("Average inflation", metadata["inflation_rate"], True),
            ("Reference rate", metadata["risk_free_rate"], True)]
    rows.extend((key, json.dumps(value, ensure_ascii=False, allow_nan=False), False)
                for key, value in metadata.items()
                if key not in {"inflation_rate", "risk_free_rate", "portfolios", "calibration"}
                and not key.startswith("fx_"))
    calibration = metadata.get("calibration")
    if calibration:
        captions = {
            "baseline_value": "Baseline value", "calibrated_value": "Calibrated value",
            "selection_target": "Selection target", "selection_probability": "Selection probability",
            "validation_probability": "Independent validation probability",
            "selection_seed": "Selection seed", "validation_seed": "Validation seed",
            "mc_number": "Monte Carlo paths", "distribution": "Distribution",
        }
        parameter = ("Opening investment capital" if calibration["parameter"] == "opening_capital"
                     else "Monthly employment income")
        rows.append(("Calibration parameter", translate(parameter, language), False))
        rows.extend((caption, calibration[key], key.endswith(("target", "probability")))
                    for key, caption in captions.items())
    for stage, portfolio in metadata["portfolios"].items():
        for key, caption in (("annual_return", "Annual return"), ("annual_risk", "Annual risk"),
                             ("cagr", "Historical CAGR")):
            rows.append((f"{stage}: {translate(caption, language)}", portfolio[key], True))
        for key, value in portfolio.items():
            if key not in {"annual_return", "annual_risk", "cagr", "monthly_returns"}:
                rows.append((f"{stage}.{key}", json.dumps(value, ensure_ascii=False, allow_nan=False), False))
    for key, value, rate in rows:
        row = sheet.max_row + 1
        values = (translate("Economic data", language), translate(key, language), value)
        for column, text in enumerate(values, 1):
            cell = sheet.cell(row, column, text)
            cell.font = Font(name="Microsoft YaHei" if language == "zh" else "Arial", size=11)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            if isinstance(text, str):
                cell.data_type = "s"
        if rate:
            sheet.cell(row, 3).number_format = "0.00%"
        sheet.row_dimensions[row].height = 30
    sheet.print_area = sheet.dimensions
    book.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", nargs="+", choices=LANGUAGES, default=list(LANGUAGES))
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "tmp" / "multilingual-reports")
    parser.add_argument("--calibrate-parameter", choices=("opening_capital", "income"),
                        default="opening_capital")
    parser.add_argument("--target-success", type=float, default=.90)
    parser.add_argument("--mc-number", type=int, default=5000)
    parser.add_argument("--forecast-only", action="store_true",
                        help="Save validated snapshots without rendering")
    args = parser.parse_args()
    snapshots = json.loads((Path(__file__).parent / "currency-assumptions.json").read_text())
    requests = {
        language: build_request(DEFAULT_CURRENCIES[language], snapshots, language=language)
        for language in args.languages
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for language, (request, metadata) in requests.items():
        currency = request["currency"]
        request, result, calibration = calibrate_request(
            request, parameter=args.calibrate_parameter, target_success=args.target_success,
            mc_number=args.mc_number,
        )
        metadata["calibration"] = calibration
        for kind, value in (("request", request), ("result", result), ("metadata", metadata)):
            snapshot = args.output_dir / f"{language}-{currency.lower()}-{kind}.json"
            snapshot.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
        print(f"{language}/{currency}: success={calibration['validation_probability']:.2%}; "
              f"{calibration['parameter']}={calibration['calibrated_value']:,.0f}", flush=True)
        if args.forecast_only:
            continue
        images = {}
        for logarithmic in (False, True):
            scale = "log" if logarithmic else "linear"
            paths = export_charts(result, args.output_dir / language / scale,
                                  format="png", logarithmic=logarithmic, language=language)
            images.update({path.stem + ("_log" if logarithmic else ""): path for path in paths})
        scenarios = [{"label": translate("Calibrated synthetic example", language),
                      "request": request, "result": result}]
        path = export_report(scenarios,
                             args.output_dir / f"plan-{language}.xlsx", language=language,
                             chart_images=images, brand=ReportBrand(contact=""))
        _metadata(path, metadata, language)
    print(f"Synthetic language editions written to {args.output_dir}")


if __name__ == "__main__":
    main()
