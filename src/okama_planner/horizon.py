"""The total cap and the resolved end of one plan variant."""

from __future__ import annotations

from okama_planner.inputs import PlanInputs


class InvalidPlanHorizonError(ValueError):
    """The two non-empty stages do not fit inside the declared total horizon."""


def accumulation_years(inputs: PlanInputs) -> int:
    years = inputs.retirement_year - int(inputs.t0[:4])
    if years < 0:
        raise InvalidPlanHorizonError(
            f"retirement year {inputs.retirement_year} is before the plan start ({inputs.t0}); "
            f"retirement {inputs.retirement_year} is not after t0 {inputs.t0}"
        )
    if years == 0:
        raise InvalidPlanHorizonError(f"retirement {inputs.retirement_year} is not after t0 {inputs.t0}")
    return years


def effective_horizon_years(inputs: PlanInputs) -> int:
    withdrawal_years = inputs.withdrawal_years
    if withdrawal_years is not None and type(withdrawal_years) is not int:
        raise InvalidPlanHorizonError(
            f"withdrawal_years={withdrawal_years!r} must be an integer or None, "
            f"got {type(withdrawal_years).__name__}"
        )
    if withdrawal_years is not None and withdrawal_years < 1:
        raise InvalidPlanHorizonError(f"withdrawal_years={withdrawal_years} must be at least 1")
    accumulation = accumulation_years(inputs)
    if withdrawal_years is None:
        if accumulation >= inputs.horizon_years:
            months = inputs.horizon_years * 12
            retirement_month = accumulation * 12
            raise InvalidPlanHorizonError(
                f"retirement year {inputs.retirement_year} is at or past the horizon: "
                f"t0={inputs.t0}, horizon_years={inputs.horizon_years} covers {months} months, "
                f"retirement falls on month {retirement_month} — the pension stream would be empty; "
                f"retirement {inputs.retirement_year} leaves no withdrawal stage inside "
                f"a {inputs.horizon_years}-year horizon"
            )
        return inputs.horizon_years
    total = accumulation + withdrawal_years
    if total > inputs.horizon_years:
        raise InvalidPlanHorizonError(
            f"retirement_year={inputs.retirement_year} plus withdrawal_years="
            f"{withdrawal_years} needs {total} years from t0={inputs.t0}, "
            f"beyond horizon_years={inputs.horizon_years}"
        )
    return total
