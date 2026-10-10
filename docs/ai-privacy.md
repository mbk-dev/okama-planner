# Personal data at the AI boundary

Use `okama_planner.ai` for AI-facing operations. The trusted local `PlannerStore` and
native report API remain available to the human advisory application. MCP calls the
restricted API and never receives a raw registry record or an internal database row ID.

## What an AI receives

A client has a stable registry code, such as `c-0001`. The AI-facing record replaces
its name with `c-0001-name`, email with `c-0001-email`, and recorded phone, messenger,
broker and note fields with corresponding codes. Missing fields remain null. Sex,
birth year and relevant dates remain available; this is pseudonymization, not a
claim that demographic and financial data cannot identify someone indirectly.

Plan names, person roles, asset/goal/budget captions and arbitrary portfolio/currency
group identifiers become `anon-000001` style codes. References between these fields
are replaced together, including asset replacements, savings-rate keys, joint-history
assets, contribution weights and portfolio transfers. Names never become hashes that
could be checked against a dictionary. Financial numbers, dates, currencies and public
market symbols remain calculation inputs only after membership in the public okama
namespace catalog is confirmed; unconfirmed strings are rejected without querying
a candidate symbol. Reading a market-holdings plan therefore needs catalog access. Unexpected free text in technical fields
is rejected. Repeated masking of a coded request preserves its codes; codes within a
plan belong to that request layout, rather than a global person registry.

`PlannerAI(database)` exposes:

- `client_get(code)` and `client_list()`: coded records;
- `client_update(code, changes)`: only sex, birth year and the IPS date;
- `client_get_tax_residency(code, year)` / `client_set_tax_residency(code, year, country)`:
  explicit country/year; private notes remain inside Planner;
- `client_save_plan(code, request)`: append an anonymous financial version;
- `client_load_plan(code, version)` and `client_list_plans(code)`: anonymous inputs or
  code/version references, never source notes, table names or internal row IDs;
- `client_forecast(code, version)`: calculate an anonymous forecast of that version.

Planner performs validation, identity lookup, database transactions and writes. MCP
has no raw SQL, registry-store access or AI argument for a database path. It cannot
create clients or change their actual names and contact details through its tools.

## Local human intake

Keep identity JSON in the human-controlled client folder outside the repository and
outside any AI-accessible directories. Do not paste its contents into a chat or tool
arguments. The file follows the trusted `ClientDetails` schema; it is not an MCP schema.

Run this command yourself in the updated Planner checkout:

```bash
poetry run python -m okama_planner.private_clients create \
  --database /private/planner.sqlite3 --input /private/client-details.json
```

The command prints only the assigned `c-NNNN` code. Share that code with the AI.
For a local identity patch, use `update` with `--code c-0001`; for a trusted financial
request file, use `save-plan` with `--code c-0001`. All three operations write through
Planner. Identity patches and native plan snapshots remain local. `create` creates a
new client each time; repeat an existing client's operation with `update`, not `create`.
The command opens an existing database and does not silently create a missing one.

## Forecasts, comparisons and artifacts

`ai.forecast(request)` and `ai.compare_portfolio_modes(baseline, variant)` run only on
masked requests. Their forecast results include an opaque `privacy_proof`, signed
with a process-local key. `ai.export_report` accepts only unchanged signed results and
checks the native request hash before creating a workbook. It ignores scenario display
names and local company/contact/logo settings, producing a neutral anonymous report.
Use the trusted human export API separately for a named client deliverable.

Modified or unsigned arbitrary result JSON is rejected. After restarting the process,
obtain a new forecast before exporting it. The signature is not authentication for a
client or a substitute for filesystem permissions. MCP exports return an opaque
artifact basename; the human chooses the report directory at server startup, and its
absolute path never appears in the tool result.

All AI-facing Planner failures return a generic error without input values, local paths,
SQL or database schema. MCP also sanitizes pre-body argument validation and masks error
logging for its Planner/client/report tools in every language, including English.
An older Planner installation without the restricted API fails closed, instead of
falling back to the previous raw registry tools. These changes require updated source
checkouts until the companion packages are released.

## Scope of the protection

This boundary protects the documented Planner/MCP interfaces. A separate AI with shell,
Python or file access under the database owner's OS account can bypass an API and read
its files. To prevent that access, run the human Planner and AI tools under separately
permissioned accounts/processes and do not grant the AI access to the database or intake
files. This update does not provision that OS isolation. Data already entered into a
chat has already reached that AI and cannot be made private by masking a later response.

The regression tests use only fictional identities and temporary databases. They cover
registry success and failure, old stored plans, safe writes, cross-client version ownership,
financial equivalence, code collisions, signed Excel export, unsigned/tampered artifacts,
local human intake and actual MCP argument/runtime error paths.
