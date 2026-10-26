"""Real HTTP journal requests must persist, reject cross-client edits and keep CSRF."""

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from okama_planner.client_form import create_server, FormServer
from okama_planner.storage import PlannerStore


@pytest.fixture
def journal(tmp_path: Path) -> Iterator[tuple[FormServer, Path]]:
    path = tmp_path / "clients.db"
    with PlannerStore.initialize(path) as store:
        store.create_client({"full_name": "Synthetic One", "crm_id": "CRM-001"})
        store.create_client({"full_name": "Synthetic Two"})
    server = create_server(path)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server, path
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


def request(
    server: FormServer, query: str = "", data: dict | None = None, origin: str | None = None
) -> tuple[int, dict[str, str], str]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    headers = {}
    if data is not None:
        headers = {
            "Content-Type": "application/json",
            "Origin": origin if origin is not None else f"http://127.0.0.1:{server.server_port}",
        }
    connection.request(
        "GET" if data is None else "POST",
        server.entry_path + query,
        body=json.dumps(data) if data is not None else None,
        headers=headers,
    )
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read().decode()
    connection.close()
    return result


def test_journal_http_save_replay_conflict_and_restart(journal: tuple[FormServer, Path]) -> None:
    server, path = journal
    status, _, page = request(server, "?view=meetings&code=c-0001")
    assert status == 200, "The selected client needs a real journal interface"
    assert "journal.js" in page
    status, headers, body = request(server, "?api=meetings&code=c-0001")
    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    bootstrap = json.loads(body)
    values = {
        "operation": "meeting",
        "code": "c-0001",
        "csrf": bootstrap["csrf"],
        "nonce": bootstrap["nonce"],
        "meeting": {
            "goal": "Review",
            "date": "2026-10-26",
            "time": "",
            "format": "online",
            "notes": "## Saved Markdown\n\n<script>not executable</script>",
        },
    }
    status, _, body = request(server, data=values)
    assert status == 200
    saved = json.loads(body)
    assert saved["meeting"]["id"] == 1
    assert request(server, data=values)[0] == 409
    bad = values | {"nonce": saved["nonce"], "meeting_id": 1, "revision": "outdated"}
    assert request(server, data=bad)[0] == 409
    status, _, body = request(server, "?api=meetings&code=c-0002")
    other = json.loads(body)
    assert (
        request(
            server,
            data=values
            | {
                "code": "c-0002",
                "nonce": other["nonce"],
                "meeting_id": 1,
                "revision": saved["meeting"]["revision"],
            },
        )[0]
        == 400
    )
    with PlannerStore.open(path) as store:
        assert store.list_meetings("c-0001")[0]["goal"] == "Review"
        assert store.list_meetings("c-0002") == []


def test_journal_requires_origin_csrf_and_safe_static_path(journal: tuple[FormServer, Path]) -> None:
    server, _ = journal
    assert request(server, "?api=meetings&code=c-9999")[0] == 400
    assert request(server, data={"operation": "meeting"}, origin="https://evil.invalid")[0] == 403
    assert request(server, data={"operation": "meeting", "csrf": "invalid"})[0] == 403
    status, headers, script = request(server, "?asset=journal.js")
    assert status == 200
    assert headers["Content-Type"].startswith("application/javascript")
    assert "root" in script
    assert request(server, "?asset=../client_form.py")[0] == 400
