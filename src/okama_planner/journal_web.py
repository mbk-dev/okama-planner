"""Capability-protected local journal; never registered as an MCP HTTP endpoint."""

import json
import secrets
from importlib.resources import files
from typing import Any

from okama_planner.storage import PlannerStore


def nonce(handler: Any, code: str) -> str:
    if len(handler.server.nonces) >= 256:
        del handler.server.nonces[next(iter(handler.server.nonces))]
    token = secrets.token_urlsafe(32)
    handler.server.nonces[token] = "meeting", code
    return token


def reply(handler: Any, status: int, payload: dict[str, Any]) -> None:
    handler.reply(
        status, json.dumps(payload, ensure_ascii=False), content_type="application/json; charset=utf-8"
    )


def get(handler: Any, query: dict[str, str]) -> bool:
    if "asset" in query:
        asset = query["asset"]
        if asset not in {"journal.js", "journal.css"}:
            raise ValueError("Unknown journal asset")
        content = files("okama_planner").joinpath("_journal_assets", asset).read_text(encoding="utf-8")
        kind = "application/javascript" if asset.endswith(".js") else "text/css"
        handler.reply(200, content, content_type=kind + "; charset=utf-8")
        return True
    if query.get("api") != "meetings" and query.get("view") != "meetings":
        return False
    code = query.get("code", "")
    with PlannerStore.open(handler.server.database) as store:
        store.get_client(code)
        if query.get("api") == "meetings":
            reply(
                handler,
                200,
                {
                    "code": code,
                    "meetings": store.list_meetings(code),
                    "csrf": handler.server.csrf,
                    "nonce": nonce(handler, code),
                },
            )
        else:
            # Codes are validated against storage, then still escaped at the HTML boundary.
            from html import escape

            entry, ui = handler.server.entry_path, handler.server.ui
            strings = json.dumps(ui.browser(), ensure_ascii=False).replace("<", "\\u003c")
            handler.reply(
                200,
                f'<!doctype html><html lang="{ui.language}"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{ui.text("ui_meeting_journal_title")}</title>'
                f'<link rel="stylesheet" href="{entry}?asset=journal.css"></head><body>'
                f'<div id="root" data-code="{escape(code, quote=True)}" '
                f'data-language="{ui.language}" data-locale="{ui.locale}" '
                f"data-strings='{escape(strings, quote=True)}'></div>"
                f'<script type="module" src="{entry}?asset=journal.js"></script></body></html>',
            )
    return True


def post(handler: Any) -> None:
    data: dict[str, Any] = {}
    code = ""
    try:
        length = int(handler.headers.get("Content-Length", "0"))
        if handler.headers.get("Transfer-Encoding") or not 0 < length <= 1_048_576:
            reply(handler, 413, {"error": handler.server.ui.text("ui_request_malformed")})
            return
        raw = handler.rfile.read(length)
        if len(raw) != length:
            raise ValueError("Incomplete JSON body")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        csrf = data.get("csrf", "")
        if not isinstance(csrf, str) or not secrets.compare_digest(csrf, handler.server.csrf):
            reply(handler, 403, {"error": handler.server.ui.text("ui_access_denied")})
            return
        code, token = data.get("code", ""), data.get("nonce", "")
        expected = handler.server.nonces.get(token) if isinstance(token, str) else None
        if expected is None:
            reply(
                handler,
                409,
                {"error": handler.server.ui.text("ui_journal_expired"), "nonce": nonce(handler, code)},
            )
            return
        if expected != ("meeting", code) or data.get("operation") != "meeting":
            reply(handler, 403, {"error": handler.server.ui.text("ui_access_denied")})
            return
        del handler.server.nonces[token]
        if set(data) - {"operation", "code", "csrf", "nonce", "meeting_id", "revision", "meeting"}:
            raise ValueError("Unknown journal field")
        with PlannerStore.open(handler.server.database) as store:
            result = store.save_meeting(code, data["meeting"], data.get("meeting_id"), data.get("revision"))
        reply(handler, 200, {"meeting": result, "nonce": nonce(handler, code)})
    except ValueError as error:
        conflict = "Meeting changed;" in str(error)
        reply(
            handler,
            409 if conflict else 400,
            {
                "error": handler.server.ui.text(
                    "ui_journal_conflict" if conflict else "ui_journal_save_failed"
                ),
                "nonce": nonce(handler, code),
            },
        )
    except Exception:
        reply(
            handler,
            400,
            {
                "error": handler.server.ui.text("ui_record_not_saved"),
                "nonce": nonce(handler, code),
            },
        )
