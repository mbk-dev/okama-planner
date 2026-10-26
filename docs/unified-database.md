# One local client database

Planner owns the working SQLite file. The common identity tables include CRM identifiers,
contacts, tax residence, original intake notes and a meeting journal. Existing advisory
inputs, scenarios, cash-flow rows, metrics, percentiles and sweep results are retained in
their typed tables with original IDs and client codes. Native public request snapshots and
results use `planner_*` tables in the same file. There is one registry, not two databases.

Schema 0003 renames existing Planner planning tables before adding advisory history; it
preserves earlier Planner client records and native plans. Use `upgrade_database(path)`
explicitly on an older Planner file; normal opening never silently migrates it.

```python
from okama_planner.storage import PlannerStore, import_advisor_database

# First make verified private SQLite backup snapshots of source and destination.
# Initialize only a NEW destination, or upgrade an existing recognized Planner database.
with PlannerStore.initialize(destination):
    pass
receipt = import_advisor_database(source, destination)
assert receipt['status'] in {'imported', 'unchanged'}
```

The importer requires a recognized complete advisory schema, rejects unknown columns,
triggers/views and conflicting data, copies in one transaction and verifies every row
using per-table SHA256 and row counts. It preserves the registry's maximum allocated ID,
including IDs of removed records. Reports contain counts and digests, never client values.
Import does not delete the source. Retire it only after complete verification, switching
all readers/writers and encrypted backup to the canonical file, and proving no late writes.

Older advisory applications can continue reading/writing their typed tables in this same
file. They must not run their old Alembic chain on it: schema ownership belongs to Planner.
Historical results remain historical; import does not recalculate or reinterpret them as
native public-API results.

## Human meeting journal

Open `python -m okama_planner.client_form --database /private/path/clients.sqlite3`.
The client card links to the journal and planning history. Goal, date and meeting format
are required; time is optional. Notes have one Markdown source with visual editing,
preview and download. Save persists in SQLite; reload/restart retains it. A stale edit
is rejected instead of replacing another window's changes. Unsaved text is retained on
validation/network errors. All frontend assets are bundled locally; Node is only needed
to rebuild them (`npm ci && npm run build` in `ui/meeting-journal`).

The UI binds to loopback and requires the capability URL, Host/Origin and CSRF/nonce.
Never reverse-proxy it or publish a real client screenshot.

## Client access policy

`okama_planner.ai.PlannerClientAccess(database)` defaults to anonymous reads and refuses
all persistent client mutations. An explicit local `allow_personal_data=True` enables
personal client creation, update, deletion, meetings and bounded history reads. Deleting
a client removes only rows owned by that identity; cross-client references cause a
transaction rollback, not deletion of a different client's records.

An MCP adapter calls this API; it does not open SQLite, inspect schema or execute SQL.
The local startup flag is not a model tool parameter. Recreating the service without the
flag revokes personal access. Forecasts and report signatures keep their anonymous contract.

Only `storage/templates/empty.sqlite3` is tracked and distributed as a database. It contains
schema and migration metadata with zero business rows. Working files, sidecars, backups
and imported records are ignored by Git. Synthetic test fixtures contain schema only.
