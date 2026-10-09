"""Create five synthetic language editions with linear and log ECharts forecasts."""

import json
from pathlib import Path

from okama_planner.charts import export_charts
from okama_planner.localization import LANGUAGES
from okama_planner.reports import ReportBrand, export_report


def main() -> None:
    examples = Path(__file__).parent
    output = Path.cwd() / "tmp" / "multilingual-reports"
    scenarios = [
        {
            "label": name.title(),
            "request": json.loads((examples / f"{name}-request.json").read_text()),
            "result": json.loads((examples / f"{name}-result.json").read_text()),
        }
        for name in ("baseline", "deferred")
    ]
    for language in LANGUAGES:
        images = {}
        for logarithmic in (False, True):
            scale = "log" if logarithmic else "linear"
            paths = export_charts(scenarios[0]["result"], output / language / scale,
                                  format="png", logarithmic=logarithmic, language=language)
            images.update({path.stem + ("_log" if logarithmic else ""): path for path in paths})
        export_report(scenarios, output / f"plan-{language}.xlsx", language=language,
                      chart_images=images, brand=ReportBrand(contact=""))
    print(f"Five synthetic language editions written to {output}")


if __name__ == "__main__":
    main()
