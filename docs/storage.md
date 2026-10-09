# Local client database

`okama_planner.storage` stores professional client records and planning history in
local SQLite files. It uses SQLAlchemy 2 and packaged Alembic migrations. The
forecast API remains stateless and does not open or create a database.

## Create and open a database

Choose a location outside your source checkout. Create the parent directory yourself:

```python
from pathlib import Path
from okama_planner.storage import PlannerStore

path = Path.home() / "planner-data" / "clients.sqlite3"
path.parent.mkdir(parents=True, exist_ok=True)
with PlannerStore.initialize(path) as store:
    assert store.list_clients() == []

with PlannerStore.open(path) as store:
    clients = store.list_clients()
```

`initialize` creates an empty database and refuses to overwrite an existing file.
On POSIX the new file is accessible only to its owner (mode 0600). `open` requires
an existing file, the current schema revision and a matching schema. It does not
silently create a new file or upgrade an old database. Context-manager exit closes
the engine; `close()` can also be called explicitly.

Database files and their SQLite sidecars are ignored by Git. The only shipped
SQLite file is `okama_planner/storage/templates/empty.sqlite3`: it contains schema
and migration metadata, **zero clients, plans, scenarios and results**. It is
included in both wheel and sdist. The fictional clients in README are documentation
only; no seed script inserts them. To generate another empty template:

```python
from okama_planner.storage import create_template
create_template(path)  # path must not exist
```

## Registry API

`create_client(details)` returns a dictionary with all 16 fields documented in
[README](../README.md#client-records). Only `full_name` is required. `id`, stable
`code` (such as `c-0001`) and UTC `created_at` are assigned by storage. Same-name
clients are allowed. `get_client(code)` and `list_clients()` return complete records.
`update_client(code, changes)` applies a partial patch:

- Missing fields stay unchanged; explicit `None` clears an optional field.
- `id`, `code` and `created_at` cannot be changed through the API.
- `primary_channel` must point to a populated `email`, `phone`, `telegram`,
  `whatsapp` or `max_messenger` contact. Its machine values are `email`, `phone`,
  `telegram`, `whatsapp`, `max`. Validate the complete patched record, not just
  the fields submitted: clearing the current primary contact requires changing
  or clearing `primary_channel` in the same patch.
- `brokers=None` means unknown; `[]` means explicitly no broker. Order is preserved.
- `telegram_id` is an integer, not a handle or string; `ips_sent_at` is a date,
  not a document-generation request. Date inputs accept Python dates or ISO dates;
  returned dates and timestamps are ISO strings, timestamps in UTC.
- Unknown fields and invalid records raise `ValueError` (including Pydantic's
  `ValidationError`). Unknown client codes raise `LookupError`.

`set_tax_residency(code, year, country, note=None)` records or updates one calendar
year; country must be an assigned ISO 3166-1 alpha-2 code (normalized to uppercase).
`get_tax_residency(code, year)` returns the row or `None`: earlier years are never
inherited. Recording residence does not implement country-specific taxation.

## Financial versions and calculation history

| Table | Stored data and relationship |
|---|---|
| `client_registry` | Stable identity, all 16 registry fields |
| `tax_residency` | Residence by registry ID and year, unique per pair |
| `client` | `id`, `registry_id`, `version`, `source_digest`, `note`, `created_at`; version numbers unique per client |
| `plan_snapshot` | Full `ForecastRequest` JSON, one per financial version |
| `person`, `asset`, `liability`, `budget_item`, `goal` | Public input components in original order; `id`, `client_id`, `position`, `payload` |
| `portfolio` | Ordered public legacy stage or joint allocation strategies, with the same component columns |
| `scenario` | `id`, `client_id`, `label`, full request JSON, `created_at` |
| `plan_run` | `id`, `scenario_id`, full request/result JSON, `source_digest`, `created_at` |

The financial version ID returned by `save_plan` is `client.id`, not the stable
registry ID or the per-client version number. Request goal identifiers keep their
original meaning and are not replaced with ORM row IDs. Component payloads follow
public Planner models; private lfp tables and unsupported settings are not imported.
Full snapshots include currency, model assumptions, Monte Carlo settings, frozen
samples, joint history and goal allocations. Replay loads the complete request,
not a reconstruction from partial component tables.

```python
import json
from pathlib import Path
from okama_planner import forecast
from okama_planner.storage import PlannerStore

request = json.loads(Path("examples/readme-request.json").read_text())
with PlannerStore.open(path) as store:
    # User input should come from the advisor's private application/form.
    client = store.create_client({"full_name": advisor_supplied_name})
    version_id = store.save_plan(client["code"], request, note="Initial plan")
    scenario_id = store.save_scenario(version_id, "Baseline", request)
    loaded = store.load_scenario(scenario_id)
    result = forecast(loaded)
    run_id = store.save_result(scenario_id, result)
    saved_result = store.load_result(run_id)
```

`save_plan(code, request, note=None)` appends a version and all components in one
transaction. `load_plan(version_id)` returns a `ForecastRequest`;
`list_plans(code)` returns version metadata in version order.
`save_scenario(version_id, label, request)` saves a full alternative request linked
to that financial version; `load_scenario(id)` returns it as a `ForecastRequest`.
A scenario may change financial assumptions or inputs; it is an explicit full
alternative, not a private lfp goal-adjustment delta.

`save_result(scenario_id, result)` appends a run only if
`result.provenance.input_sha256` equals the SHA-256 of the stored request's
canonical JSON (sorted keys, compact separators, no NaN/Infinity), the same
contract used by `forecast`. A mismatched result raises `ValueError`.
The hash ties a result to its inputs; it does not independently recalculate or
certify the submitted result. `load_result(run_id)` returns detached JSON data.
JSON arrays are returned as lists, including fields that the in-memory forecast
represents as tuples. All values survive; modifying a loaded dictionary does not
alter the stored record. Missing version/scenario/run IDs raise `LookupError`.

Earlier financial versions, scenarios and runs have no update/delete API. Updating
registry contacts does not overwrite historical inputs. Concurrent writers serialize
before assigning stable codes or version numbers; failed writes roll back the entire
operation. Direct SQL writes are outside this API's immutability/validation contract.

## Schema upgrades

```python
from okama_planner.storage import upgrade_database
upgrade_database(path)
```

Close other users of the file before upgrading. Only recognized older revisions
are upgraded; missing, unversioned or newer/unknown schemas are refused. Repeating
an upgrade is idempotent. The migration chain starts with registry/tax residence
(`0001`), then adds financial history (`0002`), preserving registry records.
Downgrades are intentionally unsupported. Existing files are never overwritten.

Migration transactions use SQLAlchemy's explicit SQLite BEGIN handling;
[SQLAlchemy documents SQLite transaction and foreign-key behavior](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).
Programmatic migrations share the store's connection following the
[Alembic connection-sharing recipe](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).

## MCP and localization contract

Storage is a Python API. **Registry access through okama-mcp is not implemented**
by this change. Future MCP adapters call these methods, own a private database path,
translate validation errors for their user and never duplicate schema or calculations.
The client selector is stable `code`; returned financial version, scenario and run
IDs must be retained separately. The adapter must select an explicitly authorized
client/version before reading or writing their records.

SQL names, JSON keys and enum values stay unchanged across languages. User-facing
labels use the shared terminology system; names, notes, broker names and scenario
labels remain user input and are not automatically translated. The storage API
returns data rather than a translated client form; registry UI localization is
tracked separately.
