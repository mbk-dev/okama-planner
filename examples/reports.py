"""Create neutral synthetic reports with two independently configurable brands."""

import json
from pathlib import Path

from PIL import Image, ImageDraw

from okama_planner.reports import ReportBrand, export_report


def main() -> None:
    examples = Path(__file__).parent
    output = Path.cwd() / "tmp" / "neutral-reports"
    output.mkdir(parents=True, exist_ok=True)
    scenarios = [
        {
            "label": name.title(),
            "request": json.loads((examples / f"{name}-request.json").read_text()),
            "result": json.loads((examples / f"{name}-result.json").read_text()),
        }
        for name in ("baseline", "deferred")
    ]
    for name, company, contact, color in [
        ("neutral", "Example Advisory", "team@example.invalid", "244C66"),
        ("alternate", "Demo Planning", "hello@demo.invalid", "703080"),
    ]:
        logo = output / f"{name}-logo.png"
        image = Image.new("RGB", (288, 96), f"#{color}")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 20, 76, 76), outline="white", width=6)
        draw.line((100, 68, 140, 48, 180, 60, 240, 24), fill="white", width=6)
        image.save(logo)
        export_report(
            scenarios,
            output / f"{name}-plan.xlsx",
            brand=ReportBrand(company=company, contact=contact, color=color, logo=logo),
        )
    print(f"Two synthetic reports written to {output}")


if __name__ == "__main__":
    main()
