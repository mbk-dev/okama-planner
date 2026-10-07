# okama Planner

A standalone Python library for personal and family financial planning, powered by
`okama.FinPlan`. It turns a household budget, assets, fixed-payment loans and dated goals
into a monthly ledger and a two-stage Monte Carlo forecast. No client registry, database,
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

Implemented: a single investment portfolio with accumulation and withdrawal strategies,
annual indexation, fixed-payment debt, liquid buffers, pooled/separate fixed-rate savings,
reserve targets and non-working assets. Separate savings accounts are not separate
investment portfolios for goals.

Not implemented in this candidate: goal-specific investment portfolios, gamma/equivalent
alpha, FX conversion, jurisdictional taxes, transaction fees, white label reports,
Excel export or a web UI. Net budget/returns must already reflect any externally
modelled taxes and fees. Positive initial invested capital and two non-empty stages are
required by this implementation. Undated purchases are rejected; dated goals outside the
forecast horizon are excluded from its ledger and goal results. Loan proceeds are not
created automatically: any corresponding asset or receipt must be supplied explicitly.

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
