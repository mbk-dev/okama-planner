# Presentation languages

Planner supports `en` (default), `ru`, `de`, `es` and `zh` (Simplified Chinese).
Language changes presentation only. A USD plan remains a USD plan in every language.
Never infer currency, tax rules, pension rules or asset exposure from a language code.

## Contract

Pass `language=` to `export_report` and `export_charts`. Both validate the language before
creating output. The raw forecast API and database remain language-neutral. Saved JSON keys,
SQL columns, IDs, ISO currency/country codes and technical enum values stay stable. Client
names, goal labels, group IDs, scenario labels and other authored text are never translated.

`okama_planner.localization` provides `translate`, `terminology`, `locale_code`,
`format_number`, `format_date`, `client_presentation`, `localized_validation_errors` and
`localized_error`. Registry presentation is a separate list of `{key, label, value}` records;
it does not alter the input record or database. Field labels and contact/sex display values
are translated; countries retain their ISO codes. Dates use the selected locale.
Validation presentation contains stable field locations and error types with translated
messages, without input values, exception objects or links. Unknown diagnostics produce a
localized general failure; technical details belong in private diagnostics, not client reports.
Expected export failures retain their exception class; Pydantic validation failures become
plain localized `ValueError` messages in non-English exports. English errors preserve the
existing contract and structured validation exceptions.

Locale mapping: en → en-US, ru → ru-RU, de → de-DE, es → es-ES, zh → zh-CN.
Numbers use grouping and decimal conventions of that locale. Dates display month/day/year
for en, day.month.year for ru/de, day/month/year for es, and year/month/day labels for zh.
HTML uses browser Intl to display abbreviated months and native currency placement; the
underlying ISO months and numerical chart arrays remain identical. PNG/SVG use the same
HTML renderer, including language, log-scale warnings and goal numbering.

Excel keeps numeric values, percentages as fractions and formulas; localized sheets are
referenced by token-aware formula rewriting. Number formats carry the selected Excel locale
ID. Excel/LibreOffice may apply the viewer's configured decimal/group separators; these are
viewer settings, not a change in plan values. Goal dates are localized. Source ledger dates
and technical snapshots remain ISO so year-based SUMIFS and provenance remain reproducible.

## Translation catalog and completeness

`src/okama_planner/terminology.csv` is the packaged source of captions with columns
`key,en,ru,zh,de,es`. `validate_terminology` rejects empty translations, duplicate keys or
English captions, and differing substitution fields. Add template captions explicitly;
never scan and translate arbitrary user values. `{unit}` is substituted from the request,
not from language or a default national currency.

Run `poetry run pytest tests/test_presentation_localization.py tests/test_reports.py
 tests/test_charts.py tests/test_multicurrency_reports.py -q` on one line to check coverage,
user-label preservation, localized references and matching forecast data.

## Coverage matrix

| Existing surface | en | ru | de | es | zh | Evidence / boundary |
|---|---|---|---|---|---|---|
| Single / per-goal white-label Excel | Yes | Yes | Yes | Yes | Yes | `test_reports.py`; source snapshots remain technical |
| Currency-group Excel and FX headers | Yes | Yes | Yes | Yes | Yes | `test_presentation_localization.py`, `test_multicurrency_reports.py` |
| HTML captions, accessible labels, actions, log warnings | Yes | Yes | Yes | Yes | Yes | Shared CSV; `test_charts.py` |
| HTML amounts, axis numbers and month annotations | Yes | Yes | Yes | Yes | Yes | Explicit Intl locale; identical saved numerical arrays |
| PNG / SVG exports | Yes | Yes | Yes | Yes | Yes | Same renderer as HTML; Chrome/Chromium required |
| Registry fields, enum display, dates | Yes | Yes | Yes | Yes | Yes | `client_presentation`; raw registry stays unchanged |
| Validation and expected export failures | Yes | Yes | Yes | Yes | Yes | `localized_validation_errors`, export boundaries |
| Short user guide and offline example | Yes | Yes | Yes | Yes | Yes | `docs/user-guide/`, `examples/localized_plan.py` |
| Local MCP client tools / Planner messages and descriptions | Yes | Yes | Yes | Yes | Yes | Companion implementation in okama-mcp, RS-717 |
| Future web interface | — | — | — | — | — | RS-713; no web interface is created here |
| Other financial market-data MCP tools | — | — | — | — | — | Outside this Planner localization task |

## MCP companion

okama-mcp implements this language contract for Planner and explicitly enabled local registry
and report tools. `--language` selects tool descriptions at startup; explicit call language
selects response presentation and expected error messages. The default English calls preserve
existing machine response shapes. Non-English registry calls expose localized presentation
beside raw records. This is application presentation, not automatic translation of user input.
See the companion `docs/planner-localization.md` for exact commands and response shapes.
Local registry/report tools remain unavailable over HTTP. The packaged `create-client` skill
and general engineering documents retain their original technical language; short user guides
are provided in all five supported languages instead of duplicating implementation instructions.

## Reproduce one plan in five languages

```bash
poetry run python examples/localized_plan.py --output-dir tmp/localized-example
poetry run python examples/localized_plan.py --output-dir tmp/localized-images --image-format svg
```

The sample performs one offline synthetic forecast, saves its request/result, and exports
five workbooks and linear/log HTML views. Optional images require Chrome/Chromium. It never
uses a client registry or live market data. Follow the guide for your language:
[English](user-guide/en.md), [Русский](user-guide/ru.md), [Deutsch](user-guide/de.md),
[Español](user-guide/es.md), [简体中文](user-guide/zh.md).
