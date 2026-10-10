"""Export saved forecast series without recalculating or exposing other plan data."""

import json
import os
import re
import shutil
import struct
import time
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"
BROWSER = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def assert_child_stopped(pid: int) -> None:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        try:
            if Path("/proc").is_dir():
                if "State:\tZ" in Path(f"/proc/{pid}/status").read_text():
                    return
            os.kill(pid, 0)
        except (FileNotFoundError, ProcessLookupError):
            return
        time.sleep(0.01)
    pytest.fail("Browser child is still running after renderer cleanup")


def saved_result(name: str = "baseline") -> dict:
    return json.loads((EXAMPLES / f"{name}-result.json").read_text())


def payload(document: str) -> dict:
    match = re.search(r'<script id="forecast-data" type="application/json">(.*?)</script>', document, re.S)
    assert match is not None
    return json.loads(match[1])


def test_default_html_preserves_both_forecasts_and_omits_other_plan_data(tmp_path: Path) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    original = deepcopy(result)
    result["private_note"] = "DO NOT PUBLISH ME"
    outputs = export_charts(result, tmp_path / "charts")
    assert outputs == [tmp_path / "charts" / "forecast.html"]
    document = outputs[0].read_text()
    data = payload(document)
    assert data["currency"] == "USD"
    assert len(data["charts"]["portfolio"]) == 73
    assert data["charts"]["portfolio"][0] == {
        "month": "2025-12", "p10": 75000.0, "p25": 75000.0, "p50": 75000.0,
        "p75": 75000.0, "p90": 75000.0,
    }
    assert data["charts"]["portfolio"][-1]["p50"] == pytest.approx(25291.057126370935)
    assert data["charts"]["capital"][-1]["p50"] == pytest.approx(47555.624431852244)
    assert "DO NOT PUBLISH ME" not in document
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)=', document)
    result.pop("private_note")
    assert result == original


@pytest.mark.parametrize("name", ["family-single", "family-per-goal"])
def test_joint_forecasts_are_exported_without_reconstructing_capital(tmp_path: Path, name: str) -> None:
    from okama_planner.charts import export_charts

    result = saved_result(name)
    assert result["schema_version"] == "1.1"
    result["charts"]["capital"][0] = {
        "month": result["charts"]["capital"][0]["month"],
        "p10": -500.0, "p25": -200.0, "p50": -100.0, "p75": 0.0, "p90": 200.0,
    }
    document = export_charts(result, tmp_path)[0].read_text()
    data = payload(document)
    assert data["charts"]["capital"][0]["p50"] == -100.0
    assert data["charts"] == result["charts"]


@pytest.mark.parametrize("mutation", ["missing", "nonfinite", "unordered", "months", "date", "schema"])
def test_bad_saved_series_are_rejected_before_creating_files(tmp_path: Path, mutation: str) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    if mutation == "missing":
        del result["charts"]["capital"][0]["p25"]
    elif mutation == "nonfinite":
        result["charts"]["portfolio"][0]["p10"] = float("nan")
    elif mutation == "unordered":
        result["charts"]["portfolio"][0]["p10"] = 100000
    elif mutation == "months":
        result["charts"]["capital"].pop()
    elif mutation == "date":
        result["charts"]["portfolio"][0]["month"] = "2025-13"
    else:
        result["schema_version"] = "9.0"
    target = tmp_path / "bad"
    with pytest.raises(ValueError):
        export_charts(result, target)
    assert not target.exists()


@pytest.mark.parametrize("kwargs", [{"format": "pdf"}, {"width": 0}, {"height": 100}, {"width": True}])
def test_invalid_export_options_fail_before_writing(tmp_path: Path, kwargs: dict) -> None:
    from okama_planner.charts import export_charts

    with pytest.raises(ValueError):
        export_charts(saved_result(), tmp_path / "bad", **kwargs)
    assert not (tmp_path / "bad").exists()


@pytest.mark.skipif(BROWSER is None, reason="Chrome or Chromium required for static exports")
@pytest.mark.parametrize("format", ["png", "svg"])
def test_direct_exports_render_two_real_images_at_requested_dimensions(tmp_path: Path, format: str) -> None:
    from okama_planner.charts import export_charts

    outputs = export_charts(saved_result(), tmp_path, format=format, width=900, height=540)
    assert [p.name for p in outputs] == [f"portfolio.{format}", f"capital.{format}"]
    for file in outputs:
        content = file.read_bytes()
        if format == "png":
            from PIL import Image

            assert content[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", content[16:24]) == (1800, 1080)
            with Image.open(file) as image:
                colors = image.convert("RGB").getcolors(image.width * image.height)
            assert sum(count for count, color in colors if color == (42, 120, 214)) > 300
        else:
            root = ElementTree.fromstring(content)
            assert root.tag == "{http://www.w3.org/2000/svg}svg"
            assert root.attrib["viewBox"] == "0 0 900 540"
            assert len(root.findall(".//{http://www.w3.org/2000/svg}path")) > 5
            text = " ".join(root.itertext())
            assert "2028" in text
            assert "p90" in text
            expected_median = "$25,291" if file.stem == "portfolio" else "$47,556"
            assert expected_median in text
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"capital.{format}", f"portfolio.{format}"]


def test_missing_browser_has_actionable_error_without_creating_files(tmp_path: Path) -> None:
    from okama_planner.charts import export_charts

    with pytest.raises(RuntimeError, match="Chrome or Chromium"):
        export_charts(saved_result(), tmp_path / "bad", format="png", browser_executable="no-such-browser")
    assert not (tmp_path / "bad").exists()


@pytest.mark.skipif(BROWSER is None, reason="Chrome or Chromium required for browser checks")
def test_browser_success_without_images_is_rejected_and_temporary_files_removed(tmp_path: Path) -> None:
    import sys

    from okama_planner.charts import export_charts

    # A real subprocess exits successfully but cannot render charts: exit zero is not a receipt.
    with pytest.raises(RuntimeError, match="did not produce both images"):
        export_charts(saved_result(), tmp_path / "failed", format="svg", browser_executable=sys.executable)
    assert list((tmp_path / "failed").iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_render_timeout_stops_owned_browser_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import signal
    import sys

    import okama_planner.charts as charts

    launcher = tmp_path / "browser"
    pid_file = tmp_path / "child.pid"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(30)\n"
    )
    launcher.chmod(0o700)
    monkeypatch.setattr(charts, "_BROWSER_TIMEOUT", 1)
    child_pid = None
    try:
        with pytest.raises(RuntimeError, match="timed out"):
            charts.export_charts(
                saved_result(), tmp_path / "failed", format="png", browser_executable=launcher
            )
        child_pid = int(pid_file.read_text())
        assert_child_stopped(child_pid)
        assert list((tmp_path / "failed").iterdir()) == []
    finally:
        if child_pid is None and pid_file.exists():
            child_pid = int(pid_file.read_text())
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group cleanup")
def test_unsuccessful_browser_exit_stops_owned_children(tmp_path: Path) -> None:
    import signal
    import sys

    from okama_planner.charts import export_charts

    launcher = tmp_path / "browser"
    pid_file = tmp_path / "child.pid"
    launcher.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"Path({str(pid_file)!r}).write_text(str(child.pid))\n"
        "sys.exit(7)\n"
    )
    launcher.chmod(0o700)
    child_pid = None
    try:
        with pytest.raises(RuntimeError, match="did not produce both images"):
            export_charts(saved_result(), tmp_path / "failed", format="png", browser_executable=launcher)
        child_pid = int(pid_file.read_text())
        assert_child_stopped(child_pid)
        assert list((tmp_path / "failed").iterdir()) == []
    finally:
        if child_pid is None and pid_file.exists():
            child_pid = int(pid_file.read_text())
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize('name', ['baseline', 'family-single', 'family-per-goal'])
def test_goal_markers_select_only_saved_labels_dates_and_numbers(tmp_path: Path, name: str) -> None:
    from okama_planner.charts import export_charts

    result = saved_result(name)
    result['goals'][0]['private_note'] = 'DO NOT EMBED'
    data = payload(export_charts(result, tmp_path)[0].read_text())
    assert data['goals'] == [
        {'number': index, 'label': goal['label'], 'month': goal['month']}
        for index, goal in enumerate(result['goals'], 1)
    ]
    assert 'DO NOT EMBED' not in json.dumps(data)


def test_goal_markers_keep_saved_number_when_dates_are_outside_horizon(tmp_path: Path) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    result['goals'][0]['month'] = '2020-01'
    data = payload(export_charts(result, tmp_path)[0].read_text())
    assert data['goals'] == [{'number': 2, 'label': result['goals'][1]['label'], 'month': '2029-01'}]
    del result['goals']
    assert payload(export_charts(result, tmp_path)[0].read_text())['goals'] == []


@pytest.mark.parametrize('bad', [None, {}, [{'label': 'Goal', 'month': '2028-13'}],
                                   [{'label': 123, 'month': '2028-01'}]])
def test_invalid_goal_metadata_is_rejected_before_writing(tmp_path: Path, bad: object) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    result['goals'] = bad
    with pytest.raises(ValueError):
        export_charts(result, tmp_path / 'invalid')
    assert not (tmp_path / 'invalid').exists()


def test_license_notices_are_embedded_without_visible_ui_and_labels_are_safe(tmp_path: Path) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    result['goals'][0]['label'] = '</script><img src=x onerror=alert(1)>'
    document = export_charts(result, tmp_path)[0].read_text()
    assert '<details>' not in document
    assert '<pre hidden id="license-notices">' in document
    assert 'Apache License' in document
    assert '</script><img' not in document
    assert payload(document)['goals'][0]['label'] == result['goals'][0]['label']


def test_log_export_initializes_scale_and_localizes_captions(tmp_path: Path) -> None:
    from okama_planner.charts import export_charts

    document = export_charts(saved_result(), tmp_path, logarithmic=True, language="ru")[0].read_text()
    data = payload(document)
    assert data["logarithmic"] is True
    assert data["labels"]["Portfolio forecast"] == "Прогноз портфеля"
    assert 'scales.set(key, input.logarithmic === true)' in document
    assert '<html lang="ru">' in document


@pytest.mark.skipif(BROWSER is None, reason="Chrome or Chromium required for static exports")
def test_log_static_export_changes_projection_and_keeps_zero_as_gaps(tmp_path: Path) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    for key in ("portfolio", "capital"):
        result["charts"][key][0] = {"month": "2025-12", "p10": -100, "p25": 0,
                                    "p50": 100, "p75": 500, "p90": 1000}
    linear = export_charts(result, tmp_path / "linear", format="svg")
    log = export_charts(result, tmp_path / "log", format="svg", logarithmic=True)
    assert linear[0].read_text() != log[0].read_text()
    assert "NaN" not in log[0].read_text()


@pytest.mark.parametrize("language,currency", [
    ("en", "EUR"), ("ru", "USD"), ("de", "RUB"), ("es", "CNY"),
])
def test_chart_units_follow_saved_result_independently_of_language(
    tmp_path: Path, language: str, currency: str,
) -> None:
    from okama_planner.charts import export_charts

    result = saved_result()
    result["currency"] = currency
    document = export_charts(result, tmp_path, language=language)[0].read_text()
    assert payload(document)["currency"] == currency
    assert payload(document)["language"] == language
