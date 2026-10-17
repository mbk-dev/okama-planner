"""Keep the supported engine capable of a deterministic offline plan."""
import importlib.metadata

import pytest

from test_api import inputs, run


def test_okama4_offline_hand_computed_balance() -> None:
    assert int(importlib.metadata.version("okama").split(".")[0]) >= 4
    result = run(inputs())
    assert result["schema_version"] == "1.0"
    assert result["metrics"]["terminal_p50"] == pytest.approx(11400)
    assert result["metrics"]["probability_of_success"] == 1
