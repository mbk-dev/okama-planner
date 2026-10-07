"""Joint sampling must preserve the historical cross-asset relationships."""

import copy

import numpy as np
import pytest
from pydantic import ValidationError

from okama_planner.scenarios import JointHistory, sample_joint_returns, weighted_returns


def history(assets: dict[str, tuple[float, ...]] | None = None) -> JointHistory:
    return JointHistory(
        start_month="2020-01", currency="USD", method="synchronized_bootstrap",
        asset_returns=assets if assets is not None else {"A": tuple(i / 100 for i in range(12))},
    )


def test_identical_assets_have_identical_paths() -> None:
    values = tuple(i / 100 for i in range(12))
    sampled = sample_joint_returns(history({"B": values, "A": values}), months=25, paths=100, seed=2)
    assert sampled.assets == ("A", "B")
    assert sampled.returns.shape == (25, 100, 2)
    assert sampled.row_indices.shape == (25, 100)
    np.testing.assert_array_equal(sampled.returns[:, :, 0], sampled.returns[:, :, 1])
    assert np.unique(sampled.row_indices).size > 1


def test_anticorrelated_assets_cancel_under_equal_weights() -> None:
    a = tuple(i / 100 for i in range(-6, 6))
    b = tuple(-x for x in a)
    sampled = sample_joint_returns(history({"A": a, "B": b}), months=20, paths=100, seed=7)
    np.testing.assert_array_equal(weighted_returns(sampled, {"A": 0.5, "B": 0.5}), np.zeros((20, 100)))


def test_segments_use_the_same_sampled_rows_and_literal_weighted_returns() -> None:
    a = (0.1, 0.2) * 6
    b = (0.3, 0.4) * 6
    sampled = sample_joint_returns(history({"A": a, "B": b}), months=15, paths=30, seed=0)
    first = weighted_returns(sampled, {"A": 1.0})
    second = weighted_returns(sampled, {"B": 1.0})
    np.testing.assert_array_equal(first, np.asarray(a)[sampled.row_indices])
    np.testing.assert_array_equal(second, np.asarray(b)[sampled.row_indices])
    np.testing.assert_allclose(weighted_returns(sampled, {"A": 0.25, "B": 0.75}),
                               np.where(sampled.row_indices % 2 == 0, 0.25, 0.35), rtol=0, atol=1e-15)


def test_seed_and_key_order_reproduce_samples_and_hash() -> None:
    a, b = (0.1,) * 12, (0.2,) * 12
    left = sample_joint_returns(history({"B": b, "A": a}), months=8, paths=5, seed=12)
    right = sample_joint_returns(history({"A": a, "B": b}), months=8, paths=5, seed=12)
    np.testing.assert_array_equal(left.row_indices, right.row_indices)
    np.testing.assert_array_equal(left.returns, right.returns)
    assert left.history_sha256 == right.history_sha256
    assert len(left.history_sha256) == 64
    other = sample_joint_returns(history({"A": a, "B": b}), months=8, paths=5, seed=13)
    assert not np.array_equal(left.row_indices, other.row_indices)
    assert left.history_sha256 == other.history_sha256
    changed = sample_joint_returns(history({"A": (0.11,) * 12, "B": b}), months=8, paths=5, seed=12)
    assert left.history_sha256 != changed.history_sha256


def test_sampling_preserves_global_rng_and_caller_inputs() -> None:
    raw = {"A": [0.1] * 12}
    original = copy.deepcopy(raw)
    source = JointHistory(start_month="2020-01", currency="USD", method="synchronized_bootstrap",
                          asset_returns=raw)
    state = np.random.get_state()
    sampled = sample_joint_returns(source, months=3, paths=4, seed=0)
    after = np.random.get_state()
    assert state[0] == after[0]
    np.testing.assert_array_equal(state[1], after[1])
    assert state[2:] == after[2:]
    weights = {"A": 1.0}
    weighted_returns(sampled, weights)
    assert weights == {"A": 1.0}
    assert raw == original
    raw["A"][0] = 0.9
    assert source.asset_returns["A"][0] == 0.1
    with pytest.raises(ValidationError):
        source.currency = "EUR"
    for array in (sampled.returns, sampled.row_indices):
        with pytest.raises(ValueError):
            array.flat[0] = 1
        with pytest.raises(ValueError):
            array.setflags(write=True)


@pytest.mark.parametrize("assets", [
    {}, {"": (0.1,) * 12}, {"  ": (0.1,) * 12}, {"A": (0.1,) * 11},
    {"A": (0.1,) * 12, "B": (0.2,) * 13}, {"A": (float("nan"),) * 12},
    {"A": (float("inf"),) * 12}, {"A": (-1.01,) * 12},
])
def test_invalid_history_is_rejected(assets: dict[str, tuple[float, ...]]) -> None:
    with pytest.raises(ValidationError):
        history(assets)


def test_method_is_required_and_explicit() -> None:
    values = {"start_month": "2020-01", "currency": "USD", "asset_returns": {"A": (0.1,) * 12}}
    with pytest.raises(ValidationError):
        JointHistory(**values)
    with pytest.raises(ValidationError):
        JointHistory(**values, method="independent_bootstrap")
    sampled = sample_joint_returns(history({"A": (-1.0,) * 12}), months=1, paths=1, seed=0)
    assert sampled.returns.item() == -1.0


@pytest.mark.parametrize(("parameter", "value"), [
    ("months", 0), ("months", -1), ("months", True), ("months", 1.5), ("months", "2"),
    ("paths", 0), ("paths", -1), ("paths", False), ("paths", 1.5),
    ("seed", -1), ("seed", True), ("seed", 1.5),
])
def test_invalid_sampling_parameters_raise_value_error(parameter: str, value: object) -> None:
    arguments = {"months": 2, "paths": 3, "seed": 0, parameter: value}
    with pytest.raises(ValueError):
        sample_joint_returns(history(), **arguments)


@pytest.mark.parametrize("weights", [
    {}, {"A": 0.9}, {"A": 1.1}, {"A": -1.0}, {"A": float("nan")},
    {"A": float("inf")}, {"missing": 1.0}, {"A": 1.0, "missing": 0.0},
    {"A": 0.5, "B": -0.5}, {"A": 1e308, "B": 1e308}, {"A": "1"},
])
def test_invalid_weights_raise_value_error(weights: dict[str, float]) -> None:
    sampled = sample_joint_returns(history({"A": (0.1,) * 12, "B": (0.2,) * 12}),
                                   months=2, paths=3, seed=0)
    with pytest.raises(ValueError):
        weighted_returns(sampled, weights)


def test_weight_sum_uses_absolute_tolerance_and_never_normalizes() -> None:
    sampled = sample_joint_returns(history(), months=1, paths=1, seed=0)
    result = weighted_returns(sampled, {"A": 1.0 + 5e-13})
    np.testing.assert_array_equal(result, sampled.returns[:, :, 0] * (1.0 + 5e-13))
    with pytest.raises(ValueError):
        weighted_returns(sampled, {"A": 1.0 + 2e-12})


@pytest.mark.parametrize(("field", "value"), [
    ("start_month", ""), ("start_month", "2020-00"), ("start_month", "2020-13"),
    ("start_month", "2020-1"), ("start_month", "20-01"), ("start_month", "2020-01-01"),
    ("start_month", " 2020-01"), ("start_month", "2020-01 "),
    ("currency", ""), ("currency", "usd"), ("currency", "US"), ("currency", "USDD"),
    ("currency", "U1D"), ("currency", " USD"), ("currency", "USD "),
])
def test_history_rejects_invalid_month_and_currency_formats(field: str, value: str) -> None:
    inputs = {"start_month": "2020-01", "currency": "USD", "method": "synchronized_bootstrap",
              "asset_returns": {"A": (0.1,) * 12}, field: value}
    with pytest.raises(ValidationError):
        JointHistory(**inputs)


@pytest.mark.parametrize("month", ["2020-01", "2020-12"])
def test_history_accepts_month_boundaries_without_currency_whitelist(month: str) -> None:
    source = JointHistory(start_month=month, currency="XYZ", method="synchronized_bootstrap",
                          asset_returns={"A": (0.1,) * 12})
    sampled = sample_joint_returns(source, months=1, paths=1, seed=0)
    assert sampled.returns.item() == 0.1
