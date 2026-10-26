"""Read known legacy LFP fields without importing LFP or mutating its database."""

import html
import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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
LABELS = dict(
    zip(
        "code full_name sex birth_year email phone telegram telegram_id whatsapp max_messenger brokers "
        "primary_channel ips_sent_at note created_at version year country name role label amount currency "
        "asset_class growth_rate principal annual_rate monthly_payment term_months start_month kind "
        "monthly_amount indexation_rate end_rule end_month amount_pv amount_basis pv_year target_year "
        "target_month priority becomes_asset can_defer can_resize replaces_asset reserve_label last_date_pin "
        "rebalancing_period abs_deviation rel_deviation symbol weight is_base status t0 horizon_years "
        "withdrawal_years retirement_year seed mc_number distribution match_moments buffer_lookahead_months "
        "savings_horizon_years inflation_rate expense_indexation_rate income_indexation_rate "
        "goal_indexation_rate "
        "discount_rate buffer_rate okama_version key value".split(),
        [
            "Код",
            "Полное имя",
            "Пол",
            "Год рождения",
            "Email",
            "Телефон",
            "Telegram",
            "Telegram ID",
            "WhatsApp",
            "MAX",
            "Брокеры",
            "Основной канал связи",
            "Дата отправки декларации",
            "Заметка",
            "Дата создания",
            "Версия",
            "Год",
            "Страна",
            "Имя",
            "Роль",
            "Название",
            "Сумма",
            "Валюта",
            "Класс актива",
            "Доходность",
            "Остаток долга",
            "Годовая ставка",
            "Ежемесячный платёж",
            "Срок, месяцев",
            "Начальный месяц",
            "Тип",
            "Сумма в месяц",
            "Индексация",
            "Правило окончания",
            "Конечный месяц",
            "Размер цели",
            "Основа размера цели",
            "Год текущих цен",
            "Целевой год",
            "Целевой месяц",
            "Приоритет",
            "Становится активом",
            "Можно отложить",
            "Можно уменьшить",
            "Заменяемый актив",
            "Название резерва",
            "Дата истории",
            "Ребалансировка",
            "Абсолютное отклонение",
            "Относительное отклонение",
            "Тикер",
            "Доля",
            "Базовый сценарий",
            "Статус",
            "Начало расчёта",
            "Горизонт, лет",
            "Период изъятий, лет",
            "Год пенсии",
            "Seed",
            "Число траекторий",
            "Распределение",
            "Сохранение моментов выборки",
            "Буфер, месяцев",
            "Горизонт накоплений, лет",
            "Инфляция",
            "Индексация расходов",
            "Индексация доходов",
            "Индексация целей",
            "Ставка дисконтирования",
            "Доходность буфера",
            "Версия okama",
            "Показатель",
            "Значение",
        ],
        strict=True,
    )
)
LABELS.update({"content": "Исходный текст", "imported_at": "Дата переноса"})
ENUMS = {
    "email": "Email",
    "phone": "Телефон",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "max": "MAX",
    "female": "Женский",
    "male": "Мужской",
    "client": "Клиент",
    "spouse": "Супруг(а)",
    "child": "Ребёнок",
    "portfolio": "Инвестиционный портфель",
    "reserve": "Резерв",
    "non_working": "Неработающий актив",
    "third_party": "Сторонний актив",
    "savings": "Накопления на покупки",
    "income": "Доход",
    "expense": "Расход",
    "none": "Без ограничения",
    "until_retirement": "До пенсии",
    "until_month": "До указанного месяца",
    "lump": "Разовая покупка",
    "retirement_income": "Пенсионный доход",
    "reserve_topup": "Пополнение резерва",
    "amount": "Денежная сумма",
    "expense_share": "Доля семейных расходов",
    "accumulation": "Накопление",
    "withdrawal": "Изъятия",
    "pending": "Ожидает расчёта",
    "ok": "Успешно",
    "failed": "Ошибка",
    "norm": "Нормальное",
    "lognorm": "Логнормальное",
    "t": "Стьюдента",
    "month": "Ежемесячно",
    "year": "Ежегодно",
    "probability_of_success": "Вероятность выполнения плана",
    "median_survival_years": "Медианный срок сохранения капитала, лет",
    **{f"terminal_p{p}": f"Конечный капитал: перцентиль {p}" for p in (10, 25, 50, 75, 90)},
}
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

    def __init__(self, path: Path, *, canonical: bool = False) -> None:
        self.canonical = canonical
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
                f"Состав портфеля: {row.get('label', '')}",
                self.rows(db, "portfolio_holding", "WHERE portfolio_id = ?", (row["id"],)),
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
        headers = ("Код", "Имя и фамилия", "Телефон", "Канал связи", "Email", "Дата ЛФП", "Дата IPS")
        parts = [
            "<section><h2>Клиенты</h2>",
            "<p>Дата ЛФП — последний успешный расчёт по всем версиям клиента; "
            "дата IPS — отправка инвестиционной декларации. "
            "Имя и фамилия показаны так, как записаны в реестре.</p>",
        ]
        if not registry:
            return "".join(parts) + "<p>Нет записей.</p></section>"
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
                display(key, row.get(key) or None, row)
                for key in ("full_name", "phone", "primary_channel", "email")
            ]
            values.extend((calendar_date(dates.get(row["id"])), calendar_date(row.get("ips_sent_at"))))
            parts.extend(f"<td>{html.escape(value)}</td>" for value in values)
            parts.append("</tr>")
        return "".join(parts) + "</tbody></table></div></section>"

    def canonical_navigation(self, parts: list[str], entry_path: str, code: str) -> None:
        if self.canonical:
            parts[1] = "<p>Сохранённые исходные данные и результаты находятся в единой базе Planner.</p>"
            parts[2] = (
                f'<nav><a href="{entry_path}">Клиенты Planner</a>'
                + (
                    f' <a href="{entry_path}?code={code}">Анкета</a>'
                    f' <a href="{entry_path}?view=meetings&amp;code={code}">Дневник встреч</a>'
                    if code
                    else ""
                )
                + "</nav>"
            )

    def page(self, entry_path: str, code: str, version: str, run: str) -> str:
        def link(caption: str, **query: Any) -> str:
            url = entry_path + "?" + urlencode({"view": "legacy", **query})
            return f'<a href="{html.escape(url, quote=True)}">{html.escape(caption)}</a>'

        parts = [
            "<h1>История финансовых планов</h1>"
            if self.canonical
            else "<h1>Существующая база ЛФП — только для чтения</h1>",
            "<p>Исходная база не изменяется. Анкеты и планы Planner сохраняются в отдельной базе. "
            "Коды в этих базах могут совпадать и относиться к разным людям. "
            "Переход между интерфейсами не переносит данные.</p>",
            f'<nav><a href="{entry_path}">Форма Planner</a></nav>',
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
            parts.append("<nav>" + link("К списку клиентов") + "</nav>")
            parts.append(table("Личные сведения и контакты", [identity]))
            parts.append(
                table(
                    "Исходные заметки",
                    self.rows(
                        db, "client_intake_note", "WHERE registry_id = ? ORDER BY id", (identity["id"],)
                    ),
                )
            )
            parts.append(
                table(
                    "Налоговое резидентство",
                    self.rows(db, "tax_residency", "WHERE registry_id = ? ORDER BY year", (identity["id"],)),
                )
            )
            versions = self.rows(db, "client", "WHERE registry_id = ? ORDER BY version", (identity["id"],))
            parts.append(
                "<h2>Версии исходных данных</h2><nav>"
                + " ".join(
                    link(f"Версия {row['version']}", code=code, version=row["version"]) for row in versions
                )
                + "</nav>"
            )
            chosen = choose(versions, "version", version)
            if chosen is None:
                if run:
                    raise ValueError("Unknown run")
                return "".join(parts) + "<p>Версии исходных данных отсутствуют.</p>"
            parts.append(table("Выбранная версия", [chosen]))
            for name, title in [
                ("person", "Семья"),
                ("asset", "Активы"),
                ("liability", "Обязательства"),
                ("budget_item", "Бюджет"),
                ("goal", "Цели"),
                ("portfolio", "Портфели"),
                ("scenario", "Сценарии"),
            ]:
                rows = self.rows(db, name, "WHERE client_id = ?", (chosen["id"],))
                parts.append(table(title, rows))
                parts.extend(self.holdings(db, rows) if name == "portfolio" else [])
            scenarios = self.rows(db, "scenario", "WHERE client_id = ?", (chosen["id"],))
            runs = []
            for scenario in scenarios:
                runs.extend(self.rows(db, "plan_run", "WHERE scenario_id = ?", (scenario["id"],)))
            runs.sort(key=lambda row: row["id"])
            parts.append(
                "<h2>Расчёты</h2><nav>"
                + " ".join(
                    link(f"Расчёт {row['id']}", code=code, version=chosen["version"], run=row["id"])
                    for row in runs
                )
                + "</nav>"
            )
            selected = choose(runs, "id", run)
            parts.append(table("Сводка расчёта", [] if selected is None else [selected]))
            if selected:
                parts.append(
                    table(
                        "Показатели расчёта",
                        self.rows(db, "run_metric", "WHERE plan_run_id = ?", (selected["id"],)),
                    )
                )
        return "".join(parts)


def calendar_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        return date.fromisoformat(str(value)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return "—"


def choose(rows: list[dict[str, Any]], key: str, selection: str) -> dict[str, Any] | None:
    if not selection:
        return rows[-1] if rows else None
    selected = next((row for row in rows if str(row[key]) == selection), None)
    if selected is None:
        raise ValueError("Unknown selection")
    return selected


def display(key: str, value: Any, row: dict[str, Any]) -> str:
    if value is None:
        return "—"
    if key in BOOLS:
        return "Да" if value else "Нет"
    if key == "brokers":
        try:
            return ", ".join(json.loads(value))
        except (ValueError, TypeError):
            return str(value)
    if isinstance(value, (float, int)):
        if (
            key.endswith("_rate")
            or key in {"weight", "abs_deviation", "rel_deviation"}
            or (
                key == "value"
                and (
                    row.get("key") == "probability_of_success"
                    or str(row.get("key", "")).endswith(("_mean_return", "_risk"))
                )
            )
            or (key == "amount_pv" and row.get("amount_basis") == "expense_share")
        ):
            return f"{value * 100:,.2f} %".replace(",", " ")
        return f"{value:,.2f}".replace(",", " ") if isinstance(value, float) else str(value)
    if key == "key" and str(value).endswith(("_mean_return", "_risk")):
        stage, metric = str(value).rsplit("_", 1)
        if metric == "return":
            stage = stage.removesuffix("_mean")
        caption = "Средняя доходность" if metric == "return" else "Риск"
        return f"{caption}: {ENUMS.get(stage, stage)}"
    return ENUMS.get(str(value), str(value)) if key in ENUM_FIELDS else str(value)


def table(title: str, rows: list[dict[str, Any]]) -> str:
    parts = [f"<section><h2>{html.escape(title)}</h2>"]
    if not rows:
        return "".join(parts) + "<p>Нет записей.</p></section>"
    keys = [key for key in rows[0] if key not in INTERNAL]
    parts.append(
        '<div class="table-scroll"><table><thead><tr>'
        + "".join(f'<th scope="col">{html.escape(LABELS[key])}</th>' for key in keys)
        + "</tr></thead><tbody>"
    )
    for row in rows:
        parts.append(
            "<tr>"
            + "".join(f"<td>{html.escape(display(key, row.get(key), row))}</td>" for key in keys)
            + "</tr>"
        )
    return "".join(parts) + "</tbody></table></div></section>"
