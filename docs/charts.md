# Forecast chart exports

Export saved portfolio and net-capital forecasts separately from Excel. The default is a
self-contained **HTML** file: ECharts and the plotted data are embedded, so opening it does
not contact a server. **PNG** and **SVG** are also available directly.

```bash
poetry run python examples/charts.py
poetry run python examples/charts.py --format png --out tmp/forecast-charts/png
poetry run python examples/charts.py --format svg --out tmp/forecast-charts/svg
```

The example uses the public synthetic baseline result. To plot another saved forecast:

```bash
poetry run python examples/charts.py --result examples/family-per-goal-result.json
```

Or use the Python API:

```python
from okama_planner.charts import export_charts

paths = export_charts(result, "my-charts")  # my-charts/forecast.html
paths = export_charts(result, "my-charts/png", format="png", width=1200, height=720)
paths = export_charts(result, "my-charts/svg", format="svg", width=1200, height=720)
paths = export_charts(result, "my-charts/log", format="png", logarithmic=True, language="ru")
```

HTML automatically adapts the charts to the window's width and height. There is no size
selector: resize the window to change proportions. Hover to see all five percentiles.
Each chart has an independent **Logarithmic scale** checkbox and PNG/SVG save buttons
beneath the plot. Controls wrap on narrow windows and occupy their own layout space.
The downloaded image uses the current chart dimensions, selected scale and goal markers.
The direct PNG/SVG exports write `portfolio.png` / `capital.png` or `portfolio.svg` /
`capital.svg`. Direct image dimensions are configurable in CSS pixels (width 320–3840,
height 240–2160). PNG is exported at **2x** resolution, matching okama-web; a 1200 × 720
chart produces a 2400 × 1440 PNG. SVG is vector with a matching viewBox.

## Rendering

The charts use **Apache ECharts 6.1.0**, the same version and fan-chart styling as
okama-web's Portfolio Monte Carlo forecast: blue `#2a78d6` median at 2.5 px,
gradient bands p10–p90 (opacity 0.12) and p25–p75 (0.25), monetary axis on the right,
adaptive calendar labels and endpoint percentile labels on wider screens. On narrow
screens the endpoint labels are hidden and the tooltip retains all values.

HTML exports need no extra Python packages or browser installation at export time.
Direct PNG/SVG rendering requires Chrome or Chromium on `PATH`. A nonstandard location
can be supplied through `browser_executable` or `--browser-executable`. Rendering uses
an isolated temporary browser profile, not your existing browser session; intermediate
files are removed after rendering. Nothing is uploaded. The existing Python forecast API,
MCP tools and Excel reports remain compatible; exporting charts does not run Monte Carlo.

The vendored ECharts distribution and license notices are included in the package and HTML.
HTML retains license notices in a hidden element without a visible license panel.
ECharts is Apache-2.0; third-party notices are retained alongside the distribution. Planner's
own exporter remains MIT. The bundle version/source/checksum are documented in
`src/okama_planner/_chart_assets/README.md`.

## Data meaning

Both result schema 1.0 and joint single/per_goal schema 1.1 are supported. Only the currency
and saved monthly chart series plus goal labels/dates enter the HTML, not client inputs,
contact details, provenance or return histories. Chart data must contain consecutive months, matching
portfolio/capital dates, finite values and ordered percentiles; invalid data is rejected
before output files are written. Optional `goals` metadata must be a list with string labels
and valid `YYYY-MM` dates. If absent, no goal markers are shown. Dates outside the chart
horizon are omitted from both markers and annotations; remaining goals retain their
original numbers from the saved goal order. Goal IDs, amounts and funding metrics are not embedded.

All values are nominal in the saved result currency. The graphs plot the two saved
percentile series independently; capital is never reconstructed by adding component
medians. Negative net capital is preserved, and the bands stack across zero correctly.
Dashed vertical goal lines use the saved goal outcome month (purchase date or first
retirement withdrawal month). Lines show only their numbers; annotations beneath each
chart show `1 — goal label (YYYY-MM)`, `2 — goal label (YYYY-MM)`, and so on.
Coincident dates have staggered numbers. There is no opening-point annotation.
Collapsed or depleted forecasts remain visible.

Linear mode preserves every saved percentile, including zero and negative values.
Logarithmic mode uses a base-10 axis beginning at the smallest positive saved percentile:
nonpositive percentile points and band intervals
with nonpositive lower endpoints are gaps, with an explanatory note beneath the plot.
The underlying data and tooltip values remain unchanged. Log bands project the actual
saved low/high endpoints, rather than stacking additive differences on a log axis.
A chart with no positive values has a disabled logarithmic checkbox and an explanation.
The `logarithmic=True` export option initializes both plots in logarithmic mode, including
direct PNG/SVG rendering. It rejects an all-nonpositive forecast before writing files.
`language` supports `en` (default), `ru`, `zh`, `de` and `es`, using the shared packaged
terminology table. Saved goal labels are preserved. Inflation indexation follows the
supplied inputs; the nominal figures are not expressed in constant purchasing power.
These exports format saved data; they do not authenticate result files or change any financial assumptions.

## Developer verification

`poetry run pytest -q` covers both saved-result schemas, validation and direct PNG/SVG
rendering when Chrome/Chromium is available. Static render tests skip explicitly when
neither browser is installed. The browser check uses a development installation of
Playwright (no npm package is required by the exporter):

```bash
poetry run python examples/charts.py
node tests/browser/check_chart_options.cjs
node tests/browser/check_charts.cjs tmp/forecast-charts/forecast.html tmp/browser-charts
```

Set `PLAYWRIGHT_MODULE` to the module's absolute location when it is installed in another
development checkout; set `CHROME_PATH` for another Chromium executable. This check opens
the HTML with networking disabled, validates stacked band endpoints, downloads both formats,
validates independent log scales and actual band polygon coordinates, downloads log
PNG/SVG, checks goal markers and license UI, exercises six aspect ratios for control
overlap, checks mobile calendar-label bounds, and saves linear/log desktop and mobile screenshots.
The fast option check also covers cross-zero log band gaps, disabled depleted forecasts,
coincident goals and safe annotation text without launching a browser. It also uses the
real bundled ECharts SVG renderer to verify monetary axis limits and polygon coordinates
after skipping a nonpositive interval. The Playwright
check closes its own browser after the checks.

Schema 2.0 exports an overall base-currency view and separate native group views; see [Multi-currency plans](multicurrency.md).
