"""The public dispatcher accepts both contracts without eager engine imports."""

import importlib
import sys
from types import ModuleType
from typing import Any

import pytest

from okama_planner import forecast
from okama_planner.multicurrency import MulticurrencyRequest
from test_multicurrency import multicurrency_request


@pytest.mark.parametrize("as_model", [False, True])
def test_forecast_dispatches_normalized_multicurrency_request(
    monkeypatch: pytest.MonkeyPatch, as_model: bool,
) -> None:
    engine = ModuleType("okama_planner.multicurrency_engine")
    received = []
    sentinel = {"schema_version": "2.0"}

    def result(request: MulticurrencyRequest) -> dict[str, Any]:
        received.append(request)
        return sentinel

    engine.multicurrency_result = result
    monkeypatch.setitem(sys.modules, engine.__name__, engine)
    raw = multicurrency_request()
    parsed = MulticurrencyRequest.model_validate(raw)
    assert forecast(parsed if as_model else raw) is sentinel
    assert received == [parsed]


def test_multicurrency_public_exports() -> None:
    package = importlib.import_module("okama_planner")
    module = importlib.import_module("okama_planner.multicurrency")
    for name in ("MulticurrencyRequest", "CurrencyGroup", "FXHistory", "CurrencyContribution",
                 "forecast_multicurrency"):
        assert name in package.__all__
        assert getattr(package, name) is getattr(module, name)
