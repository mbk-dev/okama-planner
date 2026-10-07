"""Fixed-horizon utility of real, actually funded monthly consumption."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from numbers import Integral, Real

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field
from scipy.optimize import brentq


class ConsumptionPreferences(BaseModel):
    """Explicit timing substitution, risk tolerance, and annual discounting."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    elasticity: float = Field(gt=0)
    risk_tolerance: float = Field(gt=0)
    annual_discount_rate: float = Field(gt=-1)


@dataclass(frozen=True, eq=False)
class CEResult:
    """Equivalent real consumption per month, with immutable path equivalents."""

    value: float
    path_equivalents: NDArray[np.float64]
    zero_paths: int
    months: int


@dataclass(frozen=True)
class GammaResult:
    """Relative CE improvement and optional paired-path sampling uncertainty."""

    baseline_ce: float
    variant_ce: float
    gamma: float | None
    reason: str | None
    standard_error: float | None
    confidence_interval: tuple[float, float] | None
    undefined_replicates: int


@dataclass(frozen=True)
class AlphaResult:
    """Annual return shift supplied to the caller's baseline evaluator."""

    alpha: float | None
    residual: float | None
    reason: str | None
    iterations: int


def _consumption(values: NDArray[np.float64]) -> NDArray[np.float64]:
    if not isinstance(values, np.ndarray) or values.dtype.kind not in "iuf":
        raise ValueError("Consumption must be a real numeric NumPy array")
    if values.ndim != 2 or min(values.shape) <= 0:
        raise ValueError("Consumption must have positive (months, paths) dimensions")
    with np.errstate(over="ignore", invalid="ignore"):
        array = np.asarray(values, dtype=np.float64)
    if not np.isfinite(array).all() or (array < 0).any():
        raise ValueError("Consumption must be finite and nonnegative")
    return array


def _integer(value: int, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _power_mean_logs(
    logs: NDArray[np.longdouble],
    power: np.longdouble,
    log_weights: NDArray[np.longdouble],
) -> np.longdouble:
    """Power mean in log space, including zero values represented by -infinity.

    Anchoring at the appropriate extreme keeps exponential arguments nonpositive.
    Near zero power, expm1/log1p avoid cancellation in the geometric limit.
    """
    zero = np.isneginf(logs)
    if zero.all() or (power <= 0 and zero.any()):
        return np.longdouble(-np.inf)
    weights = np.exp(log_weights - np.max(log_weights))
    weights /= weights.sum()
    if power == 0:
        # The geometric limit obeys the same input-range bound as other powers.
        return np.longdouble(np.clip(np.sum(weights * logs), logs.min(), logs.max()))
    finite = logs[~zero]
    anchor = finite.max() if power > 0 else finite.min()
    shifts = power * (logs - anchor)
    if not zero.any() and np.max(np.abs(shifts)) < 0.5:
        adjustment = np.log1p(np.sum(weights * np.expm1(shifts))) / power
    else:
        # Keep tiny time weights in log space even when their linear form underflows.
        terms = log_weights + shifts
        maximum = terms.max()
        numerator = maximum + np.log(np.exp(terms - maximum).sum())
        maximum_weight = log_weights.max()
        denominator = maximum_weight + np.log(np.exp(log_weights - maximum_weight).sum())
        adjustment = (numerator - denominator) / power
    result = anchor + adjustment
    # Power means lie within the input range; bound only floating point roundoff.
    lower = -np.inf if zero.any() else finite.min()
    return np.longdouble(np.clip(result, lower, finite.max()))


def certainty_equivalent(
    consumption: NDArray[np.float64],
    *,
    preferences: ConsumptionPreferences,
) -> CEResult:
    """Apply timing and then risk power means to (months, paths) consumption.

    No depletion path is dropped or softened with an epsilon. The horizon is
    fixed, all paths are equally likely, and there is no mortality model.
    """
    array = _consumption(consumption)
    prefs = ConsumptionPreferences.model_validate(preferences.model_dump())
    months, paths = array.shape
    eta, theta = np.longdouble(prefs.elasticity), np.longdouble(prefs.risk_tolerance)
    log_weights = (
        -np.arange(1, months + 1, dtype=np.longdouble)
        * np.log1p(np.longdouble(prefs.annual_discount_rate))
        / 12
    )
    with np.errstate(divide="ignore"):
        logs = np.log(array.astype(np.longdouble))
    path_logs = np.array(
        [_power_mean_logs(logs[:, path], (eta - 1) / eta, log_weights) for path in range(paths)],
        dtype=np.longdouble,
    )
    ce_log = _power_mean_logs(path_logs, (theta - 1) / theta, np.zeros(paths, dtype=np.longdouble))
    path_values = np.exp(path_logs).astype(np.float64)
    # Immutable bytes storage prevents callers from re-enabling the write flag.
    immutable = np.frombuffer(path_values.tobytes(), dtype=np.float64)
    return CEResult(float(np.exp(ce_log)), immutable, int(np.count_nonzero(path_values == 0)), months)


def _gamma(baseline: float, variant: float) -> tuple[float | None, str | None]:
    if baseline == 0:
        return None, "zero_baseline_ce"
    value = np.longdouble(variant) / np.longdouble(baseline) - 1
    if abs(value) > np.finfo(float).max or not np.isfinite(value):
        return None, "nonfinite_gamma"
    return float(value), None


def _bootstrap(
    baseline: NDArray[np.float64],
    variant: NDArray[np.float64],
    preferences: ConsumptionPreferences,
    replicates: int,
    seed: int,
) -> tuple[float | None, tuple[float, float] | None, int]:
    rng = np.random.default_rng(seed)
    gammas = []
    undefined = 0
    for _ in range(replicates):
        indices = rng.integers(baseline.shape[1], size=baseline.shape[1])
        base = certainty_equivalent(baseline[:, indices], preferences=preferences).value
        changed = certainty_equivalent(variant[:, indices], preferences=preferences).value
        gamma, _ = _gamma(base, changed)
        if gamma is None:
            undefined += 1
        else:
            gammas.append(gamma)
    if undefined or not replicates:
        return None, None, undefined
    # Extended precision prevents overflow in squared deviations of finite gammas.
    values = np.asarray(gammas, dtype=np.longdouble)
    deviation = np.std(values, ddof=1)
    interval = np.percentile(values, [2.5, 97.5])
    if deviation > np.finfo(float).max or not np.isfinite(deviation):
        return None, None, undefined
    return float(deviation), (float(interval[0]), float(interval[1])), undefined


def compare_consumption(
    baseline: NDArray[np.float64],
    variant: NDArray[np.float64],
    *,
    preferences: ConsumptionPreferences,
    bootstrap_replicates: int = 0,
    seed: int = 0,
) -> GammaResult:
    """Compare CE, optionally resampling shared path indices for both plans.

    Any undefined replicate suppresses both uncertainty statistics, rather than
    conditioning them on a subset of successful paths or replicates.
    """
    replicates = _integer(bootstrap_replicates, "bootstrap_replicates", 0)
    if replicates == 1:
        raise ValueError("bootstrap_replicates must be 0 or at least 2")
    seed = _integer(seed, "seed", 0)
    baseline, variant = _consumption(baseline), _consumption(variant)
    if baseline.shape != variant.shape:
        raise ValueError("Consumption matrices must have identical shapes")
    base = certainty_equivalent(baseline, preferences=preferences).value
    changed = certainty_equivalent(variant, preferences=preferences).value
    gamma, reason = _gamma(base, changed)
    standard_error, interval, undefined = _bootstrap(baseline, variant, preferences, replicates, seed)
    if gamma is None:
        standard_error, interval = None, None
    return GammaResult(base, changed, gamma, reason, standard_error, interval, undefined)


class _EvaluationError(ValueError):
    """Internal marker for unavailable callback evaluations."""


def _finite_real(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite and real")
    return float(value)


def _objective(
    callback: Callable[[float], NDArray[np.float64]],
    target: float,
    preferences: ConsumptionPreferences,
) -> Callable[[float], float]:
    shape = None

    def evaluate(alpha: float) -> float:
        nonlocal shape
        try:
            consumption = _consumption(callback(alpha))
        except (ValueError, TypeError, OverflowError) as exc:
            raise _EvaluationError("invalid_consumption") from exc
        except Exception as exc:
            raise _EvaluationError("callback_error") from exc
        if shape is not None and consumption.shape != shape:
            raise _EvaluationError("inconsistent_shape")
        shape = consumption.shape
        try:
            ce = certainty_equivalent(consumption, preferences=preferences).value
        except (ValueError, OverflowError, FloatingPointError) as exc:
            raise _EvaluationError("invalid_ce") from exc
        if not math.isfinite(ce):
            raise _EvaluationError("invalid_ce")
        return ce - target

    return evaluate


def _bracket(bracket: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(bracket, tuple) or len(bracket) != 2:
        raise ValueError("bracket must be a pair of finite increasing endpoints")
    low, high = (_finite_real(value, "bracket endpoint") for value in bracket)
    if low >= high:
        raise ValueError("bracket endpoints must be increasing")
    return low, high


def equivalent_alpha(
    evaluate_baseline: Callable[[float], NDArray[np.float64]],
    *,
    target_ce: float,
    preferences: ConsumptionPreferences,
    bracket: tuple[float, float],
    tolerance: float = 1e-8,
    max_iterations: int = 100,
) -> AlphaResult:
    """Solve for a caller-defined annual return shift using Brent's method.

    The callback owns the return overlay and must preserve paired market paths
    and every non-return input. A root is unavailable for invalid evaluations,
    changing consumption shapes, an unbracketed root, or iteration exhaustion.
    """
    target = _finite_real(target_ce, "target_ce")
    tolerance = _finite_real(tolerance, "tolerance")
    iterations = _integer(max_iterations, "max_iterations", 1)
    if target <= 0 or tolerance <= 0:
        raise ValueError("target_ce and tolerance must be positive")
    low, high = _bracket(bracket)
    objective = _objective(evaluate_baseline, target, preferences)
    try:
        if low <= 0 <= high:
            residual = objective(0.0)
            if residual == 0:
                return AlphaResult(0.0, residual, None, 0)
        left, right = objective(low), objective(high)
        if left == 0:
            return AlphaResult(low, left, None, 0)
        if right == 0:
            return AlphaResult(high, right, None, 0)
        if (left > 0) == (right > 0):
            return AlphaResult(None, None, "no_root", 0)
        root, result = brentq(
            objective, low, high, xtol=tolerance, maxiter=iterations, full_output=True, disp=False
        )
        if not result.converged:
            return AlphaResult(None, None, "iteration_limit", int(result.iterations))
        residual = objective(root)
        return AlphaResult(float(root), residual, None, int(result.iterations))
    except _EvaluationError as exc:
        return AlphaResult(None, None, str(exc), 0)
