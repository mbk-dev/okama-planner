"""Independent controls for fixed-horizon retirement consumption utility."""

import json
from collections.abc import Callable
from dataclasses import asdict

import numpy as np
import pytest
from pydantic import ValidationError

from okama_planner.utility import (
    ConsumptionPreferences,
    certainty_equivalent,
    compare_consumption,
    equivalent_alpha,
)


def preferences(
    elasticity: float = 0.5, risk_tolerance: float = 0.5, annual_discount_rate: float = 0.0
) -> ConsumptionPreferences:
    return ConsumptionPreferences(
        elasticity=elasticity, risk_tolerance=risk_tolerance, annual_discount_rate=annual_discount_rate
    )


def test_independent_harmonic_control_and_immutable_snapshot() -> None:
    consumption = np.array([[1.0, 2.0], [3.0, 4.0]])
    result = certainty_equivalent(consumption, preferences=preferences())
    np.testing.assert_allclose(result.path_equivalents, [1.5, 8 / 3])
    assert result.value == pytest.approx(1.92)
    assert result.months == 2
    assert result.zero_paths == 0
    with pytest.raises(ValueError):
        result.path_equivalents.setflags(write=True)
    consumption[:] = 8
    np.testing.assert_allclose(result.path_equivalents, [1.5, 8 / 3])


def test_independent_geometric_control() -> None:
    result = certainty_equivalent(np.array([[1.0, 2.0], [3.0, 4.0]]), preferences=preferences(1, 1))
    assert result.value == pytest.approx(24**0.25)


def test_discount_control_months_start_at_one() -> None:
    # Annual factor 4096 yields successive monthly weights 1/2 and 1/4.
    result = certainty_equivalent(np.array([[1.0], [4.0]]), preferences=preferences(0.5, 1, 4095))
    assert result.value == pytest.approx(4 / 3)
    geometric = certainty_equivalent(np.array([[1.0], [8.0]]), preferences=preferences(1, 1, 4095))
    assert geometric.value == pytest.approx(2)


@pytest.mark.parametrize(
    "eta,theta,expected", [(0.5, 0.5, 0), (1, 1, 0), (2, 2, 1), (2, 0.5, 1), (0.5, 2, 0)]
)
def test_zero_continuous_limits(eta: float, theta: float, expected: float) -> None:
    # Positive power: path means [1, 1], so the outer mean is 1.
    result = certainty_equivalent(np.array([[0.0, 4.0], [4.0, 0.0]]), preferences=preferences(eta, theta))
    assert result.value == pytest.approx(expected)
    assert result.zero_paths == (2 if eta <= 1 else 0)


def test_outer_zero_is_not_dropped() -> None:
    result = certainty_equivalent(np.array([[0.0, 4.0]]), preferences=preferences(2, 2))
    assert result.value == pytest.approx(1)
    assert result.zero_paths == 1
    assert certainty_equivalent(np.array([[0.0, 4.0]]), preferences=preferences(2, 1)).value == 0


@pytest.mark.parametrize("value", [1e-300, 1e300, np.finfo(float).max, np.nextafter(0.0, 1.0)])
def test_constant_extreme_is_finite_and_exact(value: float) -> None:
    result = certainty_equivalent(np.full((3, 4), value), preferences=preferences())
    assert result.value == value
    assert np.isfinite(result.path_equivalents).all()


def test_extreme_mixed_values_and_near_geometric_limits() -> None:
    values = np.array([[1e-300], [1e300]])
    assert certainty_equivalent(values, preferences=preferences()).value == pytest.approx(2e-300, abs=0)
    for eta in [1.0, 1.0 + 1e-12, 1.0 - 1e-12]:
        actual = certainty_equivalent(values, preferences=preferences(eta, 1)).value
        assert actual == pytest.approx(1, rel=3e-7)
    assert np.isfinite(certainty_equivalent(values, preferences=preferences(1e-320, 1e-320)).value)


@pytest.mark.parametrize(
    "matrix",
    [
        np.array([]),
        np.empty((0, 2)),
        np.empty((2, 0)),
        np.ones((2, 2, 2)),
        np.array([[-1.0]]),
        np.array([[np.nan]]),
        np.array([[np.inf]]),
        [[1.0]],
        np.array([[1 + 2j]]),
    ],
)
def test_invalid_consumption(matrix: np.ndarray) -> None:
    with pytest.raises(ValueError):
        certainty_equivalent(matrix, preferences=preferences())


@pytest.mark.parametrize(
    "field,value",
    [
        ("elasticity", 0),
        ("risk_tolerance", -1),
        ("annual_discount_rate", -1),
        ("elasticity", np.inf),
        ("risk_tolerance", np.nan),
        ("annual_discount_rate", np.inf),
    ],
)
def test_invalid_preferences(field: str, value: float) -> None:
    values = {"elasticity": 0.5, "risk_tolerance": 0.5, "annual_discount_rate": 0}
    values[field] = value
    with pytest.raises(ValidationError):
        ConsumptionPreferences(**values)


def test_preferences_are_required_and_frozen() -> None:
    with pytest.raises(ValidationError):
        ConsumptionPreferences()
    with pytest.raises(ValidationError):
        preferences().elasticity = 1


@pytest.mark.parametrize("scale,expected", [(1, 0), (2, 1), (0.5, -0.5)])
def test_gamma_scaling_and_no_mutation(scale: float, expected: float) -> None:
    baseline = np.array([[100.0, 200.0], [300.0, 400.0]])
    variant = baseline * scale
    before = baseline.copy(), variant.copy()
    result = compare_consumption(baseline, variant, preferences=preferences())
    assert result.gamma == pytest.approx(expected)
    assert result.reason is None
    assert result.standard_error is result.confidence_interval is None
    np.testing.assert_array_equal(baseline, before[0])
    np.testing.assert_array_equal(variant, before[1])
    json.dumps(asdict(result), allow_nan=False)


def test_zero_baseline_and_overflow_gamma_are_explicit() -> None:
    result = compare_consumption(np.zeros((2, 2)), np.zeros((2, 2)), preferences=preferences())
    assert result.gamma is None
    assert result.reason == "zero_baseline_ce"
    overflow = compare_consumption(np.full((1, 1), 1e-300), np.full((1, 1), 1e300), preferences=preferences())
    assert overflow.gamma is None
    assert overflow.reason == "nonfinite_gamma"
    json.dumps(asdict(overflow), allow_nan=False)


def test_paired_bootstrap_independent_arithmetic_reference_and_rng() -> None:
    baseline = np.array([[1.0, 2.0, 4.0]])
    variant = np.array([[2.0, 5.0, 3.0]])
    prefs = preferences(2, 2)
    state = np.random.get_state()
    result = compare_consumption(baseline, variant, preferences=prefs, bootstrap_replicates=30, seed=42)
    rng = np.random.default_rng(42)
    reference = []
    for _ in range(30):
        indices = rng.integers(3, size=3)
        base = np.mean(np.sqrt(baseline[0, indices])) ** 2
        changed = np.mean(np.sqrt(variant[0, indices])) ** 2
        reference.append(changed / base - 1)
    assert result.standard_error == pytest.approx(np.std(reference, ddof=1))
    assert result.confidence_interval == pytest.approx(np.percentile(reference, [2.5, 97.5]))
    assert result == compare_consumption(
        baseline, variant, preferences=prefs, bootstrap_replicates=30, seed=42
    )
    after = np.random.get_state()
    assert state[0] == after[0]
    np.testing.assert_array_equal(state[1], after[1])
    assert state[2:] == after[2:]


def test_identical_bootstrap_and_undefined_replicates() -> None:
    positive = np.array([[1.0, 2.0, 3.0]])
    result = compare_consumption(positive, positive, preferences=preferences(), bootstrap_replicates=20)
    assert result.gamma == result.standard_error == 0
    assert result.confidence_interval == (0.0, 0.0)
    baseline = np.array([[0.0, 2.0]])
    result = compare_consumption(baseline, baseline, preferences=preferences(), bootstrap_replicates=20)
    rng = np.random.default_rng(0)
    undefined = sum(0 in rng.integers(2, size=2) for _ in range(20))
    assert result.undefined_replicates == undefined
    assert result.standard_error is result.confidence_interval is None


@pytest.mark.parametrize("replicates", [1, -1, 2.5, True])
def test_invalid_bootstrap_counts(replicates: int) -> None:
    with pytest.raises(ValueError):
        compare_consumption(
            np.ones((1, 1)), np.ones((1, 1)), preferences=preferences(), bootstrap_replicates=replicates
        )


@pytest.mark.parametrize("seed", [-1, 1.2, True, None])
def test_invalid_seed_even_without_bootstrap(seed: int) -> None:
    with pytest.raises(ValueError):
        compare_consumption(np.ones((1, 1)), np.ones((1, 1)), preferences=preferences(), seed=seed)


def test_comparison_requires_identical_shapes() -> None:
    with pytest.raises(ValueError):
        compare_consumption(np.ones((1, 2)), np.ones((2, 1)), preferences=preferences())


@pytest.mark.parametrize("target,expected", [(120, 0.2), (80, -0.2), (100, 0)])
def test_alpha_linear_analytic_control(target: float, expected: float) -> None:
    result = equivalent_alpha(
        lambda alpha: np.full((3, 2), 100 * (1 + alpha)),
        target_ce=target,
        preferences=preferences(),
        bracket=(-0.5, 0.5),
    )
    assert result.alpha == pytest.approx(expected)
    assert result.residual == pytest.approx(0, abs=1e-8)
    assert result.reason is None
    assert result.iterations >= 0
    if target == 100:
        assert result.alpha == 0
    json.dumps(asdict(result), allow_nan=False)


def test_alpha_no_root_and_endpoint() -> None:
    def callback(alpha: float) -> np.ndarray:
        return np.full((2, 2), 100 * (1 + alpha))

    result = equivalent_alpha(callback, target_ce=200, preferences=preferences(), bracket=(-0.5, 0.5))
    assert result.alpha is result.residual is None
    assert result.reason == "no_root"
    endpoint = equivalent_alpha(callback, target_ce=150, preferences=preferences(), bracket=(-0.5, 0.5))
    assert endpoint.alpha == 0.5
    assert endpoint.iterations == 0


@pytest.mark.parametrize(
    "callback",
    [lambda a: np.array([1.0]), lambda a: np.array([[np.nan]]), lambda a: np.ones((1, 1 if a <= 0 else 2))],
)
def test_alpha_invalid_callback_cannot_return_number(callback: Callable[[float], np.ndarray]) -> None:
    result = equivalent_alpha(callback, target_ce=2, preferences=preferences(), bracket=(-0.5, 0.5))
    assert result.alpha is result.residual is None
    assert result.reason in {"invalid_consumption", "invalid_ce", "inconsistent_shape"}


def test_alpha_zero_consumption_is_valid_but_has_no_positive_target_root() -> None:
    result = equivalent_alpha(
        lambda a: np.zeros((1, 1)), target_ce=2, preferences=preferences(), bracket=(-0.5, 0.5)
    )
    assert result.alpha is result.residual is None
    assert result.reason == "no_root"


def test_alpha_iteration_limit() -> None:
    result = equivalent_alpha(
        lambda a: np.full((1, 1), np.exp(a)),
        target_ce=2,
        preferences=preferences(),
        bracket=(-1.0, 2.0),
        max_iterations=1,
    )
    assert result.alpha is result.residual is None
    assert result.reason == "iteration_limit"
    assert result.iterations == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_ce": 0},
        {"target_ce": np.inf},
        {"bracket": (1, 0)},
        {"bracket": (0, np.inf)},
        {"tolerance": 0},
        {"tolerance": np.nan},
        {"max_iterations": True},
        {"max_iterations": 0},
    ],
)
def test_invalid_alpha_parameters(kwargs: dict[str, object]) -> None:
    arguments = {"target_ce": 100, "bracket": (-0.5, 0.5)} | kwargs
    with pytest.raises(ValueError):
        equivalent_alpha(lambda a: np.ones((1, 1)), preferences=preferences(), **arguments)


def test_second_independent_discount_control() -> None:
    result = certainty_equivalent(np.array([[1.0], [3.0]]), preferences=preferences(0.5, 0.5, 4095))
    assert result.value == pytest.approx(9 / 7)


def test_alpha_callback_exception_has_explicit_reason() -> None:
    def callback(alpha: float) -> np.ndarray:
        raise RuntimeError("Unable to evaluate supplied baseline")

    result = equivalent_alpha(callback, target_ce=100, preferences=preferences(), bracket=(-0.5, 0.5))
    assert result.alpha is result.residual is None
    assert result.reason == "callback_error"


def test_alpha_shape_changes_during_root_search_are_rejected() -> None:
    def callback(alpha: float) -> np.ndarray:
        paths = 1 if alpha in {0.0, -0.5, 0.5} else 2
        return np.full((1, paths), 100 * (1 + alpha))

    result = equivalent_alpha(callback, target_ce=120, preferences=preferences(), bracket=(-0.5, 0.5))
    assert result.alpha is result.residual is None
    assert result.reason == "inconsistent_shape"


@pytest.mark.parametrize("shape", [(5, 1), (1, 5), (5, 7)])
@pytest.mark.parametrize("eta,theta", [(1, 0.5), (0.5, 1), (1, 1), (1, 2), (2, 1)])
@pytest.mark.parametrize("discount", [0.0, 0.025, -0.9])
def test_maximum_constant_geometric_ce_and_comparison_are_exact_finite_json(
    shape: tuple[int, int],
    eta: float,
    theta: float,
    discount: float,
) -> None:
    maximum = np.finfo(float).max
    consumption = np.full(shape, maximum)
    prefs = preferences(eta, theta, discount)
    result = certainty_equivalent(consumption, preferences=prefs)
    assert result.value == maximum
    np.testing.assert_array_equal(result.path_equivalents, np.full(shape[1], maximum))
    comparison = compare_consumption(consumption, consumption, preferences=prefs)
    assert comparison.baseline_ce == comparison.variant_ce == maximum
    assert comparison.gamma == 0
    assert comparison.reason is None
    json.dumps(asdict(comparison), allow_nan=False)
    json.dumps({"value": result.value, "paths": result.path_equivalents.tolist()}, allow_nan=False)


def test_geometric_mixed_near_maximum_stays_in_finite_input_range() -> None:
    maximum = np.finfo(float).max
    lower = np.nextafter(maximum, 0.0)
    consumption = np.array(
        [[maximum, lower], [lower, maximum], [maximum, lower], [lower, maximum], [maximum, lower]]
    )
    result = certainty_equivalent(consumption, preferences=preferences(1, 1, 0.025))
    assert lower <= result.value <= maximum
    assert np.all((lower <= result.path_equivalents) & (result.path_equivalents <= maximum))
    json.dumps({"value": result.value, "paths": result.path_equivalents.tolist()}, allow_nan=False)


def test_undefined_point_gamma_suppresses_uncertainty_when_all_replicates_are_defined() -> None:
    consumption = np.array([[0.0, 100.0]])
    result = compare_consumption(
        consumption, consumption, preferences=preferences(), bootstrap_replicates=2, seed=4
    )
    assert result.gamma is None
    assert result.reason == "zero_baseline_ce"
    assert result.undefined_replicates == 0
    assert result.standard_error is result.confidence_interval is None
