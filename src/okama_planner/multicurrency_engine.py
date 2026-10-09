"""Coordinate native accounts and a single household budget on shared market/FX paths."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

import numpy as np

from okama_planner.api import ForecastRequest, _digest
from okama_planner.horizon import effective_horizon_years
from okama_planner.ledger.build import build_ledger
from okama_planner.ledger.calendar import month_index, month_key, year_index
from okama_planner.ledger.types import Ledger, LedgerLine
from okama_planner.multicurrency import MulticurrencyRequest, sample_multicurrency
from okama_planner.rates import RateSubject, resolve_rate
from okama_planner.scenarios import JointScenarios
from okama_planner.segmented import (
    PERCENTILES,
    Array,
    FundingEvent,
    _chart,
    _finite_states,
    _Funding,
    _fund_event,
    _GoalStates,
    _initial_debt,
    _last_goal_events,
    _pending_events,
    _planned_flows,
    _rebalance_buffer,
    _source_events,
    _strategy_returns,
    _apply_goal,
)


class _Group:
    """Mutable native accounts and their immutable monthly snapshots."""

    def __init__(self, request: ForecastRequest, scenarios: JointScenarios) -> None:
        self.request = request
        plan, spec = request.plan, request.allocation
        paths = request.mc_number
        months = 12 * effective_horizon_years(plan)
        # Share-based pensions need scenario FX, so build only their dated skeleton here.
        ledger_plan = plan.model_copy(
            update={
                "goals": tuple(
                    g.model_copy(update={"amount_basis": "amount", "amount_pv": 0})
                    if g.amount_basis == "expense_share"
                    else g
                    for g in plan.goals
                )
            }
        )
        self.ledger = build_ledger(ledger_plan)
        self.ids = tuple(s.segment_id for s in spec.segments)
        shape = (months + 1, paths)
        self.segments = np.zeros((*shape, len(self.ids)))
        opening = [s.opening_amount for s in spec.segments]
        if request.portfolio_mode == "single":
            opening = [sum(opening) if key == spec.household_segment_id else 0 for key in self.ids]
        self.segments[0] = opening
        self.balances = self.segments[0].copy()
        self.sides = {key: np.zeros(shape) for key in ("buffer", "reserve", "non_working", "liability")}
        self.buffer = np.full(
            paths, sum(a.amount for a in plan.assets if a.asset_class == "savings"), dtype=float
        )
        self.reserve = np.full(
            paths, sum(a.amount for a in plan.assets if a.asset_class == "reserve"), dtype=float
        )
        explicit = next(
            (a.growth_rate for a in plan.assets if a.asset_class == "reserve" and a.growth_rate is not None),
            None,
        )
        self.reserve_factor = (1 + resolve_rate(RateSubject.ASSET_RESERVE, explicit, plan.rates)) ** (1 / 12)
        properties = {
            f"initial:{i}": np.full(paths, a.amount)
            for i, a in enumerate(plan.assets)
            if a.asset_class == "non_working"
        }
        factors = {
            f"initial:{i}": (1 + resolve_rate(RateSubject.ASSET_NON_WORKING, a.growth_rate, plan.rates))
            ** (1 / 12)
            for i, a in enumerate(plan.assets)
            if a.asset_class == "non_working"
        }
        self.state = _GoalStates(
            plan,
            self.reserve,
            _initial_debt(request, paths),
            properties,
            factors,
            {g.goal_id: np.ones(paths, dtype=bool) for g in plan.goals},
            {g.goal_id: g for g in plan.goals},
            {g.goal_id: g.segment_id for g in spec.goal_funders},
            {a.label: f"initial:{i}" for i, a in enumerate(plan.assets) if a.asset_class == "non_working"},
            _last_goal_events(self.ledger),
        )
        self.completed = {key: np.zeros(paths, dtype=bool) for key in self.ids}
        self.events: list[FundingEvent] = []
        self.transfers = []
        self.sources, self.reserves = _source_events(ledger_plan, self.ledger)
        self.returns = _strategy_returns(request, scenarios, months, paths)
        self.priorities = {key: i for i, key in enumerate(spec.event_priority)}
        self.planned = _planned_flows(self.ledger)
        self.snapshot(0)

    def start(self, n: int, month: str) -> _Funding:
        plan = self.request.plan
        for i, key in enumerate(self.ids):
            key = "single" if self.request.portfolio_mode == "single" else key
            self.balances[:, i] *= 1 + self.returns[key][n]
        if n:
            self.buffer *= (1 + plan.rates.buffer_rate) ** (1 / 12)
            self.reserve *= self.reserve_factor
            for key in self.state.properties:
                self.state.properties[key] *= self.state.property_factors[key]
        cash = np.zeros(self.request.mc_number)
        if plan.reserves_until_retirement and n >= year_index(plan.t0, plan.retirement_year):
            cash += self.buffer
            self.buffer[:] = 0
        return _Funding(self.request, self.balances, self.buffer, cash, self.completed, month, self.transfers)

    def snapshot(self, n: int) -> None:
        self.segments[n] = self.balances
        self.sides["buffer"][n], self.sides["reserve"][n] = self.buffer, self.reserve
        self.sides["non_working"][n] = sum(self.state.properties.values(), np.zeros(self.request.mc_number))
        self.sides["liability"][n] = sum(self.state.debts, np.zeros(self.request.mc_number))
        _finite_states(self.balances, *(v[n] for v in self.sides.values()))

    @property
    def portfolio(self) -> Array:
        return self.segments.sum(2)

    @property
    def capital(self) -> Array:
        return (
            self.portfolio
            + self.sides["buffer"]
            + self.sides["reserve"]
            + self.sides["non_working"]
            - self.sides["liability"]
        )


def _fx_row(
    month: str,
    group_id: str,
    currency: str,
    direction: str,
    reason: str,
    native: Array,
    base: Array,
    fee: Array,
    quote: Array,
    base_currency: str,
) -> dict[str, Any]:
    """Expose exact path traces as well as report-friendly scalar means."""
    return {
        "month": month,
        "group_id": group_id,
        "currency": currency,
        "direction": direction,
        "source_currency": base_currency if direction == "contribution" else currency,
        "destination_currency": currency if direction == "contribution" else base_currency,
        "source_amount_mean": float(base.mean()) if direction == "contribution" else float(native.mean()),
        "destination_amount_mean": float(native.mean())
        if direction == "contribution"
        else float(base.mean()),
        "rate_mean": float(quote.mean()),
        "reason": reason,
        "native_amount_mean": float(native.mean()),
        "base_amount_mean": float(base.mean()),
        "fee_base_mean": float(fee.mean()),
        "fx_rate_mean": float(quote.mean()),
        "native_amount": native.tolist(),
        "base_amount": base.tolist(),
        "fee_base": fee.tolist(),
        "fx_rate": quote.tolist(),
    }


def _convert_in(
    request: MulticurrencyRequest,
    group_id: str,
    funding: _Funding,
    base: Array,
    quote: Array,
    reason: str,
    transfers: list[dict[str, Any]],
) -> Array:
    fee = base * (request.conversion_fee_rate if funding.request.currency != request.currency else 0)
    native = (base - fee) / quote
    funding.cash += native
    if np.any(base > 0):
        transfers.append(
            _fx_row(
                funding.month,
                group_id,
                funding.request.currency,
                "contribution",
                reason,
                native,
                base,
                fee,
                quote,
                request.currency,
            )
        )
    return native


def _pay_household(
    request: MulticurrencyRequest,
    cash: Array,
    required: Array,
    fundings: dict[str, _Funding],
    rates: dict[str, Array],
    transfers: list[dict[str, Any]],
    reason: str,
    exclude: str | None = None,
) -> tuple[Array, dict[str, Array]]:
    from_cash = np.minimum(cash, required)
    cash -= from_cash
    remaining = required - from_cash
    sources = {"cash": from_cash.copy()}
    for key in request.household_funding_order:
        if key == exclude:
            continue
        funding = fundings[key]
        quote = rates[funding.request.currency]
        fee_rate = request.conversion_fee_rate if funding.request.currency != request.currency else 0
        native, used = funding.pay(remaining / quote / (1 - fee_rate), funding.spec.household_segment_id)
        gross = native * quote
        fee = gross * fee_rate
        received = gross - fee
        remaining = np.maximum(0, remaining - received)
        for source, amount in used.items():
            sources[f"group:{key}:{source}"] = amount * quote * (1 - fee_rate)
        if np.any(native > 0):
            transfers.append(
                _fx_row(
                    funding.month,
                    key,
                    funding.request.currency,
                    "withdrawal",
                    reason,
                    native,
                    received,
                    fee,
                    quote,
                    request.currency,
                )
            )
    return required - remaining, sources


def _event_row(event: FundingEvent, quote: Array | None = None) -> dict[str, Any]:
    row = {
        "month": event.month,
        "kind": event.kind,
        "label": event.label,
        "goal_id": event.goal_id,
        "segment_id": event.segment_id,
        "required_mean": float(event.required.mean()),
        "funded_mean": float(event.funded.mean()),
        "unmet_mean": float(event.unmet.mean()),
        "p_funded": float((event.unmet <= 1e-8).mean()),
        "funding_sources": {k: float(v.mean()) for k, v in event.funding_sources.items()},
    }
    if quote is not None:
        row.update(
            {
                "fx_rate": quote.tolist(),
                "fx_rate_mean": float(quote.mean()),
                **{
                    f"{key}_base_mean": float((values * quote).mean())
                    for key, values in (
                        ("required", event.required),
                        ("funded", event.funded),
                        ("unmet", event.unmet),
                    )
                },
                "required_native": event.required.tolist(),
                "funded_native": event.funded.tolist(),
                "unmet_native": event.unmet.tolist(),
            }
        )
    return row


def _metrics(
    events: list[FundingEvent],
    portfolio: Array,
    t0: str,
    months: int,
    success_events: list[FundingEvent] | None = None,
) -> dict[str, float]:
    paths = portfolio.shape[1]
    good = np.ones(paths, dtype=bool)
    unmet = np.zeros(paths)
    first = np.full(paths, months)
    for event in events:
        unmet += event.unmet
    for event in events if success_events is None else success_events:
        good &= event.unmet <= 1e-8
        first = np.where(event.unmet > 1e-8, np.minimum(first, month_index(t0, event.month)), first)
    return {
        "probability_of_success": float(good.mean()),
        "unmet_mean": float(unmet.mean()),
        "median_survival_years": float(np.median(first) / 12),
        **{f"terminal_p{p}": float(np.percentile(portfolio[-1], p)) for p in PERCENTILES},
    }


def _native_result(
    group: _Group, original: ForecastRequest, scenarios: JointScenarios, outer_hash: str
) -> dict[str, Any]:
    request = group.request
    months = (month_key(request.plan.t0, -1), *group.ledger.months)
    charts = {"portfolio": _chart(months, group.portfolio), "capital": _chart(months, group.capital)}
    side_charts = {key: _chart(months, values) for key, values in group.sides.items()}
    goals = []
    for goal in request.plan.goals:
        selected = [e for e in group.events if e.goal_id == goal.goal_id]
        if not selected:
            continue
        good = np.logical_and.reduce([e.unmet <= 1e-8 for e in selected])
        goals.append(
            {
                "goal_id": goal.goal_id,
                "label": goal.label,
                "month": selected[0].month,
                "amount_nominal": float(selected[0].required.mean()),
                "p_affordable": float(good.mean()),
                "p_funded": float(good.mean()),
                "p_full_stream": float(good.mean()) if goal.kind == "retirement_income" else None,
                "p_alive": float(
                    (group.portfolio[month_index(request.plan.t0, selected[0].month)] > 0).mean()
                ),
                "funded_mean": float(sum(e.funded for e in selected).mean()),
                "unmet_mean": float(sum(e.unmet for e in selected).mean()),
                "funding_basis": "full_stream" if goal.kind == "retirement_income" else "actual_event",
            }
        )
    segments = []
    for i, segment in enumerate(request.allocation.segments):
        selected = [e for e in group.events if e.segment_id == segment.segment_id]
        good = np.ones(request.mc_number, dtype=bool)
        for event in selected:
            good &= event.unmet <= 1e-8
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
                "probability_of_full_funding": float(good.mean()),
                "chart": _chart(months, group.segments[:, :, i]),
            }
        )
    return {
        "schema_version": "1.1",
        "currency": request.currency,
        "portfolio_mode": request.portfolio_mode,
        "metrics": _metrics(group.events, group.portfolio, request.plan.t0, len(group.ledger.months)),
        "goals": goals,
        "charts": charts,
        "segments": segments,
        "ledger": asdict(group.ledger),
        "ledger_basis": "planned_native_requirements_shared_household",
        "portfolio_flow": dict(group.ledger.portfolio_flow),
        "allocation": request.allocation.model_dump(mode="json"),
        "actual": {
            "event_funding": [_event_row(e) for e in group.events],
            "monthly_summaries": [
                {
                    "month": month,
                    "portfolio_mean": float(group.portfolio[n].mean()),
                    "capital_mean": float(group.capital[n].mean()),
                    **{f"{key}_mean": float(values[n].mean()) for key, values in group.sides.items()},
                    **{key: side_charts[key][n] for key in group.sides},
                }
                for n, month in enumerate(months)
            ],
            "transfers": [
                {
                    "month": t.month,
                    "source": t.source,
                    "destination": t.destination,
                    "reason": t.reason,
                    "amount_mean": float(t.amount.mean()),
                }
                for t in group.transfers
            ],
        },
        "provenance": {
            "engine": "multicurrency_joint_funding",
            "input_sha256": _digest(original.model_dump(mode="json")),
            "household_input_sha256": outer_hash,
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


def _pay_debts(
    request: MulticurrencyRequest,
    key: str,
    group: _Group,
    funding: _Funding,
    pending: list[tuple[str, Any, int | None]],
    cash: Array,
    fundings: dict[str, _Funding],
    rates: dict[str, Array],
    fx_transfers: list[dict[str, Any]],
    month: str,
) -> None:
    """Common cash, native accounts, then explicitly ordered household rescue."""
    for _tag, item, loan_index in pending:
        if loan_index is None:
            continue
        quote = rates[group.request.currency]
        fee_rate = request.conversion_fee_rate if group.request.currency != request.currency else 0
        required = np.minimum(group.state.debts[loan_index], item.monthly_payment)
        allocated = np.minimum(cash, required * quote / (1 - fee_rate))
        cash -= allocated
        _convert_in(request, key, funding, allocated, quote, "mortgage_payment", fx_transfers)
        funded, sources = funding.pay(required, funding.spec.household_segment_id)
        remaining = np.maximum(0, required - funded)
        rescued, rescue_sources = _pay_household(
            request,
            cash,
            remaining * quote / (1 - fee_rate),
            fundings,
            rates,
            fx_transfers,
            "mortgage_rescue",
            exclude=key,
        )
        rescue_native = _convert_in(request, key, funding, rescued, quote, "mortgage_rescue", fx_transfers)
        funding.cash -= rescue_native
        funded += rescue_native
        sources.update(
            {
                f"household:{source}": amount * (1 - fee_rate) / quote
                for source, amount in rescue_sources.items()
            }
        )
        group.state.debts[loan_index] -= funded
        group.events.append(
            FundingEvent(
                month,
                "mortgage_payment",
                item.label,
                None,
                funding.spec.household_segment_id,
                required,
                funded,
                np.maximum(0, required - funded),
                sources,
            )
        )


def _pay_goals(
    group: _Group,
    funding: _Funding,
    pending: list[tuple[str, Any, int | None]],
    expense_amount: float,
    rates: dict[str, Array],
    month: str,
) -> None:
    """Native goals cannot draw on accounts belonging to another currency."""
    for tag, item, loan_index in pending:
        if loan_index is not None:
            continue
        goal = group.state.goals.get(item.goal_id) if tag.startswith("goal:") else None
        if goal is not None and goal.amount_basis == "expense_share":
            required = (
                np.full(group.request.mc_number, expense_amount * goal.amount_pv)
                / rates[group.request.currency]
            )
            funder = group.state.funders[goal.goal_id]
            funded, sources = funding.pay(required, funder)
            unmet = np.maximum(0, required - funded)
            _apply_goal(group.state, funding, goal, funder, required, funded, unmet <= 1e-8)
            event = FundingEvent(
                month, "goal_outflow", goal.label, goal.goal_id, funder, required, funded, unmet, sources
            )
        else:
            event = _fund_event(funding, group.state, tag, item, loan_index)
        group.events.append(event)


def _household_ledger(ledger: Ledger, replaced_months: set[str]) -> Ledger:
    """The common ledger owns external income/spending, never native account allocations."""
    lines = tuple(
        line
        for line in ledger.lines
        if line.line_kind in {"income", "expense"}
        and not (line.line_kind == "expense" and line.month in replaced_months)
    )
    flows = {month: sum(line.amount for line in lines if line.month == month) for month in ledger.months}
    return replace(
        ledger,
        lines=(
            *lines,
            *(
                LedgerLine(month, "portfolio_flow", "Common budget balance", value)
                for month, value in flows.items()
            ),
        ),
        portfolio_flow=flows,
        buffer_balance=tuple(0.0 for _ in ledger.months),
        buffer_by_goal=(),
    )


def _attach_context(
    results: list[dict[str, Any]], groups: dict[str, _Group], fx_transfers: list[dict[str, Any]]
) -> None:
    """Disclose coupled financing and the non-scalar basis of share-pension requirements."""
    for result in results:
        native = result["result"]
        selected = [row for row in fx_transfers if row["group_id"] == result["group_id"]]
        native["actual"]["fx_transfers"] = selected
        native["ledger_requirement_basis"] = (
            "common_budget_expense_share_converted_per_path"
            if any(g.amount_basis == "expense_share" for g in groups[result["group_id"]].request.plan.goals)
            else "planned_native_requirements"
        )
        native["ledger_zero_skeleton_goal_ids"] = [
            g.goal_id
            for g in groups[result["group_id"]].request.plan.goals
            if g.amount_basis == "expense_share"
        ]
        for summary in native["actual"]["monthly_summaries"]:
            current = [row for row in selected if row["month"] == summary["month"]]
            summary["contribution_mean"] = sum(
                row["native_amount_mean"]
                for row in current
                if row["direction"] == "contribution" and row["reason"] == "surplus"
            )
            summary["household_withdrawal_mean"] = sum(
                row["native_amount_mean"] for row in current if row["direction"] == "withdrawal"
            )
            summary["fee_base_mean"] = sum(row["fee_base_mean"] for row in current)


def _simulate(request: MulticurrencyRequest) -> dict[str, Any]:
    scenarios, quotes, common = sample_multicurrency(request)
    groups = {
        g.group_id: _Group(
            g.request.model_copy(update={"mc_number": request.mc_number, "seed": request.seed}),
            scenarios[g.group_id],
        )
        for g in request.groups
    }
    household_ledger = build_ledger(request.household)
    household_sources, _ = _source_events(request.household, household_ledger)
    months = household_ledger.months
    household_events: list[FundingEvent] = []
    fx_transfers: list[dict[str, Any]] = []
    flows = []
    replaced_months = {
        month
        for group in groups.values()
        for month, events in group.sources.items()
        if request.household.pension_replaces_expenses
        and any(
            event.goal_id is not None and group.state.goals[event.goal_id].kind == "retirement_income"
            for event in events
        )
    }
    for n, month in enumerate(months):
        rates = {currency: values[n + 1] for currency, values in quotes.items()}
        fundings = {key: group.start(n, month) for key, group in groups.items()}
        income = sum(e.amount for e in household_sources[month] if e.line_kind == "income")
        cash = np.full(request.mc_number, income, dtype=float)
        expenses = [e for e in household_sources[month] if e.line_kind == "expense"]
        expense_amount = -sum(e.amount for e in expenses)
        if month not in replaced_months:
            for expense in expenses:
                required = np.full(request.mc_number, -expense.amount)
                funded, sources = _pay_household(
                    request, cash, required, fundings, rates, fx_transfers, "household_expense"
                )
                household_events.append(
                    FundingEvent(
                        month,
                        "expense",
                        expense.label,
                        None,
                        "household",
                        required,
                        funded,
                        np.maximum(0, required - funded),
                        sources,
                    )
                )
        pending = {}
        for key, group in groups.items():
            funding = fundings[key]
            pending[key] = _pending_events(
                group.request.plan,
                group.sources[month],
                group.reserves[month],
                group.state.debts,
                group.priorities,
            )
            _pay_debts(request, key, group, funding, pending[key], cash, fundings, rates, fx_transfers, month)
        weights = next(
            step.weights for step in reversed(request.contribution_schedule) if step.start_month <= month
        )
        distributable = cash.copy()
        for key, group in groups.items():
            _convert_in(
                request,
                key,
                fundings[key],
                distributable * weights[key],
                rates[group.request.currency],
                "surplus",
                fx_transfers,
            )
        cash[:] = 0
        for key, group in groups.items():
            funding = fundings[key]
            _pay_goals(group, funding, pending[key], expense_amount, rates, month)
            _rebalance_buffer(funding, n, group.ledger, group.planned)
            funding.invest()
            group.snapshot(n + 1)
        flows.append(
            {
                "month": month,
                "income_mean": float(income),
                "expense_mean": 0.0 if month in replaced_months else float(expense_amount),
                "contribution_base_mean": float(distributable.mean()),
            }
        )
    labels = (month_key(request.household.t0, -1), *months)
    portfolio = sum(
        (g.portfolio * quotes[g.request.currency] for g in groups.values()),
        np.zeros_like(next(iter(quotes.values()))),
    )
    capital = sum((g.capital * quotes[g.request.currency] for g in groups.values()), np.zeros_like(portfolio))
    base_events = list(household_events)
    event_rows = [
        {**_event_row(e, np.ones(request.mc_number)), "currency": request.currency, "group_id": None}
        for e in household_events
    ]
    for key, group in groups.items():
        for event in group.events:
            rate = quotes[group.request.currency][month_index(request.household.t0, event.month) + 1]
            base_events.append(
                FundingEvent(
                    event.month,
                    event.kind,
                    event.label,
                    event.goal_id,
                    event.segment_id,
                    event.required * rate,
                    event.funded * rate,
                    event.unmet * rate,
                    {},
                )
            )
            event_rows.append(
                {**_event_row(event, rate), "currency": group.request.currency, "group_id": key}
            )
    outer_hash = _digest(request.model_dump(mode="json"))
    results = [
        {
            "group_id": g.group_id,
            "currency": g.request.currency,
            "result": _native_result(groups[g.group_id], g.request, scenarios[g.group_id], outer_hash),
        }
        for g in request.groups
    ]
    _attach_context(results, groups, fx_transfers)
    side_values = {
        key: sum(
            (g.sides[key] * quotes[g.request.currency] for g in groups.values()), np.zeros_like(portfolio)
        )
        for key in next(iter(groups.values())).sides
    }
    side_charts = {key: _chart(labels, values) for key, values in side_values.items()}
    summaries = [
        {
            "month": month,
            "portfolio_mean": float(portfolio[n].mean()),
            "capital_mean": float(capital[n].mean()),
            **{f"{key}_mean": float(values[n].mean()) for key, values in side_values.items()},
            **{key: side_charts[key][n] for key in side_values},
            **(flows[n - 1] if n else {"income_mean": 0, "expense_mean": 0, "contribution_base_mean": 0}),
        }
        for n, month in enumerate(labels)
    ]
    return {
        "schema_version": "2.0",
        "currency": request.currency,
        "metrics": _metrics(
            base_events,
            portfolio,
            request.household.t0,
            len(months),
            [*household_events, *(e for g in groups.values() for e in g.events)],
        ),
        "charts": {"portfolio": _chart(labels, portfolio), "capital": _chart(labels, capital)},
        "goals": [
            {**goal, "group_id": g["group_id"], "currency": g["currency"]}
            for g in results
            for goal in g["result"]["goals"]
        ],
        "currency_groups": results,
        "actual": {"monthly_summaries": summaries, "event_funding": event_rows, "fx_transfers": fx_transfers},
        "household_ledger": asdict(_household_ledger(household_ledger, replaced_months)),
        "fx_charts": {currency: _chart(labels, values) for currency, values in quotes.items()},
        "provenance": {
            "engine": "multicurrency_joint_funding",
            "input_sha256": outer_hash,
            "seed": request.seed,
            "mc_number": request.mc_number,
            "history_sha256": common.history_sha256,
            "scenario_rows_sha256": _digest(common.row_indices.tolist()),
            "distribution": "synchronized_bootstrap",
            "match_moments": False,
            "data_source": "provided_joint_history",
            "stages": [],
            "funding_basis": "all_required_events_over_horizon",
            "balance_basis": "actual_scenario_states",
            "fx_quote_basis": "base_units_per_native_unit",
        },
    }


def multicurrency_result(request: MulticurrencyRequest) -> dict[str, Any]:
    """Return schema 2.0; reject overflow rather than persisting nonfinite financial results."""
    try:
        with np.errstate(over="raise", invalid="raise"):
            return _simulate(request)
    except FloatingPointError as error:
        raise ValueError("Actual multicurrency scenario states must remain finite") from error
