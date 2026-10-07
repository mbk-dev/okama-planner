"""Check reports against independently saved public calculations."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from openpyxl import load_workbook

EXAMPLES = Path(__file__).parents[1] / "examples"


def scenario(name: str = "baseline") -> dict:
    return {
        "label": name.title(),
        "request": json.loads((EXAMPLES / f"{name}-request.json").read_text()),
        "result": json.loads((EXAMPLES / f"{name}-result.json").read_text()),
    }


def test_report_preserves_money_and_distinguishes_capital(tmp_path: Path) -> None:
    from okama_planner.reports import export_report

    target = tmp_path / "report.xlsx"
    export_report([scenario(), scenario("deferred")], target)
    book = load_workbook(target)
    assert {"Summary", "Budget", "Balance", "Goals", "Assumptions", "Comparison"} <= set(book.sheetnames)
    assert book["Summary"]["B6"].value == 0.974
    assert book["Summary"]["B7"].value == pytest.approx(25291.057126370935)
    assert book["Comparison"]["D7"].value == "=C7-B7"
    for cell in ("B6", "C6", "D6"):
        assert book["Budget"][cell].data_type == "f"
        assert "Ledger" in book["Budget"][cell].value
    assert book["Budget"]["E6"].value == "=SUM(B6:D6)"
    assert book["Budget"].row_dimensions[6].height <= 24
    assert book["Balance"]["B6"].value == 75000
    assert book["Balance"]["C6"].value == 75000
    assert "Portfolio p50" in book["Balance"]["B5"].value
    assert "Net capital p50" in book["Balance"]["C5"].value
    assert book["Balance"]["E5"].value == "Reserve account"
    assert book["Summary"]["B9"].value == "Not available"
    assert book["Summary"]["B10"].value == "Not available"


def test_brand_changes_presentation_without_changing_results(tmp_path: Path) -> None:
    from okama_planner.reports import ReportBrand, export_report

    first, second = tmp_path / "one.xlsx", tmp_path / "two.xlsx"
    export_report([scenario()], first)
    export_report(
        [scenario()],
        second,
        brand=ReportBrand(company="=Example Advisory", contact="team@example.invalid", color="703080"),
    )
    a, b = load_workbook(first), load_workbook(second)
    assert b["Branding"]["B2"].value == "=Example Advisory"
    assert b["Branding"]["B2"].data_type == "s"
    assert b["Summary"]["A1"].fill.fgColor.rgb.endswith("703080")
    assert [a["Summary"][f"B{r}"].value for r in range(6, 11)] == [
        b["Summary"][f"B{r}"].value for r in range(6, 11)
    ]


@pytest.mark.parametrize("mutation", ["request", "currency", "schema", "months"])
def test_report_rejects_inconsistent_saved_calculation(tmp_path: Path, mutation: str) -> None:
    from okama_planner.reports import export_report

    item = deepcopy(scenario())
    if mutation == "request":
        item["request"]["seed"] += 1
    elif mutation == "currency":
        item["result"]["currency"] = "EUR"
    elif mutation == "schema":
        item["result"]["schema_version"] = "9.0"
    else:
        item["result"]["charts"]["capital"].pop()
    with pytest.raises(ValueError):
        export_report([item], tmp_path / "bad.xlsx")
    assert not (tmp_path / "bad.xlsx").exists()


def test_comparison_discloses_changed_inputs_and_rejects_different_units(tmp_path: Path) -> None:
    from okama_planner.reports import export_report

    export_report([scenario(), scenario("deferred")], tmp_path / "compare.xlsx")
    book = load_workbook(tmp_path / "compare.xlsx")
    rows = list(book["Assumptions"].values)
    assert any("target_year" in str(row) and "2029" in str(row) for row in rows)
    item = scenario("deferred")
    item["request"]["currency"] = "EUR"
    for asset in item["request"]["plan"]["assets"]:
        asset["currency"] = "EUR"
    from okama_planner import forecast

    item["result"] = forecast(item["request"])
    with pytest.raises(ValueError, match="Comparison requires"):
        export_report([scenario(), item], tmp_path / "different.xlsx")


def test_logo_is_embedded_and_color_validated(tmp_path: Path) -> None:
    from PIL import Image

    from okama_planner.reports import ReportBrand, export_report

    logo = tmp_path / "logo.png"
    Image.new("RGB", (144, 48), "purple").save(logo)
    export_report([scenario()], tmp_path / "logo.xlsx", brand=ReportBrand(logo=logo))
    import zipfile

    with zipfile.ZipFile(tmp_path / "logo.xlsx") as archive:
        assert any(name.startswith("xl/media/") for name in archive.namelist())
    with pytest.raises(ValueError, match="color"):
        export_report([scenario()], tmp_path / "bad.xlsx", brand=ReportBrand(color="invalid"))


def test_scenario_labels_are_text_in_every_sheet(tmp_path: Path) -> None:
    from okama_planner.reports import export_report

    item = scenario()
    item["label"] = "=1+1"
    export_report([item], tmp_path / "labels.xlsx")
    book = load_workbook(tmp_path / "labels.xlsx")
    for name in ("Goals", "Assumptions"):
        assert book[name]["A6"].value == "=1+1"
        assert book[name]["A6"].data_type == "s"


def joint_scenario(mode: str = "per_goal", opening: float = 100) -> dict:
    from okama_planner import forecast, with_portfolio_mode
    from test_allocation import allocation, request

    raw = request(opening)
    raw["plan"]["budget_items"] = []
    raw["plan"]["goals"] = [
        {"goal_id": 1, "label": "Home", "kind": "lump", "amount_pv": 80,
         "pv_year": 2026, "target_year": 2026, "becomes_asset": True},
        {"goal_id": 2, "label": "Pension", "kind": "retirement_income",
         "amount_pv": 20, "pv_year": 2026},
    ]
    raw["allocation"] = allocation(opening, (1, 2))
    raw["allocation"]["segments"][1]["completion"] = {
        "action": "transfer_to", "destination": "g2"
    }
    if mode == "single":
        raw = with_portfolio_mode(raw, portfolio_mode=mode).model_dump(mode="json")
    return {"label": mode, "request": raw, "result": forecast(raw)}


def test_joint_report_uses_actual_funding_and_side_balances(tmp_path: Path) -> None:
    from okama_planner.reports import export_report

    item = joint_scenario(opening=0)
    export_report([item], tmp_path / "actual.xlsx")
    book = load_workbook(tmp_path / "actual.xlsx")
    assert book["Balance"]["F7"].value == 0  # Planned property is 80; failed purchase owns none.
    assert book["Balance"]["D6"].value == 0  # Actual opening side balance is available.
    assert "actual" in book["Balance"]["A4"].value.lower()
    assert "planned" in book["Budget"]["A4"].value.lower()
    assert "planned" in book["Ledger"]["A4"].value.lower()
    assert book["Goals"]["E6"].value == 0
    assert book["Goals"]["G6"].value == 0
    assert book["Goals"]["H6"].value == 80
    assert book["Goals"]["I6"].value == "actual_event"
    assert book["Goals"]["F7"].value == 0
    assert book["Goals"]["H7"].value == 240
    assert book["Goals"]["I7"].value == "full_stream"
    assert not any(row[0] in {"Gamma", "Equivalent annual alpha"} for row in book["Summary"].values)


def test_joint_comparison_discloses_segments_events_and_differences(tmp_path: Path) -> None:
    from okama_planner.reports import export_report

    export_report([joint_scenario("single"), joint_scenario()], tmp_path / "modes.xlsx")
    book = load_workbook(tmp_path / "modes.xlsx")
    assert {"Segments", "Allocation", "Segment balances", "Funding events", "Transfers"} <= set(
        book.sheetnames
    )
    pension = list(book["Goals"].values)[6]
    assert pension[4:9] == (0, 0, 20, 220, "full_stream")
    assert any("transfer_to" in str(row) and "g2" in str(row) for row in book["Segments"].values)
    assert any("active_strategy" in str(row) and '"A"' in str(row) for row in book["Allocation"].values)
    assert any("surplus_weights" in str(row) for row in book["Allocation"].values)
    assert any(row[3:6] == ("household", "g1", "shortfall") for row in book["Transfers"].values)
    assert any(row[0] == "Total unmet mean" and row[3].startswith("=")
               for row in book["Comparison"].values)
    assert any(row[0] == "Pension: full-stream probability" for row in book["Comparison"].values)
    assert any(row[6:10] == (80, 80, 0, 1) for row in book["Funding events"].values)


@pytest.mark.parametrize("series", ["actual", "segment"])
def test_joint_report_rejects_incomplete_actual_horizon(tmp_path: Path, series: str) -> None:
    from okama_planner.reports import export_report

    item = joint_scenario()
    if series == "actual":
        item["result"]["actual"]["monthly_summaries"].pop()
    else:
        item["result"]["segments"][0]["chart"].pop()
    with pytest.raises(ValueError, match="horizon"):
        export_report([item], tmp_path / "bad.xlsx")
    assert not (tmp_path / "bad.xlsx").exists()
