"""The language example exports one offline USD forecast without recalculating it."""

import json
import os
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).parents[1]


def test_localized_example_exports_same_saved_forecast_for_every_language(tmp_path: Path) -> None:
    run = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "localized_plan.py"), "--output-dir", str(tmp_path)],
        cwd=ROOT, env={**os.environ, "MPLBACKEND": "Agg"}, capture_output=True, text=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    request = json.loads((tmp_path / "request.json").read_text())
    result = json.loads((tmp_path / "result.json").read_text())
    assert request["currency"] == result["currency"] == "USD"
    assert request["seed"] == 42
    assert request["return_samples"]["accumulation"]["monthly_returns"]
    numbers = []
    for language in ("en", "ru", "de", "es", "zh"):
        book = load_workbook(tmp_path / f"plan-{language}.xlsx")
        numbers.append([
            cell.value for sheet in book for row in sheet for cell in row
            if isinstance(cell.value, (int, float))
        ])
        for scale in ("linear", "log"):
            html = (tmp_path / language / scale / "forecast.html").read_text()
            assert f'<html lang="{language}">' in html
            assert '"currency":"USD"' in html
    assert all(values == numbers[0] for values in numbers)
