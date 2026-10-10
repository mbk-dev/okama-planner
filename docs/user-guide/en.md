# User guide

[English](en.md) · [Русский](ru.md) · [Deutsch](de.md) · [Español](es.md) · [中文](zh.md)

## Install and run

okama Planner builds monthly household cash flows and Monte Carlo forecasts. Python 3.11 or later is supported. Install the report extras for Excel exports. The development configuration uses Python 3.14; select that interpreter explicitly when contributing:

```bash
git clone https://github.com/mbk-dev/okama-planner.git
cd okama-planner
poetry env use python3.14
poetry install --extras reports
poetry run python examples/localized_plan.py --output-dir tmp/localized-example
```

The example requires neither market downloads, a browser nor a client database. It uses fictional USD amounts and frozen synthetic monthly returns. It calculates once with seed `42`, saves `request.json` and `result.json`, then exports `plan-en.xlsx`, `plan-ru.xlsx`, `plan-de.xlsx`, `plan-es.xlsx`, `plan-zh.xlsx` and interactive offline `forecast.html` files under each language's `linear/` and `log/` directories. Open an HTML file locally to inspect the portfolio and net capital. All five editions use identical USD amounts, assumptions and numerical results. A seed does not freeze dependencies: keep the environment versions for exact replay.

Select fewer editions with `--languages en de`. Add `--image-format png` or `--image-format svg` to render static charts when Chrome or Chromium is installed; `--browser-executable /path/to/chromium` selects its executable. HTML and Excel exports do not require a browser.

## Author a plan

Start from [the fictional request](../../examples/baseline-request.json). Use `forecast(request)` from `okama_planner` with the complete request. `plan.t0` is the first month; supply the horizon, retirement date, assets, liabilities, monthly income and expenses. Set each goal's unique `goal_id`, `label`, `kind`, present amount `amount_pv`, valuation year `pv_year` and target date. Rates and probabilities are fractions: `0.02` means 2%. Income and expense inputs are positive magnitudes; the cash-flow ledger signs expenses as outflows.

`currency="USD"` specifies financial units. `language="de"` in `export_report` or `export_charts` selects German presentation. Language never converts money or changes inflation, portfolio returns or jurisdictional assumptions. User labels remain as supplied; translate them yourself when preparing another edition. See [the localization contract](../localization.md) for supported messages, formatting and MCP startup language configuration.

Single-currency requests use one currency. Multi-currency requests explicitly define `reporting_currency`, native `currency_groups` and FX assumptions; localized reports preserve each native currency and the reporting unit. See [multi-currency planning](../multicurrency.md) and [portfolio modes](../portfolio-modes.md). Localization does not supply taxes or fees missing from inputs, and does not add unsupported gamma/alpha fields to the forecast request.

## Read and preserve results

Amounts in reports and charts are nominal: indexation follows the supplied rates. Inflation does not automatically turn chart amounts into constant purchasing power. On a logarithmic scale zero and negative values are omitted and affected bands have gaps; use the linear chart to inspect those periods.

Exports consume saved request/result snapshots without rerunning the forecast:

```python
import json
from pathlib import Path
from okama_planner.reports import export_report
from okama_planner.charts import export_charts

folder = Path("tmp/localized-example")
request = json.loads((folder / "request.json").read_text())
result = json.loads((folder / "result.json").read_text())
export_report([{"label": "Synthetic USD", "request": request, "result": result}],
              folder / "review.xlsx", language="en")
export_charts(result, folder / "review", language="en")
```

Editing workbook numbers does not recalculate Monte Carlo. Change inputs, rerun `forecast` and save new snapshots before exporting a changed plan. Recalculate Excel summary formulas before relying on cached formula values. Preserve the original JSON and provenance alongside exports.

## Local records and privacy

The optional SQLite registry stores clients, versioned plans, scenarios and saved results locally. Keep names and contact details in the registry; refer to clients by registry codes in shared material. Keep databases and real client exports outside public Git. Localization changes display text; SQL table/column names, JSON keys, enum values and technical identifiers remain stable. See [storage](../storage.md) for database setup and API examples.
