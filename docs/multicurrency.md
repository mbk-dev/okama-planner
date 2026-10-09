# Multi-currency financial plans

A `MulticurrencyRequest` keeps one household budget in the base currency and a group of goals and accounts in each native currency. Each group contains a complete joint-history `ForecastRequest`, with either `single` or `per_goal` portfolio mode. For example, a RUB household can fund a USD property goal and two EUR education portfolios alongside a RUB retirement portfolio.

```python
from okama_planner import MulticurrencyRequest, forecast
from okama_planner.charts import export_charts
from okama_planner.reports import export_report

request = MulticurrencyRequest.model_validate(payload)
result = forecast(request)
export_charts(result, "tmp/plan")  # HTML by default: overall and one file per group
export_report([
    {"label": "Family", "request": request.model_dump(mode="json"), "result": result}
], "tmp/plan/plan.xlsx")
```

Run the fully fictional, offline example:

```bash
MPLBACKEND=Agg poetry run python examples/multicurrency.py
# Add --images to also export linear/logarithmic PNG and SVG and embed PNG in Excel.
```

The example rates, asset histories, FX histories and amounts are synthetic. It demonstrates accounting and scenario correlation; it is not a model portfolio or a set of market assumptions.

## Request fields

| Field | Meaning |
| --- | --- |
| `currency` | Base currency of the common household budget and overall totals. |
| `household` | `PlanInputs` with persons, income, expenses, calendar and rates. Assets, liabilities and goals belong to native groups. |
| `groups` | Unique `group_id` and native `request` per currency. Native requests require `joint_history` and `allocation`; group budgets are empty. |
| `fx.opening_rates` | Explicit positive base units per native currency unit, including base quote 1. Example: RUB base, USD quote 100 means 1 USD = 100 RUB. |
| `fx.start_month`, `fx.monthly_returns` | Monthly quote returns, aligned with every group's asset history. The base currency has no FX return series. |
| `contribution_schedule` | Dated weights for all groups, summing to 1. The first entry starts at the plan's first month. |
| `household_funding_order` | Every group exactly once: order for covering a common household deficit or a loan shortfall. |
| `conversion_fee_rate` | Proportional fee on foreign conversion. Same-currency transfers incur no fee. |
| `seed`, `mc_number` | One sampling seed and scenario count for the whole plan. |

Dates, horizon and retirement year must match between the household and groups. Goal IDs are unique across the entire plan. A group can hold several portfolio segments in one currency; multiple groups with the same currency are rejected.

## Scenario and funding rules

All asset and FX columns share the same bootstrap row indices. Supply genuinely aligned histories to preserve their observed dependence. Opening quotes anchor scenario quotes; their future returns come from the same historical months as the asset returns. The engine uses native asset returns, without multiplying FX into them a second time.

Each simulated month applies investment growth and the current exchange quote, then pays the common household expenses and native loan payments. The remaining household cash is split by the current contribution weights and converted into each group's currency. Contributions then follow that group's own allocation and event rules. A native goal draws only on accounts within its currency group; it cannot automatically raid another currency's goals. Household expenses and loan shortfalls can use other groups according to the explicit household funding order.

Conversion traces retain per-path source/destination amounts, quotes and fees, plus their means. Conversion is internal: it does not create income or reduce capital beyond its fee. For foreign contributions, destination amount is `base_amount × (1 − fee) / quote`; for withdrawals, net base proceeds are `native_amount × quote × (1 − fee)`.

An `expense_share` retirement goal converts the indexed common household expense requirement into its native currency at the current scenario quote. The household flag `pension_replaces_expenses` controls whether these retirement withdrawals replace ordinary family expenses. Its zero nominal ledger skeleton is explicitly labelled; use actual funding events for the scenario-dependent amounts. Segment completion uses the final actual expense-share month. A planned buffer converts known future household requirements at the current quote for each path, without looking ahead at future simulated quotes.

## Results and exports

Result schema `2.0` contains overall `charts` and `metrics`, goals with `group_id` and `currency`, native schema `1.1` results under `currency_groups`, common actual funding events and `actual.fx_transfers`. Native portfolio and capital remain in native units. Overall capital first adds the converted balances **within each path**, then computes percentiles. It never adds independently computed percentiles. Overall success requires all common and native requirements to be funded on the same path.

HTML exports are responsive and have a logarithmic scale switch, numbered goal markers and PNG/SVG download buttons. The output directory contains `forecast.html` for the overall base-currency view and `group_id/forecast.html` for native groups. Static export supports `format="png"` or `"svg"`, and `logarithmic=True`; choose separate output directories to keep both scales.

Excel has one common Budget/Cash Flow and a horizontal Cash Flow sheet per native currency, currency-labelled goals/current amounts/strategies, and FX transfer traces. `chart_images` accepts the usual overall keys (`portfolio`, `capital`, `portfolio_log`, `capital_log`) and native keys such as `dollar/portfolio`. Native captions use the group's currency. Supported report languages remain English (default), Russian, Chinese, German and Spanish.

`PlannerStore.save_plan`, `save_scenario`, `save_result` and load methods preserve the full multi-currency request and result. Household budget rows are stored once; native components and portfolios carry their currency-group owner. Existing single-currency snapshots and result schemas remain readable.
