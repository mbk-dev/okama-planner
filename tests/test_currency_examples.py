"""Synthetic examples use dated currency-specific inputs, independently of presentation."""

import json
import runpy
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[1] / "examples"


def test_synthetic_request_uses_currency_specific_macro_history_and_independent_amounts() -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    request, metadata = module["build_request"]("EUR", snapshots)
    eur = snapshots["currencies"]["EUR"]
    assert request["currency"] == "EUR"
    assert request["plan"]["assets"][0]["amount"] == 130000
    assert request["plan"]["rates"]["inflation_rate"] == eur["inflation_rate"]
    assert request["plan"]["rates"]["buffer_rate"] == eur["risk_free_rate"]
    assert request["return_samples"]["accumulation"]["monthly_returns"] == (
        eur["portfolios"]["accumulation"]["monthly_returns"]
    )
    assert request["plan"]["t0"] == "2026-10"
    assert request["plan"]["withdrawal_years"] == 30
    assert metadata["currency"] == "EUR"
    assert "no FX conversion" in metadata["amount_method"]
    assert module["DEFAULT_CURRENCIES"] == {"en": "USD", "ru": "RUB", "zh": "CNY", "de": "EUR", "es": "EUR"}


def test_missing_chinese_policy_rate_requires_explicit_dated_input() -> None:
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    snapshots["currencies"]["CNY"]["risk_free_rate"] = None
    with pytest.raises(ValueError, match="CNY policy rate"):
        module["build_request"]("CNY", snapshots)


def test_currency_snapshots_are_finite_and_cny_reference_is_explicit() -> None:
    import math

    snapshots = json.loads((EXAMPLES / "currency-assumptions.json").read_text())
    for entry in snapshots["currencies"].values():
        for portfolio in entry["portfolios"].values():
            assert math.isfinite(portfolio["cagr"])
    module = runpy.run_path(str(EXAMPLES / "multilingual_reports.py"))
    request, metadata = module["build_request"]("CNY", snapshots, language="zh")
    assert request["plan"]["rates"]["buffer_rate"] == .03
    assert metadata["rate_symbol"] == "CHN_LPR1.RATE"
    assert "user-selected" in metadata["rate_kind"]
    assert request["plan"]["goals"][0]["label"] == "汽车"
