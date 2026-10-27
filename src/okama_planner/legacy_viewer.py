"""Read known legacy LFP fields without importing LFP or mutating its database."""

import html
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from okama_planner.localization import format_date
from okama_planner.ui_texts import DEFAULT_LANGUAGE, UiText

# Explicit field allowlists keep snapshots and the monthly ledger out of the browser.
FIELDS = {
    "client_registry": "id code full_name sex birth_year email phone telegram telegram_id whatsapp "
    "max_messenger brokers primary_channel ips_sent_at note created_at",
    "client": "id registry_id version note created_at",
    "client_intake_note": "content imported_at",
    "tax_residency": "year country note",
    "person": "name birth_year role",
    "asset": "label amount currency asset_class growth_rate note",
    "liability": "label principal annual_rate monthly_payment term_months start_month note",
    "budget_item": "kind label monthly_amount indexation_rate start_month end_rule end_month",
    "goal": "label kind amount_pv amount_basis pv_year target_year target_month priority becomes_asset "
    "can_defer can_resize indexation_rate replaces_asset reserve_label note",
    "portfolio": "id label role currency last_date_pin rebalancing_period abs_deviation rel_deviation",
    "portfolio_holding": "symbol weight",
    "scenario": "id label is_base note created_at",
    "plan_run": "id scenario_id created_at status t0 horizon_years withdrawal_years retirement_year "
    "seed mc_number distribution match_moments buffer_lookahead_months savings_horizon_years "
    "inflation_rate expense_indexation_rate income_indexation_rate goal_indexation_rate "
    "discount_rate buffer_rate okama_version",
    "run_metric": "key value",
}
FIELD_KEYS = {
    column: ("field.metric" if column == "key" else f"field.{column}")
    for column in "code full_name sex birth_year email phone telegram telegram_id whatsapp max_messenger "
    "brokers primary_channel ips_sent_at note created_at version year country name role label amount "
    "currency asset_class growth_rate principal annual_rate monthly_payment term_months start_month kind "
    "monthly_amount indexation_rate end_rule end_month amount_pv amount_basis pv_year target_year "
    "target_month priority becomes_asset can_defer can_resize replaces_asset reserve_label last_date_pin "
    "rebalancing_period abs_deviation rel_deviation symbol weight is_base status t0 horizon_years "
    "withdrawal_years retirement_year seed mc_number distribution match_moments buffer_lookahead_months "
    "savings_horizon_years inflation_rate expense_indexation_rate income_indexation_rate "
    "goal_indexation_rate discount_rate buffer_rate okama_version value content imported_at".split()
}
ENUM_KEYS = {
    value: ("enum.yearly" if value == "year" else f"enum.{value}")
    for value in "email phone telegram whatsapp max female male client spouse child portfolio reserve "
    "non_working third_party savings income expense none until_retirement until_month lump "
    "retirement_income reserve_topup amount accumulation withdrawal pending ok failed norm lognorm "
    "t month year".split()
}
ENUM_KEYS["expense_share"] = "enum.share"
METRICS = {"probability_of_success": "legacy.metric_probability",
           "median_survival_years": "legacy.metric_survival"}
UNKNOWN_LABEL = "field.metric"
INTERNAL = {"id", "registry_id", "scenario_id"}
ENUM_FIELDS = {
    "sex",
    "role",
    "asset_class",
    "kind",
    "end_rule",
    "amount_basis",
    "rebalancing_period",
    "status",
    "distribution",
    "primary_channel",
    "key",
}
BOOLS = {"is_base", "becomes_asset", "can_defer", "can_resize", "match_moments"}


class LegacyReader:
    """Connections are short lived, read-only and never passed to Planner storage."""

    def __init__(self, path: Path, *, canonical: bool = False, language: str = DEFAULT_LANGUAGE) -> None:
        self.canonical = canonical
        self.ui = UiText(language)
        self.path = path.resolve(strict=True)
        if not self.path.is_file():
            raise ValueError("Legacy database unavailable")
        with closing(self.connect()) as db:
            if self.columns(db, "plan_snapshot") or (
                not canonical and self.columns(db, "planner_plan_snapshot")
            ):
                raise ValueError("Planner is not a legacy database")
            for table, required in {
                "client_registry": {"id", "code", "full_name"},
                "client": {"id", "registry_id", "version"},
            }.items():
                if not required <= self.columns(db, table):
                    raise ValueError("Unsupported legacy database")

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        try:
            db.execute("PRAGMA query_only=ON")
            db.row_factory = sqlite3.Row
            return db
        except Exception:
            db.close()
            raise

    @staticmethod
    def columns(db: sqlite3.Connection, table: str) -> set[str]:
        # Table names come only from the module's fixed allowlist.
        return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}

    def rows(
        self, db: sqlite3.Connection, table: str, where: str = "", values: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        columns = self.columns(db, table)
        selected = [key for key in FIELDS[table].split() if key in columns]
        if not selected:
            return []
        keys = ", ".join(f'"{key}"' for key in selected)
        return [dict(row) for row in db.execute(f'SELECT {keys} FROM "{table}" {where}', values)]

    def holdings(self, db: sqlite3.Connection, portfolios: list[dict[str, Any]]) -> list[str]:
        return [
            table(
                self.ui.text("legacy.holdings", label=row.get("label", "")),
                self.rows(db, "portfolio_holding", "WHERE portfolio_id = ?", (row["id"],)),
                self.ui,
            )
            for row in portfolios
        ]

    def client_index(self, db: sqlite3.Connection, registry: list[dict[str, Any]], entry_path: str) -> str:
        dates = {}
        required = {"scenario": {"id", "client_id"}, "plan_run": {"scenario_id", "status", "created_at"}}
        if all(keys <= self.columns(db, name) for name, keys in required.items()):
            dates = dict(
                db.execute(
                    "SELECT c.registry_id, MAX(r.created_at) FROM client c "
                    "JOIN scenario s ON s.client_id = c.id "
                    "JOIN plan_run r ON r.scenario_id = s.id "
                    "WHERE r.status = 'ok' GROUP BY c.registry_id"
                )
            )
        ui = self.ui
        headers = tuple(
            ui.text(key)
            for key in ("legacy.code", "field.full_name", "field.phone", "legacy.channel",
                        "field.email", "legacy.lfp_date", "legacy.ips_date")
        )
        parts = [
            f"<section><h2>{ui.text('legacy.clients_heading')}</h2>",
            f"<p>{ui.text('legacy.clients_explainer')}</p>",
        ]
        if not registry:
            return "".join(parts) + f"<p>{ui.text('legacy.no_records')}</p></section>"
        parts.append(
            '<div class="table-scroll"><table><thead><tr>'
            + "".join(f'<th scope="col">{caption}</th>' for caption in headers)
            + "</tr></thead><tbody>"
        )
        for row in registry:
            url = entry_path + "?" + urlencode({"view": "legacy", "code": row["code"]})
            parts.append(
                '<tr><td><a href="'
                + html.escape(url, quote=True)
                + '">'
                + html.escape(row["code"])
                + "</a></td>"
            )
            values = [
                display(key, row.get(key) or None, row, ui)
                for key in ("full_name", "phone", "primary_channel", "email")
            ]
            values.extend(
                (calendar_date(dates.get(row["id"]), ui), calendar_date(row.get("ips_sent_at"), ui))
            )
            parts.extend(f"<td>{html.escape(value)}</td>" for value in values)
            parts.append("</tr>")
        return "".join(parts) + "</tbody></table></div></section>"

    def canonical_navigation(self, parts: list[str], entry_path: str, code: str) -> None:
        if self.canonical:
            ui = self.ui
            parts[1] = f"<p>{ui.text('legacy.intro_canonical')}</p>"
            parts[2] = (
                f'<nav><a href="{entry_path}">{ui.text("legacy.planner_clients")}</a>'
                + (
                    f' <a href="{entry_path}?code={code}">{ui.text("ui_profile")}</a>'
                    f' <a href="{entry_path}?view=meetings&amp;code={code}">'
                    f'{ui.text("ui_meeting_journal")}</a>'
                    if code
                    else ""
                )
                + "</nav>"
            )

    def page(self, entry_path: str, code: str, version: str, run: str) -> str:
        def link(caption: str, **query: Any) -> str:
            url = entry_path + "?" + urlencode({"view": "legacy", **query})
            return f'<a href="{html.escape(url, quote=True)}">{html.escape(caption)}</a>'

        ui = self.ui
        parts = [
            f'<h1>{ui.text("legacy.history") if self.canonical else ui.text("legacy.readonly")}</h1>',
            f"<p>{ui.text('legacy.intro')}</p>",
            f'<nav><a href="{entry_path}">{ui.text("legacy.planner_form")}</a></nav>',
        ]
        self.canonical_navigation(parts, entry_path, code)
        with closing(self.connect()) as db:
            registry = self.rows(db, "client_registry", "ORDER BY code")
            if not code:
                if version or run:
                    raise ValueError("Client required")
                return "".join(parts) + self.client_index(db, registry, entry_path)
            identity = next((row for row in registry if row["code"] == code), None)
            if identity is None:
                raise ValueError("Unknown client")
            parts.append("<nav>" + link(ui.text("legacy.back")) + "</nav>")
            parts.append(table(ui.text("legacy.personal"), [identity], ui))
            parts.append(
                table(
                    ui.text("legacy.source_notes"),
                    self.rows(
                        db, "client_intake_note", "WHERE registry_id = ? ORDER BY id", (identity["id"],)
                    ),
                    ui,
                )
            )
            parts.append(
                table(
                    ui.text("legacy.tax_residence"),
                    self.rows(db, "tax_residency", "WHERE registry_id = ? ORDER BY year", (identity["id"],)),
                    ui,
                )
            )
            versions = self.rows(db, "client", "WHERE registry_id = ? ORDER BY version", (identity["id"],))
            parts.append(
                f'<h2>{ui.text("legacy.source_versions")}</h2><nav>'
                + " ".join(
                    link(ui.text("ui_version", version=row["version"]), code=code, version=row["version"])
                    for row in versions
                )
                + "</nav>"
            )
            chosen = choose(versions, "version", version)
            if chosen is None:
                if run:
                    raise ValueError("Unknown run")
                return "".join(parts) + f"<p>{ui.text('legacy.no_versions')}</p>"
            parts.append(table(ui.text("legacy.selected_version"), [chosen], ui))
            for name, title in [
                ("person", "legacy.family"),
                ("asset", "legacy.assets"),
                ("liability", "legacy.liabilities"),
                ("budget_item", "ui_budget"),
                ("goal", "ui_goals"),
                ("portfolio", "legacy.portfolios"),
                ("scenario", "legacy.scenarios"),
            ]:
                rows = self.rows(db, name, "WHERE client_id = ?", (chosen["id"],))
                parts.append(table(ui.text(title), rows, ui))
                parts.extend(self.holdings(db, rows) if name == "portfolio" else [])
            scenarios = self.rows(db, "scenario", "WHERE client_id = ?", (chosen["id"],))
            runs = []
            for scenario in scenarios:
                runs.extend(self.rows(db, "plan_run", "WHERE scenario_id = ?", (scenario["id"],)))
            runs.sort(key=lambda row: row["id"])
            parts.append(
                f'<h2>{ui.text("legacy.calculations")}</h2><nav>'
                + " ".join(
                    link(ui.text("legacy.run", run=row["id"]), code=code, version=chosen["version"],
                         run=row["id"])
                    for row in runs
                )
                + "</nav>"
            )
            selected = choose(runs, "id", run)
            parts.append(table(ui.text("legacy.run_summary"), [] if selected is None else [selected], ui))
            if selected:
                parts.append(
                    table(
                        ui.text("legacy.run_metrics"),
                        self.rows(db, "run_metric", "WHERE plan_run_id = ?", (selected["id"],)),
                        ui,
                    )
                )
        return "".join(parts)


def calendar_date(value: Any, ui: UiText) -> str:
    if not value:
        return "—"
    try:
        return format_date(str(value)[:10], ui.language)
    except ValueError:
        return "—"


def choose(rows: list[dict[str, Any]], key: str, selection: str) -> dict[str, Any] | None:
    if not selection:
        return rows[-1] if rows else None
    selected = next((row for row in rows if str(row[key]) == selection), None)
    if selected is None:
        raise ValueError("Unknown selection")
    return selected


def is_percent(key: str, row: dict[str, Any]) -> bool:
    metric = str(row.get("key", ""))
    return (
        key.endswith("_rate")
        or key in {"weight", "abs_deviation", "rel_deviation"}
        or (key == "value" and (metric == "probability_of_success"
                               or metric.endswith(("_mean_return", "_risk"))))
        or (key == "amount_pv" and row.get("amount_basis") == "expense_share")
    )


def metric_caption(value: Any, ui: UiText) -> str | None:
    metric = str(value)
    if metric in METRICS:
        return ui.text(METRICS[metric])
    if metric.startswith("terminal_p") and metric[10:].isdigit():
        return ui.text("legacy.metric_terminal", p=metric[10:])
    if metric.endswith(("_mean_return", "_risk")):
        stage, kind = metric.rsplit("_", 1)
        if kind == "return":
            stage = stage.removesuffix("_mean")
        return ui.text(
            "legacy.metric_average_return" if kind == "return" else "legacy.metric_risk",
            stage=ui.text(ENUM_KEYS.get(stage, UNKNOWN_LABEL)),
        )
    return None


def display(key: str, value: Any, row: dict[str, Any], ui: UiText) -> str:
    if value is None:
        return "—"
    if key in BOOLS:
        return ui.text("legacy.yes") if value else ui.text("legacy.no")
    if key == "brokers":
        try:
            return ", ".join(json.loads(value))
        except (ValueError, TypeError):
            return str(value)
    if isinstance(value, (float, int)):
        if is_percent(key, row):
            return f"{value * 100:,.2f} %".replace(",", " ")
        return f"{value:,.2f}".replace(",", " ") if isinstance(value, float) else str(value)
    if key == "key":
        caption = metric_caption(value, ui)
        if caption is not None:
            return caption
    if key in ENUM_FIELDS and str(value) in ENUM_KEYS:
        return ui.text(ENUM_KEYS[str(value)])
    return str(value)


def table(title: str, rows: list[dict[str, Any]], ui: UiText) -> str:
    parts = [f"<section><h2>{html.escape(title)}</h2>"]
    if not rows:
        return "".join(parts) + f"<p>{ui.text('legacy.no_records')}</p></section>"
    keys = [key for key in rows[0] if key not in INTERNAL]
    parts.append(
        '<div class="table-scroll"><table><thead><tr>'
        + "".join(f'<th scope="col">{html.escape(ui.text(FIELD_KEYS.get(key, UNKNOWN_LABEL)))}</th>'
                  for key in keys)
        + "</tr></thead><tbody>"
    )
    for row in rows:
        parts.append(
            "<tr>"
            + "".join(f"<td>{html.escape(display(key, row.get(key), row, ui))}</td>" for key in keys)
            + "</tr>"
        )
    return "".join(parts) + "</tbody></table></div></section>"
