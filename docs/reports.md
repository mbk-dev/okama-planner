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
- Budget contains baseline monthly ledger flows, a formula sum and the flow reaching the
  portfolio after reserve movements. Expenses are negative; other flows include goals,
  loan payments and asset receipts. These are different from income minus expenses alone.
- Balance contains separate baseline portfolio and net-capital median series, plus
  deterministic buffer, savings, non-working assets and debt. Opening component balances
  are omitted. A net-capital median is not a sum of component medians.
- Goals contains both scenarios' nominal goal amounts, affordability and survival.
- Assumptions contains both complete normalized plans and numerical provenance. Large
  return histories remain in the original JSON requests; their hashes are recorded.
- Comparison contains both scenarios' success/terminal portfolio metrics and formula
  differences. Both scenarios must use the same currency, start and horizon. It does not
  rank investments when the scenarios change cash flows, goals or their timing.
- Ledger preserves baseline individual signed cash-flow lines. Instructions explains
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

The current mode is one investment portfolio with accumulation and retirement stages.
Fixed-rate savings accounts are reserve accounts. Separate investment portfolios by goal,
gamma and equivalent annual alpha are unavailable; the workbook labels unavailable
indicators instead of inserting zero or a marketing coefficient. No FX, country-specific
tax rules or legal declarations are inferred by the formatter. Supported fees, payments
and assumptions must be explicitly present in the input; formatting does not add a model.

These templates provide a report interface, not an Excel input editor or a country-specific
advisory document. Russian localization is a separate packaging step.
