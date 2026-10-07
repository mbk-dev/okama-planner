"""Joint monthly market paths with scenario-wise, money-conserving event funding.

The planned ledger supplies dated external requirements, never a second net cash inflow.
Returns precede monthly flows. Actual assets and debts remain separate from the planned ledger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from okama_planner.allocation import StrategyStep, SurplusStep
from okama_planner.horizon import effective_horizon_years
from okama_planner.inputs import GoalIn, PlanInputs
from okama_planner.ledger.build import build_ledger
from okama_planner.ledger.calendar import month_index, month_key, year_index
from okama_planner.ledger.goals import goal_month_index
from okama_planner.ledger.indexation import value_in_year
from okama_planner.ledger.mortgage import amortisation_table
from okama_planner.ledger.types import Ledger, LedgerLine
from okama_planner.rates import RateSubject, resolve_rate
from okama_planner.scenarios import JointScenarios, weighted_returns

if TYPE_CHECKING:
    from okama_planner.api import ForecastRequest

Array = NDArray[np.float64]
PERCENTILES = (10, 25, 50, 75, 90)


@dataclass(frozen=True)
class FundingEvent:
    month: str
    kind: str
    label: str
    goal_id: int | None
    segment_id: str
    required: Array
    funded: Array
    unmet: Array
    funding_sources: dict[str, Array]


@dataclass(frozen=True)
class SegmentTransfer:
    month: str
    source: str
    destination: str
    reason: str
    amount: Array


@dataclass(frozen=True)
class SegmentedResult:
    months: tuple[str, ...]
    segment_ids: tuple[str, ...]
    segment_balances: Array
    portfolio: Array
    buffer: Array
    reserve: Array
    non_working: Array
    liability: Array
    capital: Array
    events: tuple[FundingEvent, ...]
    transfers: tuple[SegmentTransfer, ...]
    ledger: Ledger


def _active(schedule: tuple[StrategyStep, ...] | tuple[SurplusStep, ...], month: str) -> Any:
    return next(step for step in reversed(schedule) if step.start_month <= month)


def _frozen(array: Array) -> Array:
    return np.frombuffer(array.tobytes(), dtype=np.float64).reshape(array.shape)


class _Funding:
    """A month's mutable accounts; exported snapshots never alias these arrays."""

    def __init__(
        self,
        request: ForecastRequest,
        balances: Array,
        buffer: Array,
        cash: Array,
        completed: dict[str, NDArray[np.bool_]],
        month: str,
        transfers: list[SegmentTransfer],
    ) -> None:
        self.request = request
        self.spec = request.allocation
        self.balances, self.buffer, self.cash = balances, buffer, cash
        self.completed, self.month, self.transfers = completed, month, transfers
        self.ids = tuple(s.segment_id for s in self.spec.segments)
        self.index = {key: i for i, key in enumerate(self.ids)}
        self.segments = {s.segment_id: s for s in self.spec.segments}

    def donors(self, funder: str) -> tuple[str, ...]:
        if self.request.portfolio_mode == "single":
            return self.ids
        if self.spec.transfer_policy == "none":
            return (funder,)
        return (funder, *(key for key in self.spec.transfer_order if key != funder))

    def available(self, funder: str, order: tuple[str, ...]) -> Array:
        values = {
            "cash": self.cash,
            "buffer": self.buffer,
            "segment": self.balances[:, [self.index[k] for k in self.donors(funder)]].sum(1),
        }
        return sum((values[key] for key in order), np.zeros(len(self.cash)))

    def pay(
        self,
        required: Array,
        funder: str,
        *,
        all_or_nothing: bool = False,
        sale: Array | None = None,
        sale_label: str | None = None,
        reserve_topup: bool = False,
    ) -> tuple[Array, dict[str, Array]]:
        order = self.spec.reserve_funding_source_order if reserve_topup else self.spec.funding_source_order
        need = required.copy()
        allowed = np.ones(need.shape, dtype=bool)
        if all_or_nothing:
            allowed = self.available(funder, order) + (0 if sale is None else sale) >= need - 1e-9
            need = np.where(allowed, need, 0)
        sources: dict[str, Array] = {}
        if sale is not None:
            proceeds = np.where(allowed, sale, 0)
            self.cash += proceeds
            # Sale is a conversion of owned property into cash, separately traceable.
            # Attribute only proceeds actually consumed, not the full sale twice.
        for source in order:
            if source == "segment":
                for donor in self.donors(funder):
                    account = self.balances[:, self.index[donor]]
                    used = np.minimum(account, need)
                    account -= used
                    need -= used
                    sources[f"segment:{donor}"] = _frozen(used)
                    if donor != funder and self.request.portfolio_mode == "per_goal" and np.any(used > 0):
                        # An incoming transfer is immediately spent by the receiving segment.
                        self.transfers.append(
                            SegmentTransfer(self.month, donor, funder, "shortfall", _frozen(used))
                        )
            else:
                account = self.cash if source == "cash" else self.buffer
                used = np.minimum(account, need)
                account -= used
                need -= used
                if source == "cash" and sale is not None:
                    from_sale = np.minimum(used, proceeds)
                    sources[f"asset_sale:{sale_label}"] = _frozen(from_sale)
                    used = used - from_sale
                sources[source] = _frozen(used)
        funded = np.where(allowed, required - need, 0)
        return funded, sources

    def destination_masks(self, key: str) -> dict[str, NDArray[np.bool_]]:
        """Resolve the validated completion chain for every path without Python path loops."""
        masks = {}
        moving = np.ones(len(self.cash), dtype=bool)
        while np.any(moving):
            policy = self.segments[key].completion
            if policy.action == "retain":
                masks[key] = moving
                break
            masks[key] = moving & ~self.completed[key]
            moving = moving & self.completed[key]
            key = policy.destination
        return masks

    def complete(self, key: str, success: NDArray[np.bool_]) -> None:
        segment = self.spec.segments[self.index[key]]
        new = success & ~self.completed[key]
        self.completed[key] |= new
        if segment.completion.action == "retain":
            return
        # Resolve already completed destinations for each path without losing surplus.
        for destination, resolved in self.destination_masks(key).items():
            mask = new & resolved
            amount = np.where(mask, self.balances[:, self.index[key]], 0)
            if np.any(amount > 0):
                self.balances[:, self.index[key]] -= amount
                self.balances[:, self.index[destination]] += amount
                self.transfers.append(
                    SegmentTransfer(self.month, key, destination, "completion", _frozen(amount))
                )

    def invest(self) -> None:
        weights = _active(self.spec.surplus_weights, self.month).weights
        if self.request.portfolio_mode == "single":
            self.balances[:, self.index[self.spec.household_segment_id]] += self.cash
        else:
            # The completion graph was validated acyclic. Redirect per scenario, conserving every cent.
            for weight in weights:
                contribution = self.cash * weight.weight
                for destination, mask in self.destination_masks(weight.segment_id).items():
                    self.balances[:, self.index[destination]] += np.where(mask, contribution, 0)
        self.cash[:] = 0


def _initial_debt(request: ForecastRequest, paths: int) -> list[Array]:
    debts = []
    for loan in request.plan.liabilities:
        before = -month_index(request.plan.t0, loan.start_month)
        table = amortisation_table(loan.principal, loan.annual_rate, loan.monthly_payment, max_months=before)
        balance = table[-1].balance if table else loan.principal
        debts.append(np.full(paths, balance))
    return debts


@dataclass
class _GoalStates:
    plan: PlanInputs
    reserve: Array
    debts: list[Array]
    properties: dict[str, Array]
    property_factors: dict[str, float]
    goal_good: dict[int, NDArray[np.bool_]]
    goals: dict[int, GoalIn]
    funders: dict[int, str]
    asset_keys: dict[str, str]
    last_goal_events: dict[int, str]


def _source_events(
    plan: PlanInputs, ledger: Ledger
) -> tuple[dict[str, list[LedgerLine]], dict[str, list[GoalIn]]]:
    months = len(ledger.months)
    by_month: dict[str, list[LedgerLine]] = {month: [] for month in ledger.months}
    for line in ledger.lines:
        if line.line_kind in {"income", "expense", "goal_outflow"}:
            by_month[line.month].append(line)
    reserve_goals = {month: [] for month in ledger.months}
    for goal in plan.goals:
        if goal.kind == "reserve_topup":
            n = goal_month_index(goal, plan.t0)
            if n < months:
                reserve_goals[ledger.months[n]].append(goal)
    return by_month, reserve_goals


def _strategy_returns(
    request: ForecastRequest, scenarios: JointScenarios, months: int, paths: int
) -> dict[str, Array]:
    spec = request.allocation
    plan = request.plan
    monthly_returns = {}
    schedules = (
        [("single", spec.single_strategy)]
        if request.portfolio_mode == "single"
        else [(s.segment_id, s.strategy) for s in spec.segments]
    )
    for key, schedule in schedules:
        monthly_returns[key] = np.empty((months, paths))
        for i, step in enumerate(schedule):
            start = month_index(plan.t0, step.start_month)
            stop = month_index(plan.t0, schedule[i + 1].start_month) if i + 1 < len(schedule) else months
            values = weighted_returns(scenarios, {w.asset: w.weight for w in step.weights})
            monthly_returns[key][start:stop] = values[start:stop]
    return monthly_returns


def _pending_events(
    plan: PlanInputs,
    sources: list[LedgerLine],
    reserves: list[GoalIn],
    debts: list[Array],
    priorities: dict[str, int],
) -> list[tuple[str, Any, int | None]]:
    pending = [
        ("expense" if line.goal_id is None else f"goal:{line.goal_id}", line, None)
        for line in sources
        if line.line_kind != "income"
    ]
    pending.extend((f"goal:{goal.goal_id}", goal, None) for goal in reserves)
    for i, loan in enumerate(plan.liabilities):
        debts[i] *= 1 + loan.annual_rate / 12
        if np.any(debts[i] > 1e-9):
            pending.append(("mortgage_payment", loan, i))
    return sorted(pending, key=lambda x: priorities[x[0]])


def _requirements(
    item: Any, goal: GoalIn | None, loan_index: int | None, state: _GoalStates
) -> tuple[str, Array, Array | None]:
    if loan_index is not None:
        return "mortgage_payment", np.minimum(state.debts[loan_index], item.monthly_payment), None
    if goal and goal.kind == "reserve_topup":
        rate = resolve_rate(RateSubject.GOAL, goal.indexation_rate, state.plan.rates)
        target = value_in_year(goal.amount_pv, rate, goal.pv_year, goal.target_year)
        return "reserve_topup", np.maximum(0, target - state.reserve), None
    sale = (
        state.properties[state.asset_keys[goal.replaces_asset]].copy()
        if goal and goal.replaces_asset is not None
        else None
    )
    return item.line_kind, np.full(len(state.reserve), -item.amount), sale


def _apply_goal(
    state: _GoalStates,
    funding: _Funding,
    goal: GoalIn,
    funder: str,
    required: Array,
    funded: Array,
    good: NDArray[np.bool_],
) -> None:
    state.goal_good[goal.goal_id] &= good
    if goal.kind == "reserve_topup":
        state.reserve += funded
    if goal.kind == "lump":
        if goal.replaces_asset is not None:
            key = state.asset_keys[goal.replaces_asset]
            state.properties[key] = np.where(good, 0, state.properties[key])
        if goal.becomes_asset:
            label = f"acquired:{goal.goal_id}"
            state.properties[label] = np.where(good, required, 0)
            rate = resolve_rate(RateSubject.GOAL, goal.indexation_rate, state.plan.rates)
            state.property_factors[label] = (1 + rate) ** (1 / 12)
    if goal.kind != "retirement_income" or funding.month == state.last_goal_events.get(goal.goal_id):
        funding.complete(funder, state.goal_good[goal.goal_id])


def _fund_event(
    funding: _Funding, state: _GoalStates, tag: str, item: Any, loan_index: int | None
) -> FundingEvent:
    goal = state.goals.get(item.goal_id) if tag.startswith("goal:") else None
    funder = state.funders[goal.goal_id] if goal else funding.spec.household_segment_id
    kind, required, sale = _requirements(item, goal, loan_index, state)
    funded, sources = funding.pay(
        required,
        funder,
        all_or_nothing=bool(goal and goal.kind == "lump"),
        sale=sale,
        sale_label=goal.replaces_asset if goal else None,
        reserve_topup=kind == "reserve_topup",
    )
    unmet = np.maximum(0, required - funded)
    if loan_index is not None:
        state.debts[loan_index] -= funded
    elif goal:
        _apply_goal(state, funding, goal, funder, required, funded, unmet <= 1e-8)
    return FundingEvent(
        funding.month,
        kind,
        item.label,
        goal.goal_id if goal else None,
        funder,
        _frozen(required),
        _frozen(funded),
        _frozen(unmet),
        sources,
    )


def _rebalance_buffer(funding: _Funding, n: int, ledger: Ledger, planned_flows: dict[str, float]) -> None:
    if funding.spec.buffer_policy != "planned_targets":
        return
    plan = funding.request.plan
    stop = (
        len(ledger.months)
        if not plan.reserves_until_retirement
        else year_index(plan.t0, plan.retirement_year)
    )
    future = ledger.months[n + 1 : min(n + 1 + plan.buffer_lookahead_months, stop)]
    target = -sum(min(0, planned_flows[key]) for key in future)
    released = np.maximum(0, funding.buffer - target)
    funding.buffer -= released
    funding.cash += released
    deposited = np.minimum(funding.cash, np.maximum(0, target - funding.buffer))
    funding.buffer += deposited
    funding.cash -= deposited


def _finite_states(*values: Array) -> None:
    if not all(np.all(np.isfinite(value)) for value in values):
        raise ValueError("Actual scenario states must remain finite")


def _planned_flows(ledger: Ledger) -> dict[str, float]:
    planned_flows = dict.fromkeys(ledger.months, 0.0)
    for line in ledger.lines:
        if line.line_kind in {
            "income",
            "expense",
            "goal_outflow",
            "mortgage_payment",
            "reserve_topup",
            "asset_sale",
        }:
            planned_flows[line.month] += line.amount
    return planned_flows


def _last_goal_events(ledger: Ledger) -> dict[int, str]:
    dates: dict[int, str] = {}
    for line in ledger.lines:
        if line.line_kind == "goal_outflow" and line.goal_id is not None:
            dates[line.goal_id] = max(dates.get(line.goal_id, ""), line.month)
    return dates


def _simulate_segments(request: ForecastRequest, scenarios: JointScenarios) -> SegmentedResult:
    """Run single pooled or per-goal actual funding on an already sampled shared cube."""
    spec = request.allocation
    if spec is None or request.joint_history is None:
        raise ValueError("Joint simulation requires allocation and joint_history")
    spec.validate_plan(request.plan, request.joint_history, request.currency)
    months = 12 * effective_horizon_years(request.plan)
    paths = request.mc_number
    if scenarios.returns.shape[:2] != (months, paths):
        raise ValueError("Scenario cube must match request horizon and path count")
    plan = request.plan
    ledger = build_ledger(plan)
    ids = tuple(s.segment_id for s in spec.segments)
    shape = (months + 1, paths)
    segments = np.zeros((*shape, len(ids)))
    initial = [s.opening_amount for s in spec.segments]
    if request.portfolio_mode == "single":
        initial = [sum(initial) if key == spec.household_segment_id else 0 for key in ids]
    segments[0] = initial
    balances = segments[0].copy()
    buffer, reserve, non_working, liability = (np.zeros(shape) for _ in range(4))
    buffer[0] = sum(a.amount for a in plan.assets if a.asset_class == "savings")
    reserve_assets = [a for a in plan.assets if a.asset_class == "reserve"]
    reserve[0] = sum(a.amount for a in reserve_assets)
    explicit_reserve = next((a.growth_rate for a in reserve_assets if a.growth_rate is not None), None)
    reserve_factor = (1 + resolve_rate(RateSubject.ASSET_RESERVE, explicit_reserve, plan.rates)) ** (1 / 12)
    properties = {
        f"initial:{i}": np.full(paths, a.amount)
        for i, a in enumerate(plan.assets)
        if a.asset_class == "non_working"
    }
    property_factors = {
        f"initial:{i}": (1 + resolve_rate(RateSubject.ASSET_NON_WORKING, a.growth_rate, plan.rates))
        ** (1 / 12)
        for i, a in enumerate(plan.assets)
        if a.asset_class == "non_working"
    }
    non_working[0] = sum(properties.values(), np.zeros(paths))
    debts = _initial_debt(request, paths)
    liability[0] = sum(debts, np.zeros(paths))
    events: list[FundingEvent] = []
    transfers: list[SegmentTransfer] = []
    completed = {key: np.zeros(paths, dtype=bool) for key in ids}
    goal_good = {g.goal_id: np.ones(paths, dtype=bool) for g in plan.goals}
    funders = {g.goal_id: g.segment_id for g in spec.goal_funders}
    priorities = {key: i for i, key in enumerate(spec.event_priority)}
    by_month, reserve_goals = _source_events(plan, ledger)
    monthly_returns = _strategy_returns(request, scenarios, months, paths)
    planned_flows = _planned_flows(ledger)
    current_buffer, current_reserve = buffer[0].copy(), reserve[0].copy()
    state = _GoalStates(
        plan,
        current_reserve,
        debts,
        properties,
        property_factors,
        goal_good,
        {g.goal_id: g for g in plan.goals},
        funders,
        {a.label: f"initial:{i}" for i, a in enumerate(plan.assets) if a.asset_class == "non_working"},
        _last_goal_events(ledger),
    )
    for n, month in enumerate(ledger.months):
        for index, key in enumerate(ids):
            balances[:, index] *= (
                1 + monthly_returns["single" if request.portfolio_mode == "single" else key][n]
            )
        if n:
            current_buffer *= (1 + plan.rates.buffer_rate) ** (1 / 12)
            current_reserve *= reserve_factor
            for label in properties:
                properties[label] *= property_factors[label]
        cash = np.full(
            paths,
            sum(line.amount for line in by_month[month] if line.line_kind == "income"),
            dtype=np.float64,
        )
        if plan.reserves_until_retirement and n >= year_index(plan.t0, plan.retirement_year):
            cash += current_buffer
            current_buffer[:] = 0
        funding = _Funding(request, balances, current_buffer, cash, completed, month, transfers)
        pending = _pending_events(plan, by_month[month], reserve_goals[month], debts, priorities)
        for tag, item, loan_index in pending:
            events.append(_fund_event(funding, state, tag, item, loan_index))
        _rebalance_buffer(funding, n, ledger, planned_flows)
        funding.invest()
        segments[n + 1] = balances
        buffer[n + 1], reserve[n + 1] = current_buffer, current_reserve
        non_working[n + 1] = sum(properties.values(), np.zeros(paths))
        liability[n + 1] = sum(debts, np.zeros(paths))
        _finite_states(balances, current_buffer, current_reserve, non_working[n + 1], liability[n + 1])
    portfolio = segments.sum(2)
    capital = portfolio + buffer + reserve + non_working - liability
    return SegmentedResult(
        (month_key(plan.t0, -1), *ledger.months),
        ids,
        _frozen(segments),
        _frozen(portfolio),
        _frozen(buffer),
        _frozen(reserve),
        _frozen(non_working),
        _frozen(liability),
        _frozen(capital),
        tuple(events),
        tuple(transfers),
        ledger,
    )


def simulate_segments(request: ForecastRequest, scenarios: JointScenarios) -> SegmentedResult:
    """Run validated policies, failing explicitly if finite inputs overflow actual balances."""
    try:
        with np.errstate(over="raise", invalid="raise"):
            return _simulate_segments(request, scenarios)
    except FloatingPointError as error:
        raise ValueError("Actual scenario states must remain finite") from error


def _chart(months: tuple[str, ...], values: Array) -> list[dict[str, Any]]:
    quantiles = np.percentile(values, PERCENTILES, axis=1).T
    return [
        {"month": month, **{f"p{p}": float(v) for p, v in zip(PERCENTILES, row, strict=True)}}
        for month, row in zip(months, quantiles, strict=True)
    ]


def joint_forecast_result(request: ForecastRequest, scenarios: JointScenarios) -> dict[str, Any]:
    """JSON-ready family and segment outcomes; quantiles follow pathwise aggregation."""
    from okama_planner.api import _digest

    result = simulate_segments(request, scenarios)
    paths = request.mc_number
    successful = np.ones(paths, dtype=bool)
    total_unmet = np.zeros(paths)
    for event in result.events:
        successful &= event.unmet <= 1e-8
        total_unmet += event.unmet
    first_shortfall = np.full(paths, len(result.months) - 1)
    for event in result.events:
        first_shortfall = np.where(
            event.unmet > 1e-8,
            np.minimum(first_shortfall, month_index(request.plan.t0, event.month)),
            first_shortfall,
        )
    metrics = {
        "probability_of_success": float(successful.mean()),
        "median_survival_years": float(np.median(first_shortfall) / 12),
        "unmet_mean": float(total_unmet.mean()),
        **{f"terminal_p{p}": float(np.percentile(result.portfolio[-1], p)) for p in PERCENTILES},
    }
    goals = []
    for goal in request.plan.goals:
        events = [event for event in result.events if event.goal_id == goal.goal_id]
        if not events:
            continue
        good = np.ones(paths, dtype=bool)
        unmet = np.zeros(paths)
        funded = np.zeros(paths)
        for event in events:
            good &= event.unmet <= 1e-8
            unmet += event.unmet
            funded += event.funded
        n = month_index(request.plan.t0, events[0].month)
        goals.append(
            {
                "goal_id": goal.goal_id,
                "label": goal.label,
                "month": events[0].month,
                "amount_nominal": float(events[0].required.mean()),
                "p_affordable": float(good.mean()),
                "p_funded": float(good.mean()),
                "p_full_stream": float(good.mean()) if goal.kind == "retirement_income" else None,
                "p_alive": float((result.portfolio[n] > 0).mean()),
                "funded_mean": float(funded.mean()),
                "unmet_mean": float(unmet.mean()),
                "funding_basis": "full_stream" if goal.kind == "retirement_income" else "actual_event",
            }
        )
    event_rows = [
        {
            "month": e.month,
            "kind": e.kind,
            "label": e.label,
            "goal_id": e.goal_id,
            "segment_id": e.segment_id,
            "required_mean": float(e.required.mean()),
            "funded_mean": float(e.funded.mean()),
            "unmet_mean": float(e.unmet.mean()),
            "p_funded": float((e.unmet <= 1e-8).mean()),
            "funding_sources": {k: float(v.mean()) for k, v in e.funding_sources.items()},
        }
        for e in result.events
    ]
    sides = {
        "buffer": result.buffer,
        "reserve": result.reserve,
        "non_working": result.non_working,
        "liability": result.liability,
    }
    side_charts = {key: _chart(result.months, values) for key, values in sides.items()}
    summaries = [
        {
            "month": month,
            "portfolio_mean": float(result.portfolio[n].mean()),
            "capital_mean": float(result.capital[n].mean()),
            **{f"{key}_mean": float(values[n].mean()) for key, values in sides.items()},
            **{key: side_charts[key][n] for key in sides},
        }
        for n, month in enumerate(result.months)
    ]
    segments = []
    for i, segment in enumerate(request.allocation.segments):
        selected = [e for e in result.events if e.segment_id == segment.segment_id]
        success = np.ones(paths, dtype=bool)
        for e in selected:
            success &= e.unmet <= 1e-8
        segments.append(
            {
                **segment.model_dump(mode="json"),
                "active_strategy": [
                    s.model_dump(mode="json")
                    for s in (
                        request.allocation.single_strategy
                        if request.portfolio_mode == "single"
                        else segment.strategy
                    )
                ],
                "probability_of_full_funding": float(success.mean()),
                "chart": _chart(result.months, result.segment_balances[:, :, i]),
            }
        )
    return {
        "schema_version": "1.1",
        "currency": request.currency,
        "portfolio_mode": request.portfolio_mode,
        "metrics": metrics,
        "goals": goals,
        "ledger": asdict(result.ledger),
        "ledger_basis": "planned_requirements_not_actual_balances",
        "portfolio_flow": dict(result.ledger.portfolio_flow),
        "charts": {
            "portfolio": _chart(result.months, result.portfolio),
            "capital": _chart(result.months, result.capital),
        },
        "segments": segments,
        "allocation": request.allocation.model_dump(mode="json"),
        "actual": {
            "monthly_summaries": summaries,
            "event_funding": event_rows,
            "transfers": [
                {
                    "month": t.month,
                    "source": t.source,
                    "destination": t.destination,
                    "reason": t.reason,
                    "amount_mean": float(t.amount.mean()),
                }
                for t in result.transfers
            ],
        },
        "provenance": {
            "engine": "joint_funding",
            "input_sha256": _digest(request.model_dump(mode="json")),
            "seed": request.seed,
            "mc_number": request.mc_number,
            "distribution": "synchronized_bootstrap",
            "match_moments": False,
            "data_source": "provided_joint_history",
            "stages": [],
            "history_sha256": scenarios.history_sha256,
            "scenario_rows_sha256": _digest(scenarios.row_indices.tolist()),
            "funding_basis": "all_required_events_over_horizon",
            "balance_basis": "actual_scenario_states",
        },
    }
