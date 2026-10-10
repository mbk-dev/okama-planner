"""Offline ECharts exports of saved portfolio and net-capital forecasts."""

from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import signal
import subprocess
from datetime import date
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from okama_planner.localization import locale_code, presentation_boundary, terminology

PERCENTILES = ("p10", "p25", "p50", "p75", "p90")
ASSETS = files("okama_planner").joinpath("_chart_assets")
_BROWSER_TIMEOUT = 60


def _chart_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Forecast charts must contain monthly points")
    selected = []
    previous = None
    for row in rows:
        month = row["month"]
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ValueError("Chart dates must use YYYY-MM")
        parsed = date.fromisoformat(f"{month}-01")
        index = parsed.year * 12 + parsed.month
        if previous is not None and index != previous + 1:
            raise ValueError("Chart months must be consecutive and ascending")
        previous = index
        values = [row[p] for p in PERCENTILES]
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in values
        ):
            raise ValueError("Chart percentiles must be finite numbers")
        if values != sorted(values):
            raise ValueError("Chart percentiles must be ordered p10 through p90")
        selected.append({"month": month, **dict(zip(PERCENTILES, values, strict=True))})
    return selected


def _chart_data(result: dict[str, Any]) -> dict[str, Any]:
    """Validate and select only plotted values; never embed the full financial plan."""
    try:
        if result["schema_version"] not in {"1.0", "1.1", "2.0"}:
            raise ValueError("Unsupported forecast schema")
        currency = result["currency"]
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("Forecast currency must be a three-letter code")
        charts = {key: _chart_rows(result["charts"][key]) for key in ("portfolio", "capital")}
        if [r["month"] for r in charts["portfolio"]] != [r["month"] for r in charts["capital"]]:
            raise ValueError("Portfolio and capital must use the same months")
        goals = result.get("goals", [])
        if not isinstance(goals, list):
            raise ValueError("Forecast goals must be a list")
        markers = []
        months = {row["month"] for row in charts["portfolio"]}
        for number, goal in enumerate(goals, 1):
            month = goal["month"]
            label = goal["label"]
            if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
                raise ValueError("Goal dates must use YYYY-MM")
            date.fromisoformat(f"{month}-01")
            if not isinstance(label, str):
                raise ValueError("Goal labels must be strings")
            if month in months:
                markers.append({"number": number, "label": label, "month": month})
        return {"currency": currency, "charts": charts, "goals": markers}
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Saved forecast is missing valid chart data") from error


def _document(data: dict[str, Any]) -> str:
    template = ASSETS.joinpath("page.html").read_text(encoding="utf-8")
    language = data.get("language", "en")
    labels = terminology(language)
    template = template.replace('<html lang="en">', f'<html lang="{language}">')
    for original, localized in sorted(labels.items(), key=lambda pair: -len(pair[0])):
        # Translate only the HTML template, before scripts/data/license notices are inserted.
        template = template.replace(original, localized)
    data = {**data, "labels": labels, "locale": locale_code(language)}
    engine = ASSETS.joinpath("echarts.min.js").read_text(encoding="utf-8")
    script = ASSETS.joinpath("charts.js").read_text(encoding="utf-8")
    licenses = "\n".join(
        ASSETS.joinpath(name).read_text(encoding="utf-8")
        for name in ("ECHARTS-LICENSE.txt", "ECHARTS-NOTICE.txt", "LICENSE-d3.txt")
    )
    # Script data must not be able to close its containing HTML element.
    encoded = json.dumps(data, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c")
    engine = engine.replace("</script", "<\\/script")
    return (
        template.replace("<!-- ECHARTS -->", f"<script>{engine}</script>")
        .replace("<!-- DATA -->", f'<script id="forecast-data" type="application/json">{encoded}</script>')
        .replace("<!-- APP -->", f"<script>{script}</script>")
        .replace("<!-- LICENSES -->", licenses.replace("&", "&amp;").replace("<", "&lt;"))
    )


class _RenderedData(HTMLParser):
    """Read the browser's render receipt rather than treating exit zero as success."""

    def __init__(self) -> None:
        super().__init__()
        self.reading = False
        self.content = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "pre" and dict(attrs).get("id") == "render-output":
            self.reading = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "pre":
            self.reading = False

    def handle_data(self, data: str) -> None:
        if self.reading:
            self.content += data


def _browser(executable: str | Path | None) -> str:
    if executable is not None:
        found = shutil.which(str(executable))
    else:
        found = next(
            (path for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge")
             if (path := shutil.which(name))),
            None,
        )
    if not found:
        raise RuntimeError(
            "PNG/SVG export requires Chrome or Chromium; use HTML or supply browser_executable"
        )
    return found


def _run_browser(command: list[str]) -> tuple[str, int]:
    """Terminate the isolated process group on failure, including browser children."""
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        start_new_session=os.name == "posix",
    ) as process:
        try:
            stdout, _ = process.communicate(timeout=_BROWSER_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Chart browser rendering timed out") from error
        finally:
            # A launcher can exit while children still run. Clean up on every outcome.
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.kill()
        return stdout, process.returncode


def _export_single_charts(
    result: dict[str, Any],
    output_dir: str | Path,
    *,
    format: Literal["html", "png", "svg"] = "html",
    width: int = 1200,
    height: int = 720,
    browser_executable: str | Path | None = None,
    logarithmic: bool = False,
    language: str = "en",
) -> list[Path]:
    """Write one responsive HTML or two images from a saved forecast, without running Monte Carlo.

    HTML includes ECharts and works offline. PNG/SVG use an isolated headless Chrome
    process, not a user's browser session. PNG uses 2x resolution; SVG is vector.
    Width/height specify static-image CSS pixels; HTML adapts to its window.
    """
    terminology(language)
    if type(logarithmic) is not bool:
        raise ValueError("logarithmic must be a boolean")
    if format not in {"html", "png", "svg"}:
        raise ValueError("Chart format must be html, png or svg")
    for name, value, lower, upper in (("width", width, 320, 3840), ("height", height, 240, 2160)):
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError(f"Chart {name} must be an integer between {lower} and {upper}")
    data = _chart_data(result)
    data["language"] = language
    data["logarithmic"] = logarithmic
    if logarithmic and any(not any(row["p90"] > 0 for row in rows) for rows in data["charts"].values()):
        raise ValueError("Logarithmic scale requires positive values in both forecasts")
    target = Path(output_dir)
    if format == "html":
        document = _document(data)
        target.mkdir(parents=True, exist_ok=True)
        destination = target / "forecast.html"
        destination.write_text(document, encoding="utf-8")
        return [destination]

    executable = _browser(browser_executable)
    data["render"] = {"format": format, "width": width, "height": height}
    document = _document(data)
    target.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".chart-render-", dir=target) as scratch:
        scratch_path = Path(scratch)
        page = scratch_path / "forecast.html"
        page.write_text(document, encoding="utf-8")
        stdout, returncode = _run_browser(
            [executable, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={scratch_path / 'profile'}",
             "--dump-dom", "--virtual-time-budget=1000", page.resolve().as_uri()]
        )
        parser = _RenderedData()
        parser.feed(stdout)
        try:
            images = json.loads(parser.content)
            rendered = {
                key: base64.b64decode(images[key], validate=True) if format == "png" else images[key].encode()
                for key in ("portfolio", "capital")
            }
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeError("Chart browser did not produce both images") from error
        if returncode != 0 or any(not content for content in rendered.values()):
            raise RuntimeError("Chart browser rendering failed")
    destinations = []
    for key, content in rendered.items():
        destination = target / f"{key}.{format}"
        destination.write_bytes(content)
        destinations.append(destination)
    return destinations


def _export_currency_charts(
    result: dict[str, Any], output_dir: str | Path, **options: Any,
) -> list[Path]:
    """Validate all native charts before writing them into safe group directories."""
    groups = result.get("currency_groups")
    if not isinstance(groups, list) or not groups:
        raise ValueError("Multi-currency forecasts require currency groups")
    seen = set()
    for group in groups:
        identifier = group.get("group_id")
        if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier)
                or identifier in seen):
            raise ValueError("Chart currency group IDs must be unique and safe directory names")
        seen.add(identifier)
        if group["currency"] != group["result"]["currency"]:
            raise ValueError("Chart group currency does not match its native result")
        _chart_data(group["result"])
    overall = {**result, "schema_version": "1.1"}
    _chart_data(overall)
    paths = export_charts(overall, output_dir, **options)
    for group in groups:
        paths.extend(export_charts(group["result"], Path(output_dir) / group["group_id"], **options))
    return paths


@presentation_boundary
def export_charts(
    result: dict[str, Any], output_dir: str | Path, *,
    format: Literal["html", "png", "svg"] = "html", width: int = 1200, height: int = 720,
    browser_executable: str | Path | None = None, logarithmic: bool = False, language: str = "en",
) -> list[Path]:
    """Export the saved family forecast and, for schema 2.0, each native currency group."""
    options = {"format": format, "width": width, "height": height,
               "browser_executable": browser_executable, "logarithmic": logarithmic, "language": language}
    if result.get("schema_version") == "2.0":
        return _export_currency_charts(result, output_dir, **options)
    return _export_single_charts(result, output_dir, **options)
