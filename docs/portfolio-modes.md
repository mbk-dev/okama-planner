# Portfolio modes and actual funding

`forecast()` retains the existing single-portfolio okama FinPlan engine when
`joint_history` and `allocation` are absent. Its request serialization, result
schema `1.0`, and input hash remain unchanged, including when
`portfolio_mode="single"` is explicitly supplied.

With `joint_history`, both `single` and `per_goal` use the joint funding engine
(result schema `1.1`). `single` pools all opening portfolio capital and uses the
explicit `AllocationSpec.single_strategy`. `per_goal` invests each goal's own
segment and the household segment with their own dated strategies. Both follow
the same event priority, actual side-account rules and monthly requirements.
The pooled mode makes all portfolio capital available to every event; the
per-goal mode follows the declared transfer policy. This distinction is reported
in comparisons. Comparing the legacy parametric FinPlan engine with a bootstrap
engine is not an isolated comparison of portfolio modes.

## Python interface

```python
from okama_planner import (
    AllocationSpec, ForecastRequest, JointHistory, compare_portfolio_modes,
    forecast, with_portfolio_mode,
)

# request is a dict or ForecastRequest containing the complete joint contract.
per_goal = ForecastRequest.model_validate(request)
single = with_portfolio_mode(per_goal, portfolio_mode="single")
result = forecast(per_goal)
comparison = compare_portfolio_modes(single, per_goal)
```

Exact signatures:

```python
forecast(request: ForecastRequest | dict[str, Any]) -> dict[str, Any]
with_portfolio_mode(
    request: ForecastRequest | dict[str, Any], *,
    portfolio_mode: Literal["single", "per_goal"],
    allocation: AllocationSpec | dict[str, Any] | None = None,
) -> ForecastRequest
compare_portfolio_modes(
    single: ForecastRequest | dict[str, Any],
    per_goal: ForecastRequest | dict[str, Any],
) -> dict[str, Any]
```

The helper returns a detached, fully validated request. It never mutates the
source or fills in an advisor's missing allocation policy. The optional
`allocation` replaces the whole policy and must validate against the existing
household and history. A legacy request cannot be switched to `per_goal` without
first supplying joint history and allocation.

Comparison requires identical `plan`, currency, seed, path count and joint
history; baseline must be `single` and variant must be `per_goal`. Allocation
changes are allowed but disclosed in `policy.changed_fields`. The sampler runs
once and the same asset cube feeds both engines. `baseline` and `variant` contain
full forecast results, `differences` are variant minus baseline, and
`risk_structure` discloses the single strategy and segment schedules. History and
sampled-row hashes identify the common market input. No full path cube is
serialized in public results.

## Required allocation contract

All allocation fields below are required, including empty tuples that express
no transfers or no goals. All models forbid unknown fields and are frozen;
allocation collections are tuples of frozen records rather than mutable maps.
Opening amounts and weights must be finite and nonnegative. Booleans are not
amounts or weights. Portfolio weights and surplus weights must sum to one within
`1e-12` absolute tolerance; they are never normalized. Unknown keys, including
keys carrying zero weight, are errors. Segment opening amounts must equal the
plan's opening portfolio assets within `1e-9` absolute tolerance.

| Model | Fields |
| --- | --- |
| `PortfolioWeight` | `asset`, `weight` |
| `StrategyStep` | `start_month`, `weights: tuple[PortfolioWeight, ...]` |
| `SegmentShare` | `segment_id`, `weight` |
| `SurplusStep` | `start_month`, `weights: tuple[SegmentShare, ...]` |
| `CompletionPolicy` | `action: retain \| transfer_to`, optional `destination` |
| `SegmentSpec` | `segment_id`, `goal_id`, `opening_amount`, `currency`, `strategy`, `completion` |
| `GoalFunder` | `goal_id`, `segment_id` |
| `AllocationSpec` | `segments`, `single_strategy`, `surplus_weights`, `household_segment_id`, `goal_funders`, `event_priority`, `funding_source_order`, `reserve_funding_source_order`, `transfer_policy`, `transfer_order`, `buffer_policy`, `purchase_execution` |

The household segment has `goal_id=null` and retains its capital. Every other
segment owns exactly one goal; every goal has a stable non-null integer ID and
exactly one own funder. Segments cannot share a goal. All dates are `YYYY-MM`.
Each schedule begins at `t0`, ascends strictly and remains within the effective
horizon. Its latest step governs the current month. Strategies rebalance to
those weights every month; risk reductions are explicit new dated steps.

`event_priority` lists `expense`, `mortgage_payment`, and `goal:<id>` for every
goal exactly once, even when a category has no events. It determines the order
of debits within each month; the order of budget items or liabilities resolves
same-category ties. All monthly incomes first enter cash once. General
`funding_source_order` orders `cash`, `buffer`, `segment` exactly once.
`reserve_funding_source_order` is a separate nonempty ordered subset of those
sources: a reserve target need not be funded by a purchase buffer. Reserve
balances are not a source for other spending in this implementation.

With `transfer_policy="none"`, `transfer_order=[]` and only the own segment can
fund a debit. Both `ordered` and `unrestricted` permit other segments as donors:
the own segment is tried first, then all other segment IDs in the explicit
`transfer_order`; the order must contain every segment once. There are no
per-donor transfer caps. `unrestricted` documents the full-pool equivalence
policy. Each transfer reduces the donor and is immediately spent by the funder;
it creates no extra household capital.

`completion.action="retain"` keeps the residual in its own strategy and keeps
future surplus allocations there. `transfer_to` requires an existing destination,
transfers residual capital once after full completion, and redirects future
surplus. Cyclic completion graphs are rejected; already completed destinations
are followed until a retaining or active segment is reached. An unfunded lump
goal does not complete. A pension completes after its last required stream event has been funded,
provided every earlier stream event was funded. An expense-share stream may
end before the calendar horizon if its underlying expenses end earlier.

`buffer_policy="retain"` holds existing savings in the buffer until spent and
invests surplus in the declared segments. `planned_targets` instead uses the
legacy planned net requirements over `buffer_lookahead_months` as a target,
deposits only available unspent cash, and releases excess cash for investment.
It does not guarantee funding of that target. If `reserves_until_retirement` is
true, the buffer releases to available cash from retirement onward. Buffer and
reserve growth follow the existing side-account convention: no growth in the
first flow month, then their monthly rate factors. Portfolio return, in contrast,
applies to the opening portfolio before the first month's flows.

## Fully synthetic JSON request

This complete example includes household expenses, salary, a property purchase,
and a pension stream, with separate risk and surplus schedules. Figures are
synthetic USD amounts. The history ends before `t0`. A purchase that fails to
receive its full price creates no acquired asset.

```json
{
  "currency": "USD", "mc_number": 20, "seed": 7,
  "portfolio_mode": "per_goal",
  "plan": {
    "t0": "2026-01", "horizon_years": 3, "retirement_year": 2028,
    "buffer_lookahead_months": 3,
    "rates": {
      "inflation_rate": 0, "expense_indexation_rate": 0,
      "income_indexation_rate": 0, "goal_indexation_rate": 0,
      "discount_rate": 0, "buffer_rate": 0
    },
    "assets": [
      {"label": "Invested", "amount": 600, "currency": "USD", "asset_class": "portfolio"},
      {"label": "Buffer", "amount": 50, "currency": "USD", "asset_class": "savings"},
      {"label": "Reserve", "amount": 100, "currency": "USD", "asset_class": "reserve", "growth_rate": 0}
    ],
    "budget_items": [
      {"kind": "income", "label": "Salary", "monthly_amount": 30, "end_rule": "until_retirement"},
      {"kind": "expense", "label": "Living", "monthly_amount": 10, "end_rule": "until_retirement"}
    ],
    "goals": [
      {"goal_id": 1, "label": "Purchase", "kind": "lump", "amount_pv": 100,
       "pv_year": 2026, "target_year": 2027, "becomes_asset": true},
      {"goal_id": 2, "label": "Pension", "kind": "retirement_income", "amount_pv": 20, "pv_year": 2026}
    ]
  },
  "joint_history": {
    "start_month": "2020-01", "currency": "USD", "method": "synchronized_bootstrap",
    "asset_returns": {
      "stock": [0.01, -0.02, 0.03, 0, 0.02, -0.01, 0.01, -0.02, 0.03, 0, 0.02, -0.01],
      "bond": [0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002, 0.002]
    }
  },
  "allocation": {
    "segments": [
      {"segment_id": "household", "goal_id": null, "opening_amount": 100, "currency": "USD",
       "strategy": [{"start_month": "2026-01", "weights": [{"asset": "bond", "weight": 1}]}],
       "completion": {"action": "retain"}},
      {"segment_id": "purchase", "goal_id": 1, "opening_amount": 100, "currency": "USD",
       "strategy": [
         {"start_month": "2026-01", "weights": [{"asset": "stock", "weight": 0.5}, {"asset": "bond", "weight": 0.5}]},
         {"start_month": "2026-07", "weights": [{"asset": "bond", "weight": 1}]}
       ], "completion": {"action": "transfer_to", "destination": "pension"}},
      {"segment_id": "pension", "goal_id": 2, "opening_amount": 400, "currency": "USD",
       "strategy": [{"start_month": "2026-01", "weights": [{"asset": "stock", "weight": 0.7}, {"asset": "bond", "weight": 0.3}]}],
       "completion": {"action": "retain"}}
    ],
    "single_strategy": [{"start_month": "2026-01", "weights": [{"asset": "stock", "weight": 0.5}, {"asset": "bond", "weight": 0.5}]}],
    "surplus_weights": [{"start_month": "2026-01", "weights": [
      {"segment_id": "household", "weight": 0.2}, {"segment_id": "purchase", "weight": 0.2},
      {"segment_id": "pension", "weight": 0.6}
    ]}],
    "household_segment_id": "household",
    "goal_funders": [{"goal_id": 1, "segment_id": "purchase"}, {"goal_id": 2, "segment_id": "pension"}],
    "event_priority": ["expense", "mortgage_payment", "goal:1", "goal:2"],
    "funding_source_order": ["cash", "buffer", "segment"],
    "reserve_funding_source_order": ["cash", "segment"],
    "transfer_policy": "ordered", "transfer_order": ["household", "purchase", "pension"],
    "buffer_policy": "planned_targets", "purchase_execution": "all_or_nothing"
  }
}
```

## Actual assets, funded events and shortfalls

Income enters cash once. `portfolio_flow` and `buffer_in/out` from the legacy
ledger are bookkeeping checks and are not additional income or expenses.
Reserve goals are target levels, not repeated contributions: actual top-ups
cover only the gap to the target and add only the funded amount to reserve.

Lump purchases are all-or-nothing. A replacement asset's sale is conditional on
funding the entire replacement price including sale proceeds. Failed purchases
leave the old property owned, pay zero, and add no new asset. Successful
purchases remove the old property, count sale proceeds once, and add acquired
property only when `becomes_asset` is true. Other spending and mortgage payments
can be partially funded; unmet requirements are recorded explicitly.

Existing loans started at or before `t0` enter with their outstanding balance.
Payments before `t0` are taken from their contractual amortization history.
During the simulated horizon, interest accrues on actual outstanding debt and
only funded payments reduce it. Missed payments are not forgiven at the planned
payoff month; they remain due through the horizon. There is no penalty/default
model. Future-start loans are rejected in joint mode because the inputs have no
explicit disbursement contract; legacy handling is unchanged.

For each path and month:

```text
net capital = sum(segment balances) + actual buffer + actual reserve
              + actual non-working assets - actual outstanding debt
```

Portfolio wealth stays nonnegative. Later external income can rebuild it after
depletion. This actual funding rule differs from legacy FinPlan's reported
absorbing zero balance. Identical strategies with unrestricted transfers give
the same pooled and per-goal family paths, including depletion and later income.
Family quantiles are computed after aggregation within each path; summing
segment medians or capital-side quantiles is not a family quantile.

`metrics.probability_of_success` means all required events were fully funded
over the horizon. `goals.p_funded` measures actual full funding, and retirement
`p_full_stream` covers every modeled pension month. `p_affordable` is a
report-compatible alias of this actual full funding probability in schema `1.1`;
`p_alive` remains a diagnostic portfolio-balance probability before the first
goal event. `median_survival_years` is the median time to first funding shortfall
(or the horizon if none), rather than the legacy market-survival statistic.
`unmet_mean` reports nominal unmet amounts summed over the relevant events; it
is not their present value.

`actual.monthly_summaries` includes opening and month-end portfolio, capital,
buffer, reserve, non-working and liability states. Side accounts have means
and percentile series; capital percentiles use whole scenario states.
`actual.event_funding` reports required/funded/unmet means, funding probability,
and amounts consumed from each source. `actual.transfers` reports actual
shortfall and completion transfers. Segment charts and strategies preserve the
risk structure. The regular `ledger` and `portfolio_flow` remain the planned
requirements for report compatibility and are marked
`ledger_basis="planned_requirements_not_actual_balances"`; their scheduled side
balances must not be presented as actual funded assets. Provenance identifies
`engine="joint_funding"`, `balance_basis="actual_scenario_states"` and the
full-horizon event funding basis.

## Unsupported combinations and size

Each joint `ForecastRequest` requires one currency for its accounts, segments and provided
history. Combine native requests under [MulticurrencyRequest](multicurrency.md) for a common
household budget and explicit FX conversion. Histories must end strictly before `t0` and
contain at least 12 aligned monthly observations for each asset. Explicit legacy
`distribution`/`match_moments` options, legacy stage samples or holdings,
nonmonthly/corridor rebalancing, separate purchase-savings accounts and automatic
`savings_horizon_years` assignment are rejected. Joint request serialization
omits legacy market knobs so validated requests round-trip unambiguously.

Internal sampling scales with months × paths × assets; internal actual balances
scale with months × paths × segments. Public outputs contain monthly summaries
and event aggregates, not every trajectory. Nonfinite actual balances caused by
numeric overflow raise a clear `ValueError` rather than exporting invalid money.
The engine does not calculate taxes, fees, portfolio borrowing, or utility.
