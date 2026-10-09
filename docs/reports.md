# Neutral Excel reports

The optional report exporter creates a new workbook (English by default) from a complete request and
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
    language="en",  # en, ru, zh (Simplified Chinese), de, es
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
- Current amounts shows supplied assets, liabilities, goals and monthly budgets in the
  request currency. Expense-share goals are explicitly marked and formatted as ratios.
- Cash Flow is the main annual budget view: calendar years run across columns. Planned
  household flows are summed from Ledger with formulas; year-end balances select the last
  available month of each year, including partial years. Goal and income captions come from
  inputs. Income labels differing only in letter case share one annual row, matching
  Excel SUMIFS comparison semantics; original input captions remain in Current amounts
  and Ledger. Opening ages appear only when birth years are supplied. No total-assets median or
  investment income is inferred by adding marginal percentiles. Technical Budget retains
  the monthly detail.
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
- Instructions explains editing, units, formula recalculation and model boundaries.
  License information stays in this repository and is not embedded in the workbook.

All monetary values are nominal in the request currency. Inflation indexation is already
included according to the request's inputs; nominal values are not deflated into constant
purchasing power. Probabilities and rates are
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
advisory document.

## Language editions and Excel charts

`language` selects `en`, `ru`, `zh`, `de` or `es`. The single packaged
[`terminology.csv`](../src/okama_planner/terminology.csv) table has columns
`key,en,ru,zh,de,es`; edit that table to maintain translated captions and instructions.
Localized sheet names keep their formula references. User-supplied company, scenario,
goal and ledger labels remain exactly as supplied, as do technical assumption/provenance
keys and machine-readable enum identifiers. Chinese sheets use Microsoft YaHei; Excel
may substitute an installed CJK font. Table sheets freeze only their header rows, while
chart sheets have no frozen panes.

`export_report(..., chart_images=...)` optionally embeds local PNGs on four separate
localized sheets. The accepted keys are `portfolio`, `portfolio_log`, `capital` and
`capital_log`; each value is a local image path. The report exporter itself starts no
browser. Produce the images using the same ECharts renderer as the standalone charts:

```python
from okama_planner.charts import export_charts

images = {}
for logarithmic in (False, True):
    paths = export_charts(result, f"charts/{logarithmic}", format="png",
                          language="de", logarithmic=logarithmic)
    images.update({p.stem + ("_log" if logarithmic else ""): p for p in paths})
export_report(scenarios, "plan-de.xlsx", language="de", chart_images=images)
```

The blue median and nested p25–p75 / p10–p90 bands use actual saved percentile values.
Logarithmic exports omit zero and negative points, with gaps rather than epsilon values.
If either forecast has no positive values, requesting a log export raises `ValueError`.
Numbered goal annotations below each Excel chart identify the saved goal labels and dates.
Run `poetry run python examples/multilingual_reports.py` to create all five synthetic
language editions with four charts each in `tmp/multilingual-reports/`; PNG generation
requires a local Chrome or Chromium installation.

Language does not choose the currency in the report API: every unit comes from the validated
request/result. The demonstration maps English to USD, Russian to RUB, Chinese to CNY and
German/Spanish to EUR. Each uses independently authored synthetic amounts and base-currency
return histories, never a relabelled USD result. Plans start in October 2026, retire in 2040
and include 30 withdrawal years. Each fictional household includes an investment portfolio,
an emergency reserve, long-term savings, an apartment, an existing car and a mortgage.
Income is about three times household expenses. Goals are a car in 2029, a home in 2031
and early retirement in 2040, replacing 100% of indexed household expenses. The existing
car is sold when its replacement is bought. No state pension starts at early retirement.
Separate car/home savings accounts use explicitly assumed reference rates. This public
adaptation does not reproduce a private custom bond-purchase/reserve policy. The RUB
demonstration is independently fictional, not a client's reference workbook.

The example increases only opening investment capital by default until the fixed selection
seed reaches 92% full-plan success, then evaluates the unchanged plan once with an independent
seed and requires at least 90%. It uses 5,000 paths per run, normal draws, matched historical
moments, selection seed 707 and validation seed 1707. The search uses fixed 25% increases,
rounded up to hundreds, stops at the first passing candidate, and refuses to exceed 32 times
the baseline. It never changes goals, dates, expenses, rates or the withdrawal horizon and
does not search for a favourable seed. Independent validation failure aborts generation.
These percentages describe this simulation, not a guarantee of real-world outcomes.

`--calibrate-parameter income` instead changes only monthly employment income.
`--target-success` changes the validation threshold (selection keeps a two-percentage-point
margin). `--mc-number` accepts at least 2,000 paths. `--forecast-only` saves complete validated
request/result/metadata JSON files without rendering charts or workbooks. Metadata records
the baseline and calibrated value, every selection attempt and independent validation result;
the result retains its actual input SHA256 and full forecast. Report assumptions display
the baseline, chosen parameter, final value, targets, seeds and validation probability.
For legacy separate-account plans, Cash Flow also shows each goal account's deterministic
year-end balance and annual contributions. Contributions sum `buffer_in` ledger entries,
filtered by goal ID (literal labels for older ledgers), after portfolio transfers. These
internal savings transfers are informational and are excluded from household income and
expense totals; purchase outflows are counted once. The account balances are fixed-rate
ledger balances, not additional Monte Carlo quantiles.

[`currency-assumptions.json`](../examples/currency-assumptions.json) records the dated geometric
10-year inflation mean, reference rate, sources, return/risk moments and complete monthly
portfolio samples. All indexation rates use that inflation mean; buffer interest uses the
reference rate as an explicit example assumption. USD uses the effective federal funds rate,
EUR the ECB deposit facility rate, RUB the central-bank rate. CNY uses the user-selected
one-year lending prime rate, explicitly distinguished from a policy or risk-free rate.
Every currency uses the same USD asset mix, with historical returns measured in that currency.
Exposure is unhedged; the RUB example does not reproduce a domestic RUB portfolio mix.
FX observations are retained as provenance; the authored amounts are not converted with them.
Visible Economic data rows in Assumptions expose rates and portfolio moments as percentages.
Reproduce the dated snapshot with `poetry run python examples/collect_currency_assumptions.py`;
its default output is `tmp/currency-assumptions/`. A snapshot without a reference rate is rejected; update its dated input explicitly before
generating another edition.

## Export charts separately

Responsive offline HTML (default), PNG and SVG chart exports are also available via
`okama_planner.charts.export_charts`, without the optional Excel dependencies.
See [Forecast chart exports](charts.md) for the API, examples and browser requirements.
