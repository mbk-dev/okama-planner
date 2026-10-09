<div align="center">

# okama Planner

**Open-source personal and family financial planning powered by okama.**

[![CI](https://github.com/mbk-dev/okama-planner/actions/workflows/ci.yml/badge.svg)](https://github.com/mbk-dev/okama-planner/actions/workflows/ci.yml) [![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](pyproject.toml) [![MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

[Quick start](#quick-start) · [Reports & charts](#reports--charts) · [MCP](#use-with-an-ai-assistant) · [Client records](#client-records) · [Languages](#languages)

</div>

![Synthetic financial plan with three goals, a logarithmic USD axis, median and Monte Carlo percentile bands](docs/images/financial-plan-three-goals.png)

*Three goals, one household: **1 Education** (September 2027), **2 Home purchase** (July 2028),
**3 Retirement income** (January 2029). Logarithmic scale; blue median, shaded p25–p75 and p10–p90
ranges. All inputs and returns are fictional. Zero and negative values are not shown on a log axis.*

Build a monthly household plan, explore uncertainty, compare alternatives and export results
under your own brand. Designed for financial planners, technically comfortable individuals and
integration developers. Calculation quality comes first; Excel, charts and MCP provide ways to
use the application while a future web interface is explored.

## What you can do

| Task | Available today |
|---|---|
| Model a household | Income, expenses, assets, fixed-payment loans, reserves and dated goals |
| Choose a portfolio approach | One pooled portfolio or explicitly allocated portfolios for each goal |
| Compare plans | Shared market scenarios, goal funding, unmet payments and portfolio/capital outcomes |
| Present results | Configurable Excel reports and interactive offline HTML charts |
| Share visuals | PNG and SVG charts, goal markers and independent logarithmic scales |
| Automate calculations | Python API and optional tools in the existing okama-mcp server |

Separate goal portfolios share synchronized market scenarios. Fixed-rate savings accounts are
also supported, but are a different concept from investment portfolios for goals.
See [portfolio modes](docs/portfolio-modes.md) for allocation, transfers and funding rules.

## Quick start

Use **Python 3.11+** and [Poetry](https://python-poetry.org/). From a local source checkout:

```bash
git clone https://github.com/mbk-dev/okama-planner.git
cd okama-planner
poetry env use python3.11
poetry install --extras reports
poetry run python examples/demo.py
poetry run python examples/portfolio_modes.py
```

The first example compares a purchase now versus a deferred purchase. The second compares a
pooled portfolio with home and retirement portfolios on the same synthetic market scenarios.
Requests, results and an Excel comparison are saved under `tmp/`; neither example downloads
market data or needs a client database.

**Prefer to browse first?** Open the [saved family inputs](examples/family-single-request.json),
[results](examples/family-single-result.json) and [Excel report examples](https://github.com/mbk-dev/okama-planner/releases/tag/v0.2.0).
The [three-goal hero input](examples/readme-request.json) and [result](examples/readme-result.json)
are included too. For exact numerical replay, use the versions in [examples/versions.json](examples/versions.json);
a seed alone does not freeze data or dependencies. [Calculation contract →](docs/contract.md)

### Use the Python API

```python
import json
from pathlib import Path
from okama_planner import forecast

request = json.loads(Path("examples/readme-request.json").read_text())
result = forecast(request)
```

The result is a JSON-compatible dictionary containing cash flows, goals, forecast metrics,
chart series and provenance. Complete input validation uses `ForecastRequest`; its JSON Schema
is available through `ForecastRequest.model_json_schema()`.

## Reports & charts

### Excel under your own brand

Set your company name, contacts, logo and accent color. The exporter creates a new workbook;
it does not require a private template or a pre-existing client file.

```python
from okama_planner.reports import ReportBrand, export_report

export_report(
    [{"label": "Family plan", "request": request, "result": result}],
    "family-plan.xlsx",
    brand=ReportBrand(company="Example Advisory", color="244C66"),
)
```

| Workbook sections | What they show |
|---|---|
| Summary, Budget, Balance | Plan outcomes, planned monthly cash flows, portfolio and net capital |
| Goals, Assumptions, Comparison | Goal funding, model inputs and differences between scenarios |
| Ledger | Detailed planned cash-flow requirements |
| Segments, Allocation, Segment balances | Portfolio assignments, strategies and account projections |
| Funding events, Transfers | Actual funded/unmet payments and transfers in joint portfolio modes |
| Branding, Instructions | Your presentation settings and guidance for reading the workbook |

The optional sheets reflect the result schema and portfolio mode. Excel presents saved forecast
results: editing a cell does not rerun Monte Carlo. Change the input, recalculate and export again.
[Report details and fictional-brand examples →](docs/reports.md)

### Interactive and shareable charts

```python
from okama_planner.charts import export_charts

export_charts(result, "charts")                # offline interactive HTML
export_charts(result, "charts/png", format="png")
export_charts(result, "charts/svg", format="svg")
```

Portfolio and net capital are separate charts. HTML includes hover values, goal markers,
logarithmic-scale controls and image download buttons. Direct PNG/SVG rendering requires
Chrome or Chromium; HTML generation does not. This is a **chart export**, not a complete
HTML financial-plan report or a hosted web application. [Chart options →](docs/charts.md)

## Use with an AI assistant

Install Planner into the same environment as the existing **okama-mcp** server. Its current
source branch exposes `planner_forecast` and `planner_compare_modes`, while preserving the
existing portfolio tools. The adapter calls Planner rather than duplicating its calculations.

[Local installation, client setup and worked MCP examples →](https://github.com/mbk-dev/okama-mcp/blob/main/docs/planner.md)

Planner reports, chart rendering and consumption-utility helpers are not yet exposed through
these MCP tools. The published MCP package and public HTTP server have not been updated for
this integration; use the source installation described in the linked guide.

## Client records

**Planned:** an optional local SQLite client registry linked to versions of financial plans.
The database template will contain the schema and **no client, plan or result records**.
Calculations will remain usable without a database.

The table below illustrates how records could look. These people are fictional; their records
exist **only in this README**, not in a bundled database or an automatic seed script.
Field names illustrate the proposed registry; the final schema is not implemented yet.

| Client code | Name | Birth year | Email |
|---|---|---|---|
| demo-001 | Alex Morgan | 1985 | alex@example.invalid |
| demo-002 | Priya Rao | 1990 | priya@example.invalid |
| demo-003 | Jordan Lee | 1978 | jordan@example.invalid |

Each advisor will keep their actual database outside the public repository. MCP access to the
registry is planned after the storage API is implemented.

## Languages

**Available today:** English workbook labels and chart interface text.
**In progress:** multilingual Excel reports. The broader localization goal covers:

- Excel and future HTML/PDF report headings, sheet names, instructions and template text.
- Chart titles, controls, annotations and number, currency and date formatting.
- Client-registry field labels, descriptions, forms and user-facing views.
- Validation messages, tool descriptions shown by MCP clients, guides and demonstration materials.
- Future web interface labels and help text.

SQL column names, JSON keys and API identifiers will remain stable across languages.
Client names and other user-entered text are not automatically translated. Localized wording
does not imply support for a country's tax or pension rules. Additional languages and these
broader interfaces are roadmap items until their implementation is published.

## Model boundaries & next steps

The current model does not perform FX conversion or implement jurisdiction-specific taxes or
transaction fees. Inputs must already reflect externally modelled taxes and fees.
Monte Carlo probabilities describe the supplied model and assumptions, not guaranteed outcomes.

Retirement consumption **CE, gamma and equivalent-alpha helpers** exist as a separate module;
they are not yet integrated into forecasts, MCP or reports.
[Method and applicability →](docs/retirement-utility.md)

Next steps include the client registry, broader MCP exports and multilingual presentation.
A web interface is a later direction. The standalone package contains no private client data,
MBK documents, internal skills or dependency on the closed lfp application.

Explore the family: [okama library](https://github.com/mbk-dev/okama) ·
[okama.io](https://okama.io/) · [okama-mcp](https://github.com/mbk-dev/okama-mcp).
