"""Exercise the offline example as a user would, including external request replay."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def run_example(output: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "examples" / "portfolio_modes.py"), "--output-dir", str(output), *args],
        cwd=ROOT, env={**os.environ, "MPLBACKEND": "Agg"}, capture_output=True, text=True, check=False,
    )


def test_synthetic_family_example_produces_shared_cube_funding_and_report(tmp_path: Path) -> None:
    run = run_example(tmp_path)
    assert run.returncode == 0, run.stderr
    comparison = json.loads((tmp_path / "comparison.json").read_text())
    assert comparison["provenance"]["sampled_once"] is True
    assert comparison["risk_structure"]["strategies_differ"] is True
    left, right = comparison["baseline"], comparison["variant"]
    assert left["provenance"]["scenario_rows_sha256"] == right["provenance"]["scenario_rows_sha256"]
    request = json.loads((tmp_path / "per-goal-request.json").read_text())
    assert len(request["plan"]["persons"]) == 3
    assert len(request["plan"]["budget_items"]) == 3
    assert [s["opening_amount"] for s in request["allocation"]["segments"]] == [0, 70000, 70000]
    assert len(right["goals"]) == 2
    assert right["goals"][1]["funding_basis"] == "full_stream"
    assert right["actual"]["event_funding"]
    assert (tmp_path / "portfolio-modes.xlsx").exists()
    replay = tmp_path / "replay"
    run = run_example(replay, "--single-request", str(tmp_path / "single-request.json"),
                      "--per-goal-request", str(tmp_path / "per-goal-request.json"))
    assert run.returncode == 0, run.stderr
    assert json.loads((replay / "comparison.json").read_text()) == comparison


def test_example_requires_both_external_requests(tmp_path: Path) -> None:
    run = run_example(tmp_path, "--single-request", "missing.json")
    assert run.returncode != 0
    assert "together" in run.stderr
    assert not (tmp_path / "comparison.json").exists()
