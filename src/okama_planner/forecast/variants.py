"""Immutable goal date changes for scenario comparisons."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from okama_planner.allocation import AllocationSpec

if TYPE_CHECKING:
    from okama_planner.api import ForecastRequest


from okama_planner.inputs import GoalIn, PlanInputs


class UnknownGoalError(LookupError):
    """No goal in this input carries the given id."""


def _replace_goal(inputs: PlanInputs, goal_id: int, **changes: object) -> PlanInputs:
    found = False
    goals: list[GoalIn] = []
    for goal in inputs.goals:
        if goal.goal_id == goal_id:
            found = True
            goals.append(goal.model_copy(update=changes))
        else:
            goals.append(goal)
    if not found:
        raise UnknownGoalError(f"no goal with id {goal_id} in this input")
    return inputs.model_copy(update={"goals": tuple(goals)})


def with_goal_deferred(inputs: PlanInputs, goal_id: int, target_year: int) -> PlanInputs:
    """Move one goal's date."""
    return _replace_goal(inputs, goal_id, target_year=target_year)


def with_portfolio_mode(
    request: ForecastRequest | dict[str, Any],
    *,
    portfolio_mode: Literal["single", "per_goal"],
    allocation: AllocationSpec | dict[str, Any] | None = None,
) -> ForecastRequest:
    """Return a validated detached mode variant; source input is never mutated.

    Joint history and explicit allocation must already be present for per-goal mode.
    An allocation override is validated against the same household and history.
    """
    from okama_planner.api import ForecastRequest

    source = request.model_dump(mode="json") if isinstance(request, ForecastRequest) else request
    value = ForecastRequest.model_validate(source)
    changed = value.model_dump(mode="json")
    changed["portfolio_mode"] = portfolio_mode
    if allocation is not None:
        changed["allocation"] = (
            allocation.model_dump(mode="json") if isinstance(allocation, AllocationSpec) else allocation
        )
    return ForecastRequest.model_validate(changed)
