# Neutral Excel reports

The optional report exporter creates a new English workbook from a complete request and
its saved forecast result. It does not use a pre-existing workbook, private registry or
external template. The neutral layout, code and synthetic examples are distributed under
the repository's MIT license. Keep that license when redistributing or modifying them.

Install the optional dependencies in the same environment as Planner:

```bash
poetry install --extras reports
poetry run python examples/reports.py
```

The example writes two differently branded reports and locally drawn example logos to
`tmp/neutral-reports/`. Every number comes from the public synthetic requests/results in
`examples/`; all example company names, logos and `.invalid` contacts are fictional.

```python
from okama_planner.reports import ReportBrand, export_report

export_report(
    [{"label": "Baseline", "request": request, "result": result},
     {"label": "Deferred purchase", "request": other_request, "result": other_result}],
    "my-plan.xlsx",
    brand=ReportBrand(company="Example Advisory", contact="team@example.invalid",
                      color="244C66", logo=None),
)
```

`logo` accepts a local image path; it is never downloaded. Colors are six hexadecimal
digits without `#`. Company, contacts, accent color and logo affect presentation only.
Edit Branding B2/B3 to update its text/contact reference; rerun the exporter to update
headings, colors and logos. The workbook explains editable cells. Supplied text is stored
as text, including strings beginning with `=`. The output contains no external workbook
references, macros or hidden source data.

## Reading the workbook

- Summary shows baseline plan success, terminal portfolio median and selected mode.
- Budget contains baseline **planned** monthly ledger flows, a formula sum and the flow reaching the
  portfolio after reserve movements. Expenses are negative; other flows include goals,
  loan payments and asset receipts. These are different from income minus expenses alone.
- Balance contains separate baseline portfolio and net-capital median series. For schema
  1.1, buffer, reserve, non-working assets and debt are actual scenario medians from saved
  monthly summaries, including opening balances. Failed purchases do not create property.
  Legacy 1.0 uses deterministic side balances and omits their opening point. A net-capital
  median is not a sum of component medians.
- Goals shows actual fully funded probability, funded/unmet mean totals and funding basis
  for schema 1.1. A pension's full-stream probability covers every payment, not just its
  first month; its displayed nominal amount is the first required payment. Legacy 1.0
  retains its before-goal affordability and survival columns.
- Assumptions contains both complete normalized plans and numerical provenance. Large
  return histories remain in the original JSON requests; their hashes are recorded.
- Comparison contains both scenarios' success/terminal portfolio metrics and formula
  differences. Both scenarios must use the same currency, start and horizon. It does not
  rank investments when the scenarios change cash flows, goals or their timing.
- Ledger preserves baseline individual signed **planned requirement** lines. In 1.1, neither
  Ledger nor Budget is an account of actual payments or actual balances. Funding events
  records actual required/funded/unmet means and funding sources instead.
- Segments and Segment balances show each scenario's opening allocation, full-funding
  probability, completion rule and account percentile series. In joint single mode these
  segments are display attribution within one pooled portfolio.
- Allocation shows explicit dated asset weights, active strategies, dated surplus weights,
  source/priority order, transfer policy and other supplied rules. Transfers records actual
  shortfall/completion movements. Different strategies expose different risk; the formatter
  does not invent a risk score.
- Comparison adds actual funding/unmet differences per goal, full-stream differences for
  pensions and history/scenario-row hashes. Differences are second scenario minus baseline;
  matching hashes document shared random draws. They do not remove risk/policy differences.
- Instructions explains
  editing, licensing, units, formula recalculation and model boundaries.

All monetary values are nominal in the request currency; probabilities and rates are
fractions. Budget and Comparison formula values require recalculation in Excel or
LibreOffice before readers relying on cached values can consume them. Planner's forecast
numbers are fixed results, not spreadsheet formulas: changing the workbook does not rerun
Monte Carlo. Change the complete request, run `forecast`, then export its new result.

The request hash checks that a result declares the matching input; it is not a signature
authenticating arbitrary result files. Keep request/result JSON together. Brand changes
do not modify those files or the stored numerical results.

## Financial and country boundaries

The exporter accepts saved schema 1.0 single results and schema 1.1 joint single/per_goal
results. The richer family comparison is available with:

```bash
poetry run python examples/portfolio_modes.py
```

Its requests and results are entirely synthetic; it samples synchronized history rows once
for both modes and exports `tmp/portfolio-modes/portfolio-modes.xlsx`. The optional paired
`--single-request` / `--per-goal-request` arguments replay complete external requests; use
`--output-dir` to keep their snapshots in their own directory.

Fixed-rate savings accounts are reserve accounts. No utility indicators are added to joint
reports; the legacy 1.0 placeholder rows remain for compatibility. No FX, country-specific
tax rules or legal declarations are inferred by the formatter. Supported fees, payments
and assumptions must be explicitly present in the input; formatting does not add a model.

These templates provide a report interface, not an Excel input editor or a country-specific
advisory document. Russian localization is a separate packaging step.

## Export charts separately

Responsive offline HTML (default), PNG and SVG chart exports are also available via
`okama_planner.charts.export_charts`, without the optional Excel dependencies.
See [Forecast chart exports](charts.md) for the API, examples and browser requirements.
