"""Human-only browser intake, served exclusively on the IPv4 loopback interface.

Never expose this module through AI tools or a public/reverse-proxied server.
"""

import argparse
import html
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from okama_planner.legacy_viewer import LegacyReader
from okama_planner.storage import PlannerStore
from okama_planner.storage.validation import ClientDetails

LABELS = {
    'full_name': 'Полное имя', 'sex': 'Пол', 'birth_year': 'Год рождения',
    'email': 'Email', 'phone': 'Телефон', 'telegram': 'Telegram', 'telegram_id': 'Telegram ID',
    'whatsapp': 'WhatsApp', 'max_messenger': 'MAX', 'brokers': 'Брокеры (по одному на строку)',
    'primary_channel': 'Основной канал связи', 'ips_sent_at': 'Дата отправки декларации', 'note': 'Заметка',
}
OPTIONS = {
    'sex': [('', 'Не указан'), ('female', 'Женский'), ('male', 'Мужской')],
    'primary_channel': [('', 'Не указан'), ('email', 'Email'), ('phone', 'Телефон'),
                        ('telegram', 'Telegram'), ('whatsapp', 'WhatsApp'), ('max', 'MAX')],
}
STYLE = """
body{font:16px system-ui,sans-serif;color:#172b42;background:#f3f6fa;margin:0}
main{max-width:960px;margin:32px auto;padding:28px;background:white;border-radius:16px}
h1{font-size:28px}h2{font-size:22px}nav{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}
a{color:#185eaa}fieldset{border:1px solid #dae2ec;border-radius:10px;margin:20px 0;padding:20px}
legend{font-weight:600} .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
label{display:block}input,select,textarea{box-sizing:border-box;width:100%;padding:10px;margin-top:6px;
font:inherit;border:1px solid #97a9bd;border-radius:6px}textarea{resize:vertical}
input[type=checkbox]{width:auto}button{background:#185eaa;color:white;border:0;border-radius:8px;
padding:12px 24px;font:inherit;cursor:pointer}.notice{background:#e7f5ec;padding:14px;border-radius:8px}
.error{background:#fff0ec;padding:14px;border-radius:8px}small{color:#425b74}
.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%}
th,td{padding:10px;border-bottom:1px solid #dae2ec;text-align:left;vertical-align:top}
td{white-space:pre-wrap;overflow-wrap:anywhere}section{margin:28px 0}
@media(max-width:650px){main{margin:0;padding:20px;border-radius:0}.grid{grid-template-columns:1fr}}
"""
MAX_BODY = 1_048_576


def escaped(value: Any) -> str:
    return html.escape(str(value), quote=True)


def single_values(parsed: dict[str, list[str]]) -> dict[str, str]:
    if any(len(value) != 1 for value in parsed.values()):
        raise ValueError('Repeated field')
    return {key: value[0] for key, value in parsed.items()}


class FormServer(HTTPServer):
    """A synchronous server keeps nonce consumption and mutations serialized."""

    def __init__(self, database: Path, port: int, legacy: LegacyReader | None = None) -> None:
        self.database = database
        self.legacy = legacy
        self.entry_path = f'/{secrets.token_urlsafe(32)}/'
        self.style_nonce = secrets.token_urlsafe(24)
        self.csrf = secrets.token_urlsafe(32)
        self.nonces: dict[str, tuple[str, str]] = {}
        super().__init__(('127.0.0.1', port), FormHandler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Do not emit tracebacks containing request or database values."""


class FormHandler(BaseHTTPRequestHandler):
    server: FormServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress capability URLs and private submitted values in access logs."""

    def reply(self, status: int, body: str = '', location: str | None = None) -> None:
        encoded = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy',
                         f"default-src 'none'; style-src 'nonce-{self.server.style_nonce}'; "
                         "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        if location is not None:
            self.send_header('Location', location)
        self.end_headers()
        self.wfile.write(encoded)
        self.close_connection = True

    def allowed(self, post: bool = False) -> bool:
        host = f'127.0.0.1:{self.server.server_port}'
        origin = self.headers.get('Origin')
        return (
            self.headers.get_all('Host') == [host]
            and urlsplit(self.path).path == self.server.entry_path
            and (origin == f'http://{host}' if post else origin in (None, f'http://{host}'))
            and self.headers.get('Sec-Fetch-Site') in (None, 'none', 'same-origin')
        )

    def form(self, operation: str, code: str) -> str:
        # Bound abandoned forms; opening more than 256 forms invalidates the oldest one.
        if len(self.server.nonces) >= 256:
            del self.server.nonces[next(iter(self.server.nonces))]
        nonce = secrets.token_urlsafe(32)
        self.server.nonces[nonce] = operation, code
        hidden = {'csrf': self.server.csrf, 'nonce': nonce, 'operation': operation, 'code': code}
        return f'<form method="post" action="{self.server.entry_path}">' + ''.join(
            f'<input type="hidden" name="{key}" value="{escaped(value)}">'
            for key, value in hidden.items()
        )

    def identity_fields(self, row: dict[str, Any]) -> str:
        parts = []
        for title, keys in (
            ('Личные сведения', ('full_name', 'sex', 'birth_year', 'ips_sent_at')),
            ('Контакты', ('email', 'phone', 'telegram', 'telegram_id', 'whatsapp',
                          'max_messenger', 'primary_channel')),
            ('Брокеры и заметки', ('brokers', 'note')),
        ):
            parts.append(f'<fieldset><legend>{title}</legend><div class="grid">')
            for key in keys:
                value = row.get(key) or ''
                parts.append(f'<label>{LABELS[key]}')
                if key in OPTIONS:
                    parts.append(f'<select name="{key}">')
                    for option, caption in OPTIONS[key]:
                        selected = ' selected' if value == option else ''
                        parts.append(f'<option value="{option}"{selected}>{caption}</option>')
                    parts.append('</select>')
                elif key in ('brokers', 'note'):
                    if key == 'brokers' and isinstance(value, list):
                        value = '\n'.join(value)
                    parts.append(f'<textarea name="{key}" rows="3">{escaped(value)}</textarea>')
                    if key == 'brokers':
                        known = row.get('brokers_known', row.get('brokers') is not None)
                        checked = ' checked' if known else ''
                        parts.append('<small>Пустой список при отмеченном флажке '
                                     'означает, что брокеров нет.</small>'
                                     f'<br><input type="checkbox" name="brokers_known" value="yes"{checked}>'
                                     ' Сведения о брокерах известны')
                else:
                    kind = 'date' if key == 'ips_sent_at' else 'text'
                    required = ' required' if key == 'full_name' else ''
                    parts.append(f'<input type="{kind}" name="{key}" value="{escaped(value)}"{required}>')
                parts.append('</label>')
            parts.append('</div></fieldset>')
        return ''.join(parts)

    def plan_fields(self, store: PlannerStore, code: str, version: str,
                    submitted: dict[str, str] | None) -> str:
        if not code:
            raise ValueError('Client required')
        plans = store.list_plans(code)
        chosen = plans[-1] if plans and not version else next(
            (item for item in plans if str(item['version']) == version), None)
        if version and chosen is None:
            raise ValueError('Unknown version')
        parts = ['<p>Расширенный редактор JSON: доходы, расходы, активы, обязательства, цели '
                 'и настройки прогноза. Сохранение создаёт новую версию; расчёт не запускается.</p>']
        for item in plans:
            query = urlencode({'code': code, 'view': 'plan', 'version': item['version']})
            parts.append(f'<p><a href="{self.server.entry_path}?{escaped(query)}">'
                         f'Версия {item["version"]}</a> {escaped(item["note"] or "")}</p>')
        data = '{}' if chosen is None else json.dumps(
            store.load_plan(chosen['id']).model_dump(mode='json'), ensure_ascii=False, indent=2)
        values = submitted or {}
        parts.extend([self.form('save-plan', code), '<label>План (ForecastRequest / MulticurrencyRequest)'
                      f'<textarea name="request" rows="24">{escaped(values.get("request", data))}</textarea>'
                      '</label>', '<p><label>Заметка к версии '
                      f'<input name="plan_note" value="{escaped(values.get("plan_note", ""))}"></label></p>'])
        return ''.join(parts)

    def page(self, store: PlannerStore, code: str, view: str, version: str = '',
             submitted: dict[str, str] | None = None, notice: str = '') -> str:
        parts = ['<!doctype html><html lang="ru"><head><meta charset="utf-8">',
                 '<meta name="viewport" content="width=device-width,initial-scale=1">',
                 '<title>Локальная форма клиента</title>',
                 f'<style nonce="{self.server.style_nonce}">{STYLE}</style></head><body><main>',
                 '<h1>Клиенты и финансовые планы</h1>',
                 '<p>Данные остаются в локальной базе. Для работы человека; без подключения к ИИ.</p>',
                 f'<nav><a href="{self.server.entry_path}">Создать клиента</a> ']
        for row in store.list_clients():
            parts.append(f'<a href="{self.server.entry_path}?code={row["code"]}">{row["code"]}</a> ')
        if self.server.legacy is not None:
            parts.append(f'<a href="{self.server.entry_path}?view=legacy">'
                         'Просмотр базы LFP (только чтение)</a>')
        parts.append('</nav>')
        if notice:
            level = 'error' if submitted is not None else 'notice'
            parts.append(f'<p class="{level}" role="status">{escaped(notice)}</p>')
        row = store.get_client(code) if code else {}
        if code:
            parts.append(f'<h2>{escaped(code)}</h2><nav>'
                         f'<a href="{self.server.entry_path}?code={code}">Анкета</a> '
                         f'<a href="{self.server.entry_path}?code={code}&amp;view=plan">'
                         'Финансовые планы</a></nav>')
        if view == 'plan':
            parts.append(self.plan_fields(store, code, version, submitted))
        else:
            parts.append(self.form('update' if code else 'create', code))
            if submitted is not None:
                row.update(submitted)
                row['brokers_known'] = submitted.get('brokers_known') == 'yes'
            parts.append(self.identity_fields(row))
        parts.append('<p><button type="submit">Сохранить</button></p></form></main></body></html>')
        return ''.join(parts)

    def do_GET(self) -> None:
        if not self.allowed():
            self.reply(403, 'Доступ запрещён.')
            return
        try:
            query = single_values(parse_qs(urlsplit(self.path).query, strict_parsing=True))
            code = query.get('code', '')
            view = query.get('view', 'client')
            if view == 'legacy':
                if self.server.legacy is None:
                    raise ValueError('Legacy not enabled')
                content = self.server.legacy.page(self.server.entry_path, code,
                                                  query.get('version', ''), query.get('run', ''))
                page = ('<!doctype html><html lang="ru"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>Просмотр базы LFP</title>'
                        f'<style nonce="{self.server.style_nonce}">{STYLE}</style></head>'
                        f'<body><main>{content}</main></body></html>')
                self.reply(200, page)
                return
            if view not in ('client', 'plan'):
                raise ValueError('Unknown view')
            with PlannerStore.open(self.server.database) as store:
                page = self.page(store, code, view, query.get('version', ''),
                                 notice='Сохранено.' if query.get('saved') == '1' else '')
            self.reply(200, page)
        except Exception:
            self.reply(400, 'Не удалось открыть запись. Проверьте код и версию в локальной базе.')

    def do_POST(self) -> None:
        if not self.allowed(post=True):
            self.reply(403, 'Доступ запрещён.')
            return
        if urlsplit(self.path).query:
            self.reply(405, 'Сохранение по этому адресу недоступно.')
            return
        self.submit()

    def submit(self) -> None:
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.headers.get('Transfer-Encoding') or length <= 0:
                self.reply(400, 'Некорректный запрос.')
                return
            if length > MAX_BODY:
                self.reply(413, 'Запрос слишком большой.')
                return
            if self.headers.get_content_type() != 'application/x-www-form-urlencoded':
                self.reply(400, 'Некорректный формат запроса.')
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('Incomplete body')
            parsed = parse_qs(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=30)
            data = single_values(parsed)
            if not secrets.compare_digest(data.pop('csrf', '').encode('utf-8'),
                                          self.server.csrf.encode('utf-8')):
                self.reply(403, 'Доступ запрещён.')
                return
            nonce = data.pop('nonce', '')
            operation, code = data.pop('operation', ''), data.pop('code', '')
            expected = self.server.nonces.get(nonce)
            if expected is None:
                self.reply(409, 'Форма уже использована или устарела. Откройте её заново.')
                return
            if expected != (operation, code):
                self.reply(403, 'Доступ запрещён.')
                return
            del self.server.nonces[nonce]
            query = self.save(operation, code, data)
            query['saved'] = '1'
            self.reply(303, location=self.server.entry_path + '?' + urlencode(query))
        except Exception:
            self.validation_error(locals().get('code', ''), locals().get('operation', ''),
                                  locals().get('data', {}))

    def validation_error(self, code: str, operation: str, data: dict[str, str]) -> None:
        message = 'Запись не сохранена. Проверьте поля, формат плана и основной контакт.'
        try:
            with PlannerStore.open(self.server.database) as store:
                page = self.page(store, code, 'plan' if operation == 'save-plan' else 'client',
                                 submitted=data, notice=message)
            self.reply(400, page)
        except Exception:
            self.reply(400, message)

    def save(self, operation: str, code: str, data: dict[str, str]) -> dict[str, str]:
        with PlannerStore.open(self.server.database) as store:
            if operation == 'save-plan':
                if set(data) - {'request', 'plan_note'}:
                    raise ValueError('Unknown field')
                plan_id = store.save_plan(code, json.loads(data.get('request', '')),
                                          note=data.get('plan_note') or None)
                version = next(item['version'] for item in store.list_plans(code) if item['id'] == plan_id)
                return {'code': code, 'view': 'plan', 'version': str(version)}
            if set(data) - (ClientDetails.model_fields.keys() | {'brokers_known'}):
                raise ValueError('Unknown field')
            details = {key: data.get(key) or None for key in ClientDetails.model_fields}
            for key in ('birth_year', 'telegram_id'):
                if details[key] is not None:
                    details[key] = int(details[key])
            broker_text = data.get('brokers', '')
            details['brokers'] = ([line.strip() for line in broker_text.splitlines() if line.strip()]
                                  if broker_text.strip() or data.get('brokers_known') == 'yes' else None)
            if operation == 'create':
                code = store.create_client(details)['code']
            elif operation == 'update':
                store.update_client(code, details)
            else:
                raise ValueError('Unknown operation')
            return {'code': code}


def create_server(database: Path, port: int = 0, legacy_database: Path | None = None) -> FormServer:
    """Open an existing database and bind only to 127.0.0.1."""
    with PlannerStore.open(database):
        pass
    legacy = LegacyReader(legacy_database) if legacy_database is not None else None
    return FormServer(database, port, legacy)


def main(argv: list[str] | None = None) -> int:
    """Run local human intake; never start a browser or reveal database content."""
    parser = argparse.ArgumentParser(description='Human-only local client browser form (Russian UI)')
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--legacy-database', type=Path,
                        help='Optional existing LFP database; read-only, never migrated')
    parser.add_argument('--port', type=int, default=0, help='Loopback port; default chooses an unused port')
    parser.add_argument('--initialize', action='store_true',
                        help='Create a new empty database; never overwrite')
    arguments = parser.parse_args(argv)
    server = None
    try:
        if arguments.initialize:
            with PlannerStore.initialize(arguments.database):
                pass
        server = create_server(arguments.database, arguments.port, arguments.legacy_database)
        print(f'Open locally: http://127.0.0.1:{server.server_port}{server.entry_path}', flush=True)
        print('Stop with Ctrl+C. Keep this capability URL private.', flush=True)
        server.serve_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        print('Local form could not start. Check the database and port locally.', file=sys.stderr)
        return 2
    finally:
        if server is not None:
            server.server_close()


if __name__ == '__main__':
    sys.exit(main())
