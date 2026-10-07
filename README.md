# okama Planner

A standalone Python library for personal and family financial planning, powered by
`okama.FinPlan` and explicit joint market scenarios. It turns a household budget, assets,
fixed-payment loans and dated goals into a monthly ledger and a forecast with pooled or
goal-specific investment portfolios. No client registry, database,
Excel template or MCP server is required.

Released under the [MIT license](LICENSE). This repository contains the independently usable
calculation library and synthetic examples, with a clean project history.

## Install and run the offline example

Use Python 3.11 and Poetry. From this directory:

```bash
poetry env use python3.11
poetry install
poetry run python examples/demo.py
poetry run pytest -q
```

The example writes two requests, two full results and the request JSON Schema to
`tmp/planner-demo/` under the working directory. Its inputs and monthly return samples
are entirely synthetic. It performs no market-data downloads. Ready-made results are in
`examples/baseline-result.json` and `examples/deferred-result.json`.

For numerical reproduction of those saved results, install the versions recorded in
`examples/versions.json`:

```bash
poetry add 'okama==3.0.0' 'pydantic==2.13.5' 'numpy==2.4.6' 'pandas==3.0.5' 'scipy==1.17.1'
poetry run python examples/demo.py
```

Python 3.11.15 was used for the saved example. Frozen histories, inputs, package versions,
Monte Carlo parameters and seed all matter; a seed alone does not freeze live data.
An exact cross-platform binary match is not asserted.

## Python API

```python
import json
from pathlib import Path
from okama_planner import ForecastRequest, forecast

request = json.loads(Path("examples/family.json").read_text())
validated = ForecastRequest.model_validate(request)
result = forecast(validated)  # a JSON-compatible dict; no persistence
schema = ForecastRequest.model_json_schema()
```

`forecast` also accepts the request dict directly. The full request includes `plan`,
explicit `currency`, `mc_number` (1–10,000), `seed`, `distribution` (`norm`, `lognorm`,
`t`), `match_moments` and optional `return_samples`. Each supplied stage sample is a
contiguous monthly total-return series with a `start_month` and at least 12 observations,
already in the plan currency. The history must end no later than the plan start and match
any declared last-date pin. Histories replace stage holdings; providing both is rejected.

Without `return_samples`, both stages require `*_holdings` (symbols and weights) and
`*_last_date_pin`; okama downloads their return histories. That live path requires network
access. Last dates constrain the sample end, but cannot freeze later revisions to historical
data. The release acceptance example and controls use supplied samples.

See [the API and calculation contract](docs/contract.md) for output semantics and assumptions.
There is no separate product CLI. The example script is a usage helper.

## Example and current scope

The example invests synthetic USD 75,000, saves household surplus for three years, buys
synthetic property in July 2028, then withdraws retirement spending from January 2029.
The second request changes only the purchase year to 2029. The same frozen histories and
seed are used. The purchase price is indexed, so postponement also changes its nominal cost.
Saved results include a positive portfolio median while total capital additionally includes
the acquired property. Sample probabilities are Monte Carlo estimates from 500 paths, not
claims about real investment returns or a guarantee that deferral improves a plan.

Implemented: a legacy single investment portfolio with accumulation and withdrawal
strategies, plus joint-bootstrap `single` and `per_goal` investment portfolios with actual
event funding. Annual indexation, fixed-payment debt, liquid buffers, pooled/separate
fixed-rate savings, reserve targets and non-working assets remain supported. Separate
fixed-rate savings accounts differ from goal-specific investment portfolios.

The richer offline family example compares home and pension portfolios against one pooled
portfolio on one shared scenario cube. Its empty household account, opening allocations,
dated strategies, surplus weights, payment order, transfers and completion rules are explicit:

```bash
poetry install --extras reports
poetry run python examples/portfolio_modes.py
```

It saves both requests/results, `comparison.json` and a neutral workbook under
`tmp/portfolio-modes/`. Ready-made synthetic snapshots are
`examples/family-single-request.json`, `examples/family-single-result.json`,
`examples/family-per-goal-request.json` and `examples/family-per-goal-result.json`.
The family, amounts and synchronized histories are fictional. See
[portfolio mode semantics](docs/portfolio-modes.md) and [report semantics](docs/reports.md).
Risk differs between the two modes, so their differences describe these explicit
strategies and policies, not an isolated benefit of account separation.

To replay two complete requests without changing the example:

```bash
poetry run python examples/portfolio_modes.py \
  --single-request path/to/single.json --per-goal-request path/to/per-goal.json \
  --output-dir path/to/results
```

Both requests must describe the same household, history, currency, seed and path count.
The helper writes snapshots only to the selected output directory and does not print their
contents. Keep personal requests/results outside the public repository.

FX conversion, jurisdictional taxes, transaction fees and a web UI are outside the current
model. Net budget/returns must already reflect any externally modelled taxes and fees.
The legacy FinPlan path requires positive initial invested capital and two non-empty stages;
joint funding supports empty segments. Undated purchases are rejected; dated goals outside
the forecast horizon are excluded from its ledger and goal results. Loan proceeds are not
created automatically: any corresponding asset or receipt must be supplied explicitly.

## Neutral Excel reports

An optional exporter produces an English financial-plan workbook with configurable
company, contacts, local logo and colors. Two fictional-brand examples, configuration
instructions, licensing and financial boundaries are described in [docs/reports.md](docs/reports.md).
Run `poetry install --extras reports` and `poetry run python examples/reports.py`.
Formatting preserves saved forecasts; it does not rerun calculations in Excel.

## Package boundary

`extraction-manifest.json` lists the exact reviewed public-file inventory.
The package imports neither the private `lfp`
application nor `okama-mcp`; there is no dependency cycle when the optional MCP adapter imports
this library. Private registries, database writers, templates, investment declarations,
client files, internal skills, tax reserve policies and repository history are excluded.

## MCP integration

An optional `planner_forecast` tool is available in the okama-mcp source main branch.
See [local installation, client configuration and two ready scenarios](https://github.com/mbk-dev/okama-mcp/blob/main/docs/planner.md).
Install this library into the same environment as that server. Existing published okama-mcp
package versions and the public HTTP server have not been updated for this integration.
The adapter delegates calculations to this library and preserves the existing finplan tools.
