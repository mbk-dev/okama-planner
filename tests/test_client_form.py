"""Real loopback requests catch missing intake, validation and access boundaries."""

import http.client
import json
import re
import threading
from collections.abc import Iterator
from typing import Any
from pathlib import Path
from urllib.parse import urlencode

import pytest



from okama_planner import client_form
from okama_planner.storage import PlannerStore

@pytest.fixture
def browser(tmp_path: Path) -> Iterator[tuple[client_form.FormServer, Path]]:
    database = tmp_path / 'clients.sqlite3'
    with PlannerStore.initialize(database):
        pass
    server = client_form.create_server(database)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, database
    server.shutdown()
    thread.join()
    server.server_close()


def send(
    server: client_form.FormServer, path: str | None = None, values: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], str]:
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    body = None if values is None else urlencode(values)
    request_headers = {} if headers is None else headers.copy()
    if values is not None:
        request_headers.setdefault('Content-Type', 'application/x-www-form-urlencoded')
        request_headers.setdefault('Origin', f'http://127.0.0.1:{server.server_port}')
    connection.request('GET' if values is None else 'POST', path or server.entry_path,
                       body=body, headers=request_headers)
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read().decode()
    connection.close()
    return result


def fields(page: str) -> dict[str, str]:
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page))


def test_create_edit_escape_and_replay(browser: tuple[client_form.FormServer, Path], capsys: Any) -> None:
    server, database = browser
    status, headers, page = send(server)
    assert status == 200
    assert headers['Cache-Control'] == 'no-store'
    assert headers['Referrer-Policy'] == 'same-origin'
    assert "default-src 'none'" in headers['Content-Security-Policy']
    values = fields(page) | {'full_name': '<script>fictional</script>', 'email': 'a@example.invalid',
                             'brokers': '', 'brokers_known': 'yes', 'primary_channel': 'email',
                             'birth_year': '1980',
                             'telegram_id': '123', 'ips_sent_at': '2026-10-10', 'note': 'Synthetic'}
    status, headers, _ = send(server, values=values)
    assert status == 303
    assert 'c-0001' in headers['Location']
    assert 'fictional' not in headers['Location']
    assert send(server, values=values)[0] == 409
    _, _, page = send(server, headers['Location'])
    assert '&lt;script&gt;fictional&lt;/script&gt;' in page
    assert '<script>fictional</script>' not in page
    values = fields(page) | {'full_name': 'Synthetic Updated', 'brokers': 'Broker A', 'brokers_known': 'yes'}
    assert send(server, values=values)[0] == 303
    with PlannerStore.open(database) as store:
        assert len(store.list_clients()) == 1
        assert store.get_client('c-0001')['full_name'] == 'Synthetic Updated'
        assert store.get_client('c-0001')['brokers'] == ['Broker A']
    assert capsys.readouterr().err == ''


@pytest.mark.parametrize('headers,path', [
    ({'Host': 'evil.invalid'}, None),
    ({'Origin': 'https://evil.invalid'}, None),
    ({}, '/'),
])
def test_access_rejected(browser: tuple[client_form.FormServer, Path],
                         headers: dict[str, str], path: str | None) -> None:
    server, _ = browser
    assert send(server, path, headers=headers)[0] == 403


def test_csrf_validation_and_body_limit(browser: tuple[client_form.FormServer, Path]) -> None:
    server, database = browser
    _, _, page = send(server)
    good = fields(page)
    assert send(server, values={'full_name': 'Synthetic'})[0] == 403
    status, _, error_page = send(
        server, values=good | {'full_name': 'Synthetic', 'birth_year': 'not integer'})
    assert status == 400
    assert 'value="Synthetic"' in error_page
    assert fields(error_page)['nonce'] != good['nonce']
    assert send(server, values=good | {'full_name': 'Synthetic'}, headers={'Origin': ''})[0] == 403
    assert send(server, values=good, headers={'Content-Length': '1100000'})[0] == 413
    with PlannerStore.open(database) as store:
        assert store.list_clients() == []


def test_plan_versions_and_ownership(browser: tuple[client_form.FormServer, Path]) -> None:
    server, database = browser
    with PlannerStore.open(database) as store:
        store.create_client({'full_name': 'Synthetic One'})
        store.create_client({'full_name': 'Synthetic Two'})
    path = server.entry_path + '?code=c-0001&view=plan'
    _, _, page = send(server, path)
    data = json.loads(Path('examples/readme-request.json').read_text())
    values = fields(page) | {'request': json.dumps(data), 'plan_note': 'Synthetic version'}
    status, headers, _ = send(server, values=values)
    assert status == 303
    assert send(server, values=values)[0] == 409
    _, _, page = send(server, headers['Location'])
    assert 'Synthetic version' in page
    assert '&quot;currency&quot;' in page
    with PlannerStore.open(database) as store:
        assert len(store.list_plans('c-0001')) == 1
        assert store.load_plan(1).currency == 'USD'
    assert send(server, server.entry_path + '?code=c-0002&view=plan&version=1')[0] == 400
    _, _, page = send(server, path)
    assert send(server, values=fields(page) | {'request': '{}'})[0] == 400


def test_cli_initialization_is_explicit_and_never_overwrites(tmp_path: Path, capsys: Any) -> None:
    database = tmp_path / 'clients.sqlite3'
    assert client_form.main(['--database', str(database)]) == 2
    assert not database.exists()
    with PlannerStore.initialize(database):
        pass
    before = database.read_bytes()
    assert client_form.main(['--database', str(database), '--initialize']) == 2
    assert database.read_bytes() == before
    assert 'Traceback' not in capsys.readouterr().err


def test_rejected_forged_tokens_and_nonce_binding(browser: tuple[client_form.FormServer, Path]) -> None:
    server, database = browser
    _, _, page = send(server)
    values = fields(page) | {'full_name': 'Synthetic'}
    assert send(server, values=values | {'csrf': 'поддельный'})[0] == 403
    assert send(server, values=values | {'operation': 'update', 'code': 'c-0001'})[0] == 403
    assert send(server, values=values)[0] == 303
    with PlannerStore.open(database) as store:
        assert len(store.list_clients()) == 1


def test_saved_plan_redirect_uses_own_version(browser: tuple[client_form.FormServer, Path],
                                               monkeypatch: Any) -> None:
    server, database = browser
    with PlannerStore.open(database) as store:
        store.create_client({'full_name': 'Synthetic'})
    original = PlannerStore.save_plan

    def another_writer(self: PlannerStore, code: str, request: dict[str, Any],
                       note: str | None = None) -> int:
        identifier = original(self, code, request, note)
        with PlannerStore.open(database) as other:
            original(other, code, request, 'Independent writer')
        return identifier

    monkeypatch.setattr(PlannerStore, 'save_plan', another_writer)
    _, _, page = send(server, server.entry_path + '?code=c-0001&view=plan')
    request = json.loads(Path('examples/readme-request.json').read_text())
    status, headers, _ = send(server, values=fields(page) | {'request': json.dumps(request)})
    assert status == 303
    assert 'version=1' in headers['Location']
    with PlannerStore.open(database) as store:
        assert len(store.list_plans('c-0001')) == 2
