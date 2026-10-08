"""Export saved synthetic forecasts as offline HTML (default), PNG or SVG."""

import argparse
import json
from pathlib import Path

from okama_planner.charts import export_charts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, default=Path(__file__).parent / "baseline-result.json")
    parser.add_argument("--format", choices=("html", "png", "svg"), default="html")
    parser.add_argument("--out", type=Path, default=Path("tmp/forecast-charts"))
    parser.add_argument("--width", type=int, default=1200, help="Static image width in CSS pixels")
    parser.add_argument("--height", type=int, default=720, help="Static image height in CSS pixels")
    parser.add_argument("--browser-executable", type=Path, default=None)
    args = parser.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    for path in export_charts(
        result, args.out, format=args.format, width=args.width, height=args.height,
        browser_executable=args.browser_executable,
    ):
        print(path)


if __name__ == "__main__":
    main()
