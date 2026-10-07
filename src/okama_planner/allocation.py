"""Explicit, immutable funding and dated investment policies for joint scenarios."""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from okama_planner.horizon import effective_horizon_years
from okama_planner.inputs import PlanInputs
from okama_planner.scenarios import JointHistory

_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"


class AllocationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PortfolioWeight(AllocationModel):
    asset: str = Field(min_length=1)
    weight: float = Field(ge=0, allow_inf_nan=False, strict=True)


class StrategyStep(AllocationModel):
    start_month: str = Field(pattern=_MONTH)
    weights: tuple[PortfolioWeight, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_weights(self) -> StrategyStep:
        _weights([x.asset for x in self.weights], [x.weight for x in self.weights])
        return self


class SegmentShare(AllocationModel):
    segment_id: str = Field(min_length=1)
    weight: float = Field(ge=0, allow_inf_nan=False, strict=True)


class SurplusStep(AllocationModel):
    start_month: str = Field(pattern=_MONTH)
    weights: tuple[SegmentShare, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_weights(self) -> SurplusStep:
        _weights([x.segment_id for x in self.weights], [x.weight for x in self.weights])
        return self


def _weights(keys: list[str], values: list[float]) -> None:
    if len(set(keys)) != len(keys) or any(not key.strip() for key in keys):
        raise ValueError("Weight keys must be unique and nonempty")
    if not math.isclose(math.fsum(values), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("Weights must sum to 1 within absolute tolerance 1e-12; never normalized")


class CompletionPolicy(AllocationModel):
    action: Literal["retain", "transfer_to"]
    destination: str | None = None

    @model_validator(mode="after")
    def valid_destination(self) -> CompletionPolicy:
        if (self.action == "transfer_to") != (self.destination is not None):
            raise ValueError("transfer_to requires destination; retain forbids destination")
        return self


class SegmentSpec(AllocationModel):
    segment_id: str = Field(min_length=1)
    goal_id: int | None = Field(strict=True)
    opening_amount: float = Field(ge=0, allow_inf_nan=False, strict=True)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    strategy: tuple[StrategyStep, ...] = Field(min_length=1)
    completion: CompletionPolicy


class GoalFunder(AllocationModel):
    goal_id: int = Field(strict=True)
    segment_id: str = Field(min_length=1)


class AllocationSpec(AllocationModel):
    """All choices are required: even an empty transfer order is an explicit decision."""

    segments: tuple[SegmentSpec, ...] = Field(min_length=1)
    single_strategy: tuple[StrategyStep, ...] = Field(min_length=1)
    surplus_weights: tuple[SurplusStep, ...] = Field(min_length=1)
    household_segment_id: str
    goal_funders: tuple[GoalFunder, ...]
    event_priority: tuple[str, ...]
    funding_source_order: tuple[Literal["cash", "buffer", "segment"], ...]
    reserve_funding_source_order: tuple[Literal["cash", "buffer", "segment"], ...] = Field(min_length=1)
    transfer_policy: Literal["none", "ordered", "unrestricted"]
    transfer_order: tuple[str, ...]
    buffer_policy: Literal["retain", "planned_targets"]
    purchase_execution: Literal["all_or_nothing"]

    @model_validator(mode="after")
    def valid_references(self) -> AllocationSpec:
        self._validate_segments()
        self._validate_sources()
        self._validate_transfers()
        return self

    def _validate_segments(self) -> None:
        ids = [s.segment_id for s in self.segments]
        if len(set(ids)) != len(ids) or any(not x.strip() for x in ids):
            raise ValueError("Segment IDs must be unique and nonempty")
        if self.household_segment_id not in ids:
            raise ValueError("Unknown household segment")
        household = next(s for s in self.segments if s.segment_id == self.household_segment_id)
        if household.goal_id is not None or household.completion.action != "retain":
            raise ValueError("Household segment has no goal and must retain its capital")
        goals = [s.goal_id for s in self.segments if s.segment_id != self.household_segment_id]
        if None in goals or len(set(goals)) != len(goals):
            raise ValueError("Each non-household segment requires one unique goal_id")
        assignments = [(g.goal_id, g.segment_id) for g in self.goal_funders]
        expected = [(s.goal_id, s.segment_id) for s in self.segments if s.goal_id is not None]
        if len(assignments) != len(expected) or set(assignments) != set(expected):
            raise ValueError("Every goal must be funded by its own segment exactly once")
        required_priority = {"expense", "mortgage_payment", *(f"goal:{g}" for g in goals)}
        if set(self.event_priority) != required_priority or len(self.event_priority) != len(
            required_priority
        ):
            raise ValueError("event_priority requires expense, mortgage_payment and each goal exactly once")

    def _validate_sources(self) -> None:
        if (
            set(self.funding_source_order) != {"cash", "buffer", "segment"}
            or len(self.funding_source_order) != 3
        ):
            raise ValueError("funding_source_order must order cash, buffer and segment exactly once")
        if len(set(self.reserve_funding_source_order)) != len(self.reserve_funding_source_order):
            raise ValueError("Reserve funding sources must be unique")

    def _validate_transfers(self) -> None:
        ids = [s.segment_id for s in self.segments]
        if self.transfer_policy == "none":
            if self.transfer_order:
                raise ValueError("none transfer policy requires empty transfer_order")
        elif set(self.transfer_order) != set(ids) or len(self.transfer_order) != len(ids):
            raise ValueError("Transfer order must contain every segment exactly once")
        for step in self.surplus_weights:
            if any(w.segment_id not in ids for w in step.weights):
                raise ValueError("Surplus weights refer to unknown segment")
        self._validate_completion_graph(ids)

    def _validate_completion_graph(self, ids: list[str]) -> None:
        edges = {
            s.segment_id: s.completion.destination
            for s in self.segments
            if s.completion.action == "transfer_to"
        }
        for origin in edges:
            visited = {origin}
            destination = edges[origin]
            while destination is not None:
                if destination not in ids:
                    raise ValueError("Unknown completion destination")
                if destination in visited:
                    raise ValueError("Completion transfers must not contain cycles")
                visited.add(destination)
                destination = edges.get(destination)

    def validate_plan(self, plan: PlanInputs, history: JointHistory, currency: str) -> None:
        """Validate household identity, amounts, currencies and calendar coverage."""
        goals = [g.goal_id for g in plan.goals]
        if None in goals or len(set(goals)) != len(goals):
            raise ValueError("Joint funding requires non-null unique goal IDs")
        if set(goals) != {x.goal_id for x in self.goal_funders}:
            raise ValueError("Allocation must assign every plan goal, with no unknown goals")
        opening = sum(a.amount for a in plan.assets if a.asset_class == "portfolio")
        if not math.isclose(
            math.fsum(s.opening_amount for s in self.segments), opening, rel_tol=0, abs_tol=1e-9
        ):
            raise ValueError("Segment opening amounts must equal opening portfolio capital")
        if history.currency != currency or any(s.currency != currency for s in self.segments):
            raise ValueError("Segment/history currencies must match the plan; FX is unsupported")
        start = pd.Period(plan.t0, freq="M")
        end = start + 12 * effective_horizon_years(plan)
        history_end = (
            pd.Period(history.start_month, freq="M") + len(next(iter(history.asset_returns.values()))) - 1
        )
        if history_end >= start:
            raise ValueError("Joint history must end before plan start")
        schedules = [self.single_strategy, self.surplus_weights, *(s.strategy for s in self.segments)]
        for schedule in schedules:
            dates = [pd.Period(step.start_month, freq="M") for step in schedule]
            if (
                dates[0] != start
                or any(a >= b for a, b in zip(dates[:-1], dates[1:], strict=True))
                or dates[-1] >= end
            ):
                raise ValueError("Dated schedules must begin at t0, ascend strictly and stay within horizon")
        strategies = [self.single_strategy, *(s.strategy for s in self.segments)]
        for schedule in strategies:
            if any(w.asset not in history.asset_returns for step in schedule for w in step.weights):
                raise ValueError("Strategy refers to unknown history asset")
