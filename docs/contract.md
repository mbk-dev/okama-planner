# Legacy forecast contract, schema version 1.0

This page describes the unchanged legacy FinPlan path. Requests with explicit joint history
and allocation return schema 1.1 in either portfolio mode; see
[the goal-portfolio contract](portfolio-modes.md) for actual funding and comparison semantics.

The entry point is `okama_planner.forecast(ForecastRequest | dict) -> dict`.
The request schema is available from `ForecastRequest.model_json_schema()` and as
`examples/request-schema.json`. Models reject unknown fields. Errors are Python
`ValueError`/Pydantic validation errors; adapters should translate them at their own boundary.
The library does not read or write client files or a database.

## Inputs and timing

All amounts use one explicit currency. Monthly budget amounts are positive; `kind` determines
their sign. Annual rates are decimal fractions. Assets are classified as `portfolio`,
`savings`, `reserve`, `non_working` or `third_party`; the last class is excluded from the
modelled household capital. Retirement begins in the month of `t0` in `retirement_year`.
Indexation occurs on anniversaries of `t0`, not every calendar January. Purchase amounts
are stated in `pv_year` and indexed by whole years to their `target_year`; their optional
`target_month` selects the month within that year. Without it, the month of `t0` is used.

`retirement_income` is a spending stream, not an income receipt. With
`pension_replaces_expenses=true`, it replaces post-retirement household expenses. Otherwise
it is additional spending. Its `amount_basis=expense_share` uses a fraction of the replaced
expenses and requires that replacement rule. A `lump` purchase draws cash; `becomes_asset`
creates a non-working asset as well. `replaces_asset` sells an existing named non-working
asset in the purchase month. A `reserve_topup` is a target balance, not an extra contribution:
only the missing amount is moved into the reserve. Concurrent targets share the same reserve.

Loans amortise from `start_month` with nominal fixed payments and annual_rate / 12 interest.
`term_months` is descriptive: payments continue to actual payoff instead of silently dropping
unpaid debt at term. Payments that do not reduce debt are rejected. Future loans contribute
no debt before their first month; past loans enter with their remaining balance.

## Results

- `schema_version`, `currency`, `portfolio_mode='single'` identify the output contract.
- `ledger` contains ordered monthly household lines, portfolio transfers and deterministic
  buffer, reserve, property and loan balances. Do not sum all line kinds: `portfolio_flow`
  restates household flows after savings allocation; buffer movements use the buffer's sign.
- `portfolio_flow` is a month-to-nominal-amount mapping: positive invests, negative withdraws.
- `metrics` includes `probability_of_success`, `median_survival_years` and terminal portfolio
  percentiles p10, p25, p50, p75, p90. Success means the investment plan survives its whole
  horizon, rather than that every non-investment asset is liquidated to meet spending.
- `goals` contains `goal_id`, `label`, `month`, `amount_nominal`, `p_affordable` and `p_alive`.
  Both probabilities use portfolio wealth in the month before the goal. Lump affordability
  measures the portfolio share after savings/budget funding; reserve affordability measures
  the missing top-up. Fully prefunded goals have p_affordable=1 even if the portfolio is dead.
  A pension row measures its first monthly withdrawal; it does not certify the whole pension
  stream. `p_alive` measures positive portfolio wealth before that date. It is not the goal's
  probability and is distinct from full-plan success.
- `charts.portfolio` contains monthly nominal wealth percentiles, including the opening month
  immediately before `t0`. Depleted paths are floored at zero.
- `charts.capital` adds deterministic savings, reserve and non-working asset balances and
  subtracts outstanding loans from each matching portfolio percentile. This is net capital,
  not the amount available for investment withdrawals. Acquired property is not automatically
  liquidated after the portfolio depletes.
- `provenance` records canonical input SHA256, seed, path count, distribution, moment matching,
  okama/numpy/pandas/scipy versions, data source, each stage's history boundaries and SHA256,
  and annualised sample mean/risk. Those sample statistics do not identify the unconstrained
  fitted mean/risk when `match_moments=false`.

Cash flows are already nominally indexed in the ledger. `TimeSeriesStrategy` receives them
with `time_series_discounted_values=True` to avoid applying okama's indexation again.
`DatedFinPlan` keeps forecast dates anchored to `t0` independently of historical sample dates.
`HistoryPortfolio` is a narrow offline adapter for FinPlan, not a general asset-data provider.
Normal draws can fall below -100%; this path follows okama's model and does not impose
a different tail law. Matched Student t uses fitted tail shape with the sample centre/spread;
unconstrained fits can change expected return. Distribution choice is an explicit assumption.

## Adapter handoff

A thin MCP adapter can validate the complete request, call `forecast` once and return this dict.
For legacy comparisons, make independent calls with copied requests; the library has no mutable
scenario/session storage. Example baseline/deferred requests and results fix the purchase-date
comparison without adding an MCP implementation here. Market-backed stages may share okama
portfolio cache entries within a process; offline calculation has no market downloads.
