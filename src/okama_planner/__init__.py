"""Personal and family financial planning powered by okama."""

from okama_planner.allocation import (
    AllocationSpec,
    CompletionPolicy,
    GoalFunder,
    PortfolioWeight,
    SegmentShare,
    SegmentSpec,
    StrategyStep,
    SurplusStep,
)
from okama_planner.api import ForecastRequest, compare_portfolio_modes, forecast
from okama_planner.forecast.variants import with_portfolio_mode
from okama_planner.inputs import PlanInputs
from okama_planner.scenarios import JointHistory

__all__ = [
    "AllocationSpec",
    "CompletionPolicy",
    "ForecastRequest",
    "GoalFunder",
    "JointHistory",
    "PlanInputs",
    "PortfolioWeight",
    "SegmentShare",
    "SegmentSpec",
    "StrategyStep",
    "SurplusStep",
    "compare_portfolio_modes",
    "forecast",
    "with_portfolio_mode",
]
