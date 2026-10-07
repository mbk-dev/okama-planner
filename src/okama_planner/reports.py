"""Neutral Excel presentation of saved forecasts, independent of the calculation path."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from okama_planner.api import ForecastRequest
from okama_planner.horizon import effective_horizon_years

MONEY = '#,##0.00;(#,##0.00);"-"'
PERCENT = '0.0%;(0.0%);"-"'


@dataclass(frozen=True)
class ReportBrand:
    """Presentation only. Logo is a local image, never downloaded by this module."""

    company: str = "Example Advisory"
    contact: str = "team@example.invalid"
    color: str = "244C66"
    logo: Path | None = None


def _text(sheet: Worksheet, row: int, column: int, value: Any) -> None:
    cell = sheet.cell(row, column, value)
    if isinstance(value, str):
        cell.data_type = "s"


def _append(sheet: Worksheet, values: Sequence[Any]) -> None:
    row = sheet.max_row + 1
    for column, value in enumerate(values, 1):
        _text(sheet, row, column, value)


def _sheet(book: Workbook, name: str, brand: ReportBrand, headers: list[str]) -> Worksheet:
    sheet = book.create_sheet(name)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(3, len(headers)))
    _text(sheet, 1, 1, f"{brand.company} | {name}")
    sheet["A1"].font = Font(name="Arial", size=18, color="FFFFFF", bold=True)
    sheet["A1"].fill = PatternFill("solid", fgColor=brand.color)
    sheet.row_dimensions[1].height = 34
    sheet["A2"] = "='Branding'!B3"
    sheet["A3"] = "Saved forecast; edit the request and rerun Planner to change calculations."
    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=max(3, len(headers)))
    sheet.row_dimensions[3].height = 30
    sheet.freeze_panes = "B6"
    sheet.sheet_view.showGridLines = False
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = "1:5"
    for column, header in enumerate(headers, 1):
        _text(sheet, 5, column, header)
        cell = sheet.cell(5, column)
        cell.fill = PatternFill("solid", fgColor=brand.color)
        cell.font = Font(name="Arial", color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.column_dimensions[get_column_letter(column)].width = 24 if column > 1 else 38
    sheet.row_dimensions[5].height = 36
    return sheet


def _validate(items: Sequence[dict[str, Any]]) -> list[ForecastRequest]:
    if not 1 <= len(items) <= 2:
        raise ValueError("Provide a baseline and optionally one comparison scenario")
    requests = []
    for item in items:
        request = ForecastRequest.model_validate(item["request"])
        result = item["result"]
        encoded = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        if result["provenance"]["input_sha256"] != digest:
            raise ValueError("Saved result does not match its request")
        if result["schema_version"] not in {"1.0", "1.1"} or result["currency"] != request.currency:
            raise ValueError("Unsupported result schema or inconsistent currency")
        if result["portfolio_mode"] != request.portfolio_mode or (
            result["schema_version"] == "1.0" and result["portfolio_mode"] != "single"
        ):
            raise ValueError("Unsupported or inconsistent portfolio mode")
        periods = pd.period_range(
            request.plan.t0, periods=12 * effective_horizon_years(request.plan), freq="M"
        )
        months = [str(p) for p in periods]
        if list(result["ledger"]["months"]) != months:
            raise ValueError("Ledger horizon does not match the request")
        chart_months = [str(periods[0] - 1), *months]
        for series in result["charts"].values():
            if [row["month"] for row in series] != chart_months:
                raise ValueError("Chart horizon does not match the request")
        _validate_actual(request, result, chart_months)
        json.dumps(result, allow_nan=False)
        requests.append(request)
    if any(
        (r.currency, r.plan.t0, effective_horizon_years(r.plan))
        != (requests[0].currency, requests[0].plan.t0, effective_horizon_years(requests[0].plan))
        for r in requests
    ):
        raise ValueError("Comparison requires the same currency, start and horizon")
    return requests



def _validate_actual(request: ForecastRequest, result: dict[str, Any], months: list[str]) -> None:
    if result["schema_version"] != "1.1":
        return
    if request.joint_history is None or request.allocation is None:
        raise ValueError("Joint result requires a joint request")
    series = [result["actual"]["monthly_summaries"], *(s["chart"] for s in result["segments"])]
    if any([row["month"] for row in rows] != months for rows in series):
        raise ValueError("Actual or segment horizon does not match the request")

def _assumptions(sheet: Worksheet, items: Sequence[dict[str, Any]], requests: list[ForecastRequest]) -> None:
    def flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
        if isinstance(value, dict):
            return [
                pair for key, child in value.items() for pair in flatten(child, f"{prefix}.{key}".strip("."))
            ]
        if isinstance(value, list):
            return [
                pair for i, child in enumerate(value) for pair in flatten(child, f"{prefix}[{i}] ".strip())
            ]
        return [(prefix, value)]

    for item, request in zip(items, requests, strict=True):
        data = request.model_dump(mode="json")
        data.pop("return_samples", None)
        data.pop("joint_history", None)
        for key, value in flatten(data):
            # Preserve complete assumptions instead of silently choosing a few scenario levers.
            _append(sheet, [item["label"], key, json.dumps(value, ensure_ascii=False, allow_nan=False)])
        for key, value in flatten(item["result"]["provenance"]):
            _append(sheet, [item["label"], f"provenance.{key}", json.dumps(value, ensure_ascii=False)])
    sheet.column_dimensions["B"].width = 46
    sheet.column_dimensions["C"].width = 75


def _budget(sheet: Worksheet, result: dict[str, Any]) -> None:
    end = 5 + len(result["ledger"]["lines"])
    for month in result["ledger"]["months"]:
        row = sheet.max_row + 1
        _append(sheet, [month, None, None, None, None, result["portfolio_flow"][month]])
        for column, kinds in [
            (2, ["income"]),
            (3, ["expense"]),
            (4, ["mortgage_payment", "goal_outflow", "asset_sale", "reserve_topup"]),
        ]:
            terms = [
                f"SUMIFS('Ledger'!$D$6:$D${end},'Ledger'!$A$6:$A${end},$A{row},"
                f"'Ledger'!$B$6:$B${end},\"{kind}\")"
                for kind in kinds
            ]
            sheet.cell(row, column, "=" + "+".join(terms))
        sheet.cell(row, 5, f"=SUM(B{row}:D{row})")
    sheet["D5"] = "Other ledger flows"
    sheet["F5"] = "Portfolio flow after reserves"


def _balance(sheet: Worksheet, result: dict[str, Any]) -> None:
    ledger = result["ledger"]
    for i, (portfolio, capital) in enumerate(
        zip(result["charts"]["portfolio"], result["charts"]["capital"], strict=True)
    ):
        row = [portfolio["month"], portfolio["p50"], capital["p50"]]
        if result["schema_version"] == "1.1":
            actual = result["actual"]["monthly_summaries"][i]
            row.extend(actual[key]["p50"] for key in ("buffer", "reserve", "non_working", "liability"))
        else:
            row.extend(
                ledger[key][i - 1] if i else None
                for key in ("buffer_balance", "reserve_balance", "non_working_balance", "liability_balance")
            )
        _append(sheet, row)
    sheet["A4"] = (
        "Actual scenario p50 balances, including opening balances; component medians are not additive."
        if result["schema_version"] == "1.1"
        else "Opening component balances are omitted; p50 series include the opening point."
    )
    sheet.merge_cells("A4:G4")
    sheet.row_dimensions[4].height = 30


def _goals(sheet: Worksheet, items: Sequence[dict[str, Any]]) -> None:
    for item in items:
        for goal in item["result"]["goals"]:
            _append(
                sheet,
                [
                    item["label"],
                    goal["label"],
                    goal["month"],
                    goal["amount_nominal"],
                    goal["p_affordable"],
                    goal["p_alive"],
                ],
            )
    sheet["A4"] = "Affordability and survival use the month before the goal; neither is full-plan success."
    sheet.merge_cells("A4:F4")


def _summary(sheet: Worksheet, result: dict[str, Any]) -> None:
    for label, value in [
        ("Full-plan success", result["metrics"]["probability_of_success"]),
        ("Terminal portfolio p50", result["metrics"]["terminal_p50"]),
        ("Portfolio mode", result["portfolio_mode"]),
        *(([("Total unmet mean", result["metrics"]["unmet_mean"])])
          if result["schema_version"] == "1.1" else
          [("Gamma", "Not available"), ("Equivalent annual alpha", "Not available")]),
    ]:
        _append(sheet, [label, value])
    sheet["B6"].number_format = PERCENT
    sheet["A12"] = "Monte Carlo percentiles describe separate distributions, not one jointly realised path."
    sheet.merge_cells("A12:D12")
    sheet.row_dimensions[12].height = 38


def _comparison(sheet: Worksheet, items: Sequence[dict[str, Any]]) -> None:
    baseline = items[0]["result"]
    other = items[1]["result"] if len(items) == 2 else None
    for key, label in [
        ("probability_of_success", "Full-plan success"),
        ("terminal_p50", "Terminal portfolio p50"),
    ]:
        row = sheet.max_row + 1
        values = [label, baseline["metrics"][key], other["metrics"][key] if other else "Not supplied"]
        _append(sheet, [*values, None if other else "Not supplied"])
        if other:
            sheet.cell(row, 4, f"=C{row}-B{row}")
    if all(item["result"]["schema_version"] == "1.0" for item in items):
        for label in ["Gamma", "Equivalent annual alpha"]:
            _append(sheet, [label, "Not available", "Not available", "Not available"])
    else:
        _joint_comparison(sheet, items)
    for column in ("B", "C", "D"):
        sheet[f"{column}6"].number_format = PERCENT
    sheet["A4"] = (
        "Differences are descriptive; changed goals or cash flows prevent a like-for-like investment ranking."
    )
    sheet.merge_cells("A4:D4")
    sheet.row_dimensions[4].height = 36



def _joint_goals(sheet: Worksheet, items: Sequence[dict[str, Any]]) -> None:
    for item in items:
        for goal in item["result"]["goals"]:
            joint = item["result"]["schema_version"] == "1.1"
            _append(sheet, [
                item["label"], goal["label"], goal["month"], goal["amount_nominal"],
                goal["p_funded"] if joint else "Legacy: see affordability in saved JSON",
                goal.get("p_full_stream"), goal.get("funded_mean"), goal.get("unmet_mean"),
                goal.get("funding_basis", "legacy_before_goal_affordability"),
            ])
    sheet["A4"] = "Actual funding covers every required goal event; pension success covers the full stream."
    sheet.merge_cells("A4:I4")


def _joint_comparison(sheet: Worksheet, items: Sequence[dict[str, Any]]) -> None:
    left = items[0]["result"]
    right = items[1]["result"] if len(items) == 2 else None

    def difference(label: str, a: Any, b: Any, probability: bool = False) -> None:
        row = sheet.max_row + 1
        _append(sheet, [label, a, b, None])
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            sheet.cell(row, 4, f"=C{row}-B{row}")
        else:
            _text(sheet, row, 4, "Not comparable")
        if probability:
            for column in (2, 3, 4):
                sheet.cell(row, column).number_format = PERCENT

    difference("Total unmet mean", left["metrics"].get("unmet_mean", "Legacy: unavailable"),
               right["metrics"].get("unmet_mean", "Legacy: unavailable") if right else "Not supplied")
    other_goals = {g["goal_id"]: g for g in right["goals"]} if right else {}
    for goal in left["goals"]:
        other = other_goals.get(goal["goal_id"], {})
        for key, label, probability in [
            ("p_funded", "fully funded probability", True),
            ("p_full_stream", "full-stream probability", True),
            ("funded_mean", "funded mean", False),
            ("unmet_mean", "unmet mean", False),
        ]:
            if key == "p_full_stream" and goal.get(key) is None and other.get(key) is None:
                continue
            difference(f"{goal['label']}: {label}", goal.get(key, "Unavailable"),
                       other.get(key, "Unavailable"), probability)
    for label, key in [("Portfolio mode", "portfolio_mode"), ("Shared history hash", "history_sha256"),
                       ("Shared scenario rows hash", "scenario_rows_sha256")]:
        if key == "portfolio_mode":
            values = [r[key] if r else "Not supplied" for r in (left, right)]
        else:
            values = [r["provenance"].get(key, "Legacy: unavailable") if r else "Not supplied"
                      for r in (left, right)]
        _append(sheet, [label, *values, "Same" if values[0] == values[1] else "Different"])


def _joint_details(book: Workbook, items: Sequence[dict[str, Any]], brand: ReportBrand) -> None:
    segments = _sheet(book, "Segments", brand, [
        "Scenario", "Segment", "Goal ID", "Opening amount", "Full-funding probability", "Completion",
    ])
    allocation = _sheet(book, "Allocation", brand, ["Scenario", "Policy / schedule", "Explicit value"])
    balances = _sheet(book, "Segment balances", brand, ["Scenario", "Segment", "Month", "p10", "p50", "p90"])
    events = _sheet(book, "Funding events", brand, [
        "Scenario", "Month", "Kind", "Label", "Goal ID", "Segment", "Required mean", "Funded mean",
        "Unmet mean", "Fully funded probability", "Funding sources (mean)",
    ])
    transfers = _sheet(book, "Transfers", brand, [
        "Scenario", "Mode", "Month", "Source", "Destination", "Reason", "Amount mean",
    ])
    segments["A4"] = "Single mode segment balances are a display attribution within one pooled portfolio."
    segments.merge_cells("A4:F4")
    allocation.column_dimensions["C"].width = 95
    for item in items:
        result = item["result"]
        if result["schema_version"] != "1.1":
            continue
        label = item["label"]
        for key, value in result["allocation"].items():
            if key != "segments":
                _append(allocation, [label, key, json.dumps(value, ensure_ascii=False)])
        for segment in result["segments"]:
            _append(segments, [label, segment["segment_id"], segment["goal_id"], segment["opening_amount"],
                               segment["probability_of_full_funding"], json.dumps(segment["completion"])])
            segments.cell(segments.max_row, 5).number_format = PERCENT
            for key in ("strategy", "active_strategy"):
                _append(allocation, [label, f"{segment['segment_id']}.{key}", json.dumps(segment[key])])
            for point in segment["chart"]:
                _append(balances, [label, segment["segment_id"], point["month"],
                                   point["p10"], point["p50"], point["p90"]])
        for event in result["actual"]["event_funding"]:
            _append(events, [label, event["month"], event["kind"], event["label"], event["goal_id"],
                             event["segment_id"], event["required_mean"], event["funded_mean"],
                             event["unmet_mean"], event["p_funded"], json.dumps(event["funding_sources"])])
            events.cell(events.max_row, 10).number_format = PERCENT
        for transfer in result["actual"]["transfers"]:
            _append(transfers, [label, result["portfolio_mode"], transfer["month"], transfer["source"],
                                transfer["destination"], transfer["reason"], transfer["amount_mean"]])

def _style_cell(cell: Any) -> None:
    formula = cell.data_type == "f"
    color = "008000" if formula and "!" in cell.value else "000000" if formula else "0000FF"
    cell.font = Font(name="Arial", size=11, color=color)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    if isinstance(cell.value, str) and not formula:
        cell.data_type = "s"
    if isinstance(cell.value, (float, int)) or formula and cell.row >= 6:
        if cell.number_format == "General":
            cell.number_format = MONEY
    if not formula and isinstance(cell.value, (float, int)):
        cell.comment = Comment(
            "Source: supplied saved forecast; see Assumptions for request hash and provenance.",
            "okama Planner",
        )


def _finish(book: Workbook) -> None:
    for sheet in book:
        for row in sheet:
            for cell in row:
                if sheet.title != "Branding" and cell.row in (1, 5):
                    continue
                _style_cell(cell)
            if row[0].row > 5:
                lines = max(
                    math.ceil(
                        (12 if cell.data_type == "f" else len(str(cell.value or "")))
                        / max(10, sheet.column_dimensions[get_column_letter(cell.column)].width)
                    )
                    for cell in row
                )
                sheet.row_dimensions[row[0].row].height = min(120, max(18, 16 * lines))
        sheet.print_options.horizontalCentered = True
        sheet.print_area = sheet.dimensions
    for coordinate in ("B2", "B3"):
        book["Branding"][coordinate].fill = PatternFill("solid", fgColor="FFF2CC")


def _print_layout(book: Workbook, summary: Worksheet, unit: str, label: str) -> None:
    book.move_sheet(summary, offset=-1)
    branding = book["Branding"]
    branding.page_setup.orientation = "landscape"
    branding.page_setup.paperSize = branding.PAPERSIZE_A4
    branding.page_setup.fitToWidth = 1
    branding.page_setup.fitToHeight = 1
    branding.sheet_properties.pageSetUpPr.fitToPage = True
    branding.print_area = "A1:F7"
    branding.column_dimensions["A"].width = 26
    for sheet in book:
        sheet.oddFooter.right.text = f"Nominal {unit} | {label}"
        sheet.oddFooter.right.font = "Arial"
    for name in ("Budget", "Ledger"):
        basis = " | Planned requirements, not actual payments/balances" if "Funding events" in book else ""
        book[name]["A4"] = f"Baseline: {label} | Nominal {unit}{basis}"
        book[name].merge_cells(start_row=4, start_column=1, end_row=4, end_column=book[name].max_column)


def export_report(
    scenarios: Sequence[dict[str, Any]],
    path: str | Path,
    *,
    brand: ReportBrand | None = None,
) -> Path:
    """Export one saved forecast and optionally a comparison. Calculations are never rerun.

    Each scenario has ``label``, ``request`` and ``result``. Only identical units/horizons
    can be compared. Branding and strings are presentation inputs, never Excel formulas.
    """
    requests = _validate(scenarios)
    brand = brand or ReportBrand()
    if not re.fullmatch(r"[0-9a-fA-F]{6}", brand.color):
        raise ValueError("Brand color must be six hexadecimal digits")
    book = Workbook()
    book.remove(book.active)
    branding = book.create_sheet("Branding")
    for row, (label, value) in enumerate(
        [
            ("Branding", "Presentation settings"),
            ("Company", brand.company),
            ("Contact", brand.contact),
            ("Color", brand.color),
            ("Editable", "B2/B3: text only; rerun exporter for logo/color changes"),
        ],
        1,
    ):
        _text(branding, row, 1, label)
        _text(branding, row, 2, value)
    branding.column_dimensions["B"].width = 70
    if brand.logo:
        image = Image(brand.logo)
        image.height, image.width = 48, 144
        branding.add_image(image, "D2")
        branding["D5"] = "Local example logo"
    result = scenarios[0]["result"]
    unit = requests[0].currency
    summary = _sheet(book, "Summary", brand, ["Indicator", f"Baseline ({unit})", "", ""])
    _summary(summary, result)
    _budget(
        _sheet(
            book,
            "Budget",
            brand,
            ["Month", "Income", "Expenses", "Other flows", "Net ledger flow", "Portfolio flow"],
        ),
        result,
    )
    _balance(
        _sheet(
            book,
            "Balance",
            brand,
            [
                "Month",
                "Portfolio p50",
                "Net capital p50",
                "Purchase buffer",
                "Reserve account",
                "Non-working assets",
                "Debt",
            ],
        ),
        result,
    )
    joint = any(item["result"]["schema_version"] == "1.1" for item in scenarios)
    (_joint_goals if joint else _goals)(
        _sheet(
            book,
            "Goals",
            brand,
            [
                "Scenario",
                "Goal",
                "Month",
                f"Nominal amount ({unit})",
                "Affordable probability",
                "Alive probability",
            ] if not joint else [
                "Scenario", "Goal", "First month", f"First required amount ({unit})",
                "Fully funded probability", "Full-stream probability", "Funded mean (whole goal)",
                "Unmet mean (whole goal)", "Funding basis",
            ],
        ),
        scenarios,
    )
    _assumptions(
        _sheet(book, "Assumptions", brand, ["Scenario", "Parameter", "Supplied value"]), scenarios, requests
    )
    _comparison(
        _sheet(
            book,
            "Comparison",
            brand,
            [
                "Indicator",
                str(scenarios[0]["label"]),
                str(scenarios[1]["label"]) if len(scenarios) == 2 else "No comparison",
                "Difference",
            ],
        ),
        scenarios,
    )
    raw = _sheet(book, "Ledger", brand, ["Month", "Kind", "Label", f"Amount ({unit})", "Resolved rate"])
    for line in result["ledger"]["lines"]:
        _append(raw, [line["month"], line["line_kind"], line["label"], line["amount"], line["resolved_rate"]])
    if joint:
        _joint_details(book, scenarios, brand)
    instructions = _sheet(book, "Instructions", brand, ["Topic", "Instruction", ""])
    for row in [
        [
            "License",
            "MIT applies to code, neutral layout and synthetic examples; "
            "retain the license when redistributing.",
        ],
        [
            "Edit",
            "Edit Branding B2/B3 for contact text. Rerun the exporter to change "
            "company headings, colors and local logo.",
        ],
        [
            "Calculations",
            "Request/result are snapshots. Change the full request and rerun forecast before exporting; "
            "editing workbook numbers does not rerun Monte Carlo.",
        ],
        [
            "Assumptions",
            "Every scenario has its own full plan and provenance. Return histories are identified by hashes; "
            "keep the original request/result JSON files.",
        ],
        [
            "Units",
            f"All monetary amounts are nominal {unit}; rates and probabilities are fractions. "
            "Budget expenses and other outflows are negative.",
        ],
        [
            "Limits",
            "Legacy single or joint single/per_goal investments; fixed-rate savings are separate reserves. "
            "No jurisdictional tax, FX, gamma/alpha or white label legal declaration is inferred.",
        ],
        [
            "Country rules",
            "Supply supported budgets and cash flows explicitly. "
            "Fees/taxes absent from inputs are not modelled. "
            "Formatting does not change financial assumptions.",
        ],
        [
            "Recalculate",
            "Recalculate Excel summary formulas before using cached values. "
            "Compare numeric series separately; "
            "percentile components are not additive.",
        ],
    ]:
        _append(instructions, row)
    instructions.column_dimensions["B"].width = 95
    _finish(book)
    _print_layout(book, summary, unit, str(scenarios[0]["label"]))
    for row in range(6, book["Goals"].max_row + 1):
        for column in (5, 6):
            book["Goals"].cell(row, column).number_format = PERCENT
    for row in range(6, raw.max_row + 1):
        raw.cell(row, 5).number_format = PERCENT
    book.active = book.sheetnames.index("Summary")
    book.properties.creator = "okama Planner"
    book.properties.title = "Neutral financial plan"
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    book.save(destination)
    return destination
