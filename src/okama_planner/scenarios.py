"""Synchronized bootstrap of monthly asset returns in a single plan currency."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, field_validator


class JointHistory(BaseModel):
    """Aligned monthly observations, already expressed in the plan currency.

    Each asset's observation at the same offset belongs to the same month.
    The caller is responsible for calendar alignment and currency conversion.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    method: Literal["synchronized_bootstrap"]
    asset_returns: dict[str, tuple[float, ...]]

    @field_validator("asset_returns")
    @classmethod
    def validate_asset_returns(cls, values: dict[str, tuple[float, ...]]) -> dict[str, tuple[float, ...]]:
        if not values or any(not name.strip() for name in values):
            raise ValueError("History requires assets with nonempty names")
        lengths = {len(returns) for returns in values.values()}
        if len(lengths) != 1 or next(iter(lengths)) < 12:
            raise ValueError("Assets must have equal lengths of at least 12 monthly observations")
        if any(not math.isfinite(value) or value < -1 for returns in values.values() for value in returns):
            raise ValueError("Monthly returns must be finite and at least -1")
        return values


@dataclass(frozen=True, eq=False)
class JointScenarios:
    """One shared historical row per forecast month and path across all assets.

    Arrays returned by :func:`sample_joint_returns` have immutable backing storage.
    The hash identifies history and method, independently of seed and sample size.
    """

    assets: tuple[str, ...]
    returns: NDArray[np.float64]
    row_indices: NDArray[np.int64]
    history_sha256: str


def _integer(value: int, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def sample_joint_returns(history: JointHistory, *, months: int, paths: int, seed: int) -> JointScenarios:
    """Draw historical rows with replacement using a local NumPy generator.

    This preserves within-month cross-asset dependence, but does not preserve
    serial dependence between successive historical months.
    """
    months = _integer(months, "months", 1)
    paths = _integer(paths, "paths", 1)
    seed = _integer(seed, "seed", 0)
    # Revalidate a snapshot: frozen Pydantic models still contain mutable mappings.
    snapshot = JointHistory.model_validate(history.model_dump())
    assets = tuple(sorted(snapshot.asset_returns))
    normalized = snapshot.model_dump()
    normalized["asset_returns"] = {
        asset: [0.0 if value == 0 else value for value in snapshot.asset_returns[asset]] for asset in assets
    }
    payload = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    matrix = np.asarray([snapshot.asset_returns[asset] for asset in assets], dtype=np.float64).T
    indices = np.random.default_rng(seed).integers(matrix.shape[0], size=(months, paths), dtype=np.int64)
    sampled = matrix[indices]
    # bytes backing prevents callers from re-enabling the write flag on owned arrays.
    returns = np.frombuffer(sampled.tobytes(), dtype=np.float64).reshape(months, paths, len(assets))
    row_indices = np.frombuffer(indices.tobytes(), dtype=np.int64).reshape(months, paths)
    return JointScenarios(assets=assets, returns=returns, row_indices=row_indices, history_sha256=digest)


def weighted_returns(scenarios: JointScenarios, weights: dict[str, float]) -> NDArray[np.float64]:
    """Monthly returns for a portfolio rebalanced to the supplied weights each month.

    Omitted assets have zero weight. Supplied weights are never normalized.
    Invalid weights, including unknown assets with zero weight, raise ValueError.
    """
    if any(asset not in scenarios.assets for asset in weights):
        raise ValueError("Weights contain an unknown asset")
    if any(
        not isinstance(weight, Real) or not math.isfinite(weight) or weight < 0 for weight in weights.values()
    ):
        raise ValueError("Weights must be finite and nonnegative")
    if not math.isclose(sum(weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("Weights must sum to 1 within absolute tolerance 1e-12")
    vector = np.asarray([weights.get(asset, 0.0) for asset in scenarios.assets], dtype=np.float64)
    return scenarios.returns @ vector
