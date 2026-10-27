# Release images

## Local client database interface

`client-database-interface.png` is the 0.5.0 release hero: the client card with the meeting
journal, and the registry table with three fictional clients. It is a headless Chrome capture
of `python -m okama_planner.client_form` running against a temporary SQLite file created for
the capture. The records are Alex Morgan, Priya Rao and Jordan Lee — the same fictional
clients that appear in the README table; addresses use the reserved `.invalid` domain.

The entries never need to leave the capture directory, and each capture run builds its own
database. No real client database, folder or screenshot is used, and the shipped
`empty.sqlite3` template stays empty. Regenerate the image with:

```bash
poetry run python docs/images/capture-client-database.py
```

Chrome or Chromium and Pillow are required. The script seeds the database, starts the local
form, captures the journal and registry views at 2× device scale, composes them into
2500 × 1420 pixels and stops the server.

# README hero

## Financial plan

`financial-plan-three-goals.png` is the updated synthetic USD example prepared in lfp,
exported by Planner's ECharts renderer. The published input, result and dated assumptions
are `examples/readme-request.json`, `examples/readme-result.json` and
`examples/readme-metadata.json`. No real client data or private workbook is included.

The three goals are Car (2029-10), Home purchase (2031-10) and Early retirement (2040-10).
The forecast starts in October 2026 and runs for 44 years. Household amounts are fictional;
portfolio returns are frozen historical observations in USD. The saved independent validation
uses 5,000 paths, seed 1707, and gives a success probability of 95.92%. This is a model result,
not a guarantee. The metadata records the selection and validation procedure.

The logarithmic portfolio PNG is 2400 × 1440 pixels (2× rendering), using the exporter's
standard bounds. Zero and negative values are omitted on a log axis.

Regenerate the image from the saved result, without recalculating or downloading market data:

```bash
poetry run python - <<'PYTHON'
import json
from pathlib import Path
from shutil import copyfile
from okama_planner.charts import export_charts
result = json.loads(Path("examples/readme-result.json").read_text())
export_charts(result, "tmp/readme-hero", format="png", language="en",
              logarithmic=True, width=1200, height=720)
copyfile("tmp/readme-hero/portfolio.png", "docs/images/financial-plan-three-goals.png")
PYTHON
```

Chrome or Chromium is required for PNG rendering. To recalculate the forecast, pass the
saved request to `forecast`; retain the dated metadata with the saved result.
