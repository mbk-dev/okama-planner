"""Export the same fictional offline USD plan in five presentation languages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

# okama imports matplotlib eagerly; this example needs no display.
os.environ.setdefault("MPLBACKEND", "Agg")

from okama_planner import forecast
from okama_planner.charts import export_charts
from okama_planner.localization import LANGUAGES
from okama_planner.reports import ReportBrand, export_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "tmp" / "localized-example")
    parser.add_argument("--languages", nargs="+", choices=LANGUAGES, default=list(LANGUAGES))
    parser.add_argument("--image-format", choices=("png", "svg"),
                        help="Also render images with locally installed Chrome or Chromium")
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    request = json.loads((Path(__file__).parent / "baseline-request.json").read_text(encoding="utf-8"))
    # The frozen samples are authored synthetic observations, not live market history.
    # Language never selects a currency, changes inputs, or triggers another forecast.
    result = forecast(request)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, snapshot in (("request", request), ("result", result)):
        (args.output_dir / f"{name}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
    scenarios = [{"label": "Synthetic USD", "request": request, "result": result}]
    for language in args.languages:
        export_report(scenarios, args.output_dir / f"plan-{language}.xlsx",
                      language=language, brand=ReportBrand(contact=""))
        for logarithmic in (False, True):
            destination = args.output_dir / language / ("log" if logarithmic else "linear")
            export_charts(result, destination, language=language, logarithmic=logarithmic)
            if args.image_format:
                export_charts(result, destination, format=args.image_format, language=language,
                              logarithmic=logarithmic, browser_executable=args.browser_executable)
    print(args.output_dir)


if __name__ == "__main__":
    main()
