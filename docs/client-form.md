# Local browser form for human intake

The form lets a person enter client identity directly into a local SQLite database,
without sending names or contacts through an AI assistant. It is an optional standalone
command, not an MCP tool. The interface is available in every supported language (English, Russian, German, Spanish, Simplified Chinese); English is the default.

## Start and stop

Open an existing database:

```bash
poetry run python -m okama_planner.client_form --database /path/to/clients.sqlite3
poetry run python -m okama_planner.client_form --database /path/to/clients.sqlite3 --language ru
```

The interface language is chosen on the command line and defaults to English. Every supported
language (`en`, `ru`, `de`, `es`, `zh`) covers the whole local surface — the intake form, the
meeting journal and the legacy viewer — and dates follow the selected locale. Catalogue keys
live in `src/okama_planner/ui_texts.csv`; the browser bundle receives its captions from the
server and never carries its own translations.

Create a new empty database explicitly (its parent directory must exist):

```bash
poetry run python -m okama_planner.client_form --database /path/to/new.sqlite3 --initialize
```

Initialization refuses to overwrite an existing file. Without `--initialize`, a missing
file is an error. No sample clients are inserted. `--port 8765` selects a fixed port;
the default selects an unused port. The process prints a private capability URL.
Open that exact URL in your local browser. Stop the process with Ctrl+C and close the tab.
Restarting invalidates the old URL and all outstanding forms.

Keep the URL private: anyone able to access this machine's loopback interface and possessing
the URL can read and edit this database. Do not forward the port, reverse-proxy it, expose it
on a network, or register the command as an AI tool. This is a local human intake surface,
not a hosted multi-user application. A local process with database filesystem access remains
outside this boundary; see [AI privacy](ai-privacy.md).

## Client and financial input

Navigation lists stable client codes, never names. Choose **Создать клиента** to create a
record, or select a code to edit its complete identity record. The form includes all writable
registry fields. The database assigns the ID, code and creation timestamp. The interface displays only
the stable code.
Saving an edited form replaces its writable fields; empty optional inputs clear those values.

Enter one broker per line. An empty field with the known-information checkbox
unchecked means unknown; checking it with an empty field means no broker.
A populated field records the ordered broker list. Sex and the primary communication channel
have explicit choices. A primary channel requires its corresponding contact. Birth year,
Telegram ID and declaration delivery date use the existing registry validation.

The **Финансовые планы** link opens an advanced JSON editor for a `ForecastRequest` or
`MulticurrencyRequest`. It covers financial input including household members, income,
expenses, assets, liabilities, goals and forecast settings. Copy a complete request into the
editor; the offline synthetic inputs in `examples/` illustrate the schema. The same storage
validation used by the Python API runs before saving.

Saving always appends a financial version, with an optional version note. Version links load
previous requests for the selected code; the editor opens the latest version by default.
Saving a previous version also appends a new version. This editor does not calculate a
forecast, export a report or edit results. Client identity and plan saves are separate actions.
Annual tax residency is a related table rather than a registry field and remains available
through the storage API.

Errors are intentionally generic and do not echo validation inputs or database exceptions.
On a validation error, the form retains your entries and issues a fresh single-use nonce
so you can correct and resubmit them. Requests
larger than 1 MiB are rejected. A form can be submitted only once, including an unsuccessful
validation attempt (a replacement form is issued); refreshing the result after a successful save cannot duplicate a client
or version. Opening more than 256 forms invalidates the oldest outstanding forms.

## Read-only legacy LFP browser

Attach an existing LFP database explicitly while keeping the writable Planner database separate:

```bash
poetry run python -m okama_planner.client_form --database /path/to/planner.sqlite3 --legacy-database /path/to/lfp.sqlite3
```

No legacy path is assumed. Without this flag the legacy link and view are unavailable.
The startup check rejects missing files, directories, unsupported databases and Planner's own
schema as a legacy source. The legacy connection uses SQLite URI `mode=ro` and
`PRAGMA query_only=ON`; it does not initialize, migrate, copy or update the source.

**Просмотр базы LFP (только чтение)** opens a compact client table: code, full name as
stored, phone, primary communication channel, email, LFP date and IPS date. The legacy
registry stores a single `full_name`, so the name is not guessed or split into components.
The LFP date is the latest successful calculation timestamp across all input versions and
scenarios for that client, not a workbook delivery date; the IPS date is `ips_sent_at`.
Dates appear as DD.MM.YYYY; missing contacts or dates display a dash. The index contains
no financial details. Selecting a linked code opens the detailed view, and
**К списку клиентов** returns to the table.

The detailed view shows identity, contacts, original imported Markdown notes when present,
tax residency, financial input versions, family, assets,
liabilities, budget, goals, portfolios with holdings, scenarios and a stored run summary
with metrics. The latest input version and run are selected by default; navigation can select
an earlier version or run owned by that client and version. Missing optional tables display
an empty section. Monthly ledgers and raw input snapshots are not loaded. Values are escaped,
enums use the interface language, rates and expense-share goals show percentages. Imported notes
are displayed as escaped plain text for the selected registry entry; their source fingerprints
are not displayed, and their content is not exposed through AI APIs.

**Форма Planner** returns to the writable form's starting page. The two databases have
independent code namespaces: equal codes can identify different people. Navigation does not
transfer a client or migrate data. The legacy page contains no save form, and POST requests
to a view URL are rejected. The existing Host, Origin, capability path and response protections
apply to both views. Errors and logs never expose source paths, query values or raw database errors.

## Local boundary

The stdlib HTTP server binds only to `127.0.0.1`, requires the random capability path,
checks the exact Host and same-origin Origin, and validates CSRF plus a single-use form nonce.
It refuses cross-site browser requests and has no external assets or network data calls.
HTML values are escaped; responses disable caching, scripts and framing, and prevent referrer
leaks. Access logs and raw exception tracebacks are suppressed. The startup URL is printed
only so the human can open the form.

Tests use synthetic databases and real loopback HTTP requests. They cover intake, edit,
validation, escaping, access boundaries, repeat submissions, append-only plan versions and
client ownership of loaded versions.

## Unified Planner database (0.5.0)

Normal operation uses one Planner-owned file. CRM identifiers and the persistent
meeting journal are available from the client card; historical advisory records
are read from the same file. `--legacy-database` is a compatibility viewer for
archived files, not the normal working setup. Use the verified importer and
[one database guide](unified-database.md) before retiring an old working file.
