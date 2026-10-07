"""Immutable goal date changes for scenario comparisons."""

from __future__ import annotations


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
