# README hero

`financial-plan-three-goals.png` is rendered by the actual Planner ECharts exporter from
`examples/readme-result.json`. The request derives from the public synthetic family example
with an added education goal; no real client data or private workbook is used.

The logarithmic portfolio chart uses a display range of USD 100–1,000,000 and a 420-pixel
chart height. The underlying forecast is unchanged. Goal numbers follow request order:
education, home purchase, retirement. Zero/negative values are omitted on a log axis.

From the repository root, with the project's numerical environment:

```bash
poetry run python - <<'PY'
import json
from pathlib import Path
from okama_planner import forecast
from okama_planner.charts import export_charts
request = json.loads(Path("examples/readme-request.json").read_text())
result = forecast(request)
Path("examples/readme-result.json").write_text(json.dumps(result, indent=2) + "\n")
export_charts(result, "tmp/readme-charts")
PY
node examples/readme_hero.cjs
```

The image helper requires a development installation of Playwright and Chrome/Chromium,
like the existing chart browser checks. Set `PLAYWRIGHT_MODULE` and `CHROME_PATH` if needed.
It verifies three goal annotations and the log axis before exporting. It closes its browser.
