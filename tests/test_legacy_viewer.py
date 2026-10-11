"""Synthetic legacy databases only: real HTTP and immutable source checks."""

import hashlib
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from okama_planner import client_form
from okama_planner.storage import PlannerStore
from test_client_form import fields, send


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    path = tmp_path / 'legacy.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE client_registry(id INTEGER PRIMARY KEY, code TEXT, full_name TEXT, email TEXT);
        INSERT INTO client_registry VALUES(1,'c-0001','<script>Synthetic</script>','test@example.invalid');
        INSERT INTO client_registry VALUES(2,'c-0002','Other synthetic','other@example.invalid');
        CREATE TABLE client(id INTEGER PRIMARY KEY, registry_id INTEGER, version INTEGER, note TEXT);
        INSERT INTO client VALUES(10,1,1,'First version'),(11,1,2,'Second version'),(20,2,1,'Other version');
        CREATE TABLE tax_residency(registry_id INTEGER, year INTEGER, country TEXT);
        INSERT INTO tax_residency VALUES(1,2026,'RU');
        CREATE TABLE person(client_id INTEGER, name TEXT, birth_year INTEGER, role TEXT);
        INSERT INTO person VALUES(11,'Synthetic child',2010,'child');
        CREATE TABLE asset(client_id INTEGER, label TEXT, amount REAL, currency TEXT, asset_class TEXT);
        INSERT INTO asset VALUES(11,'Synthetic reserve',100,'RUB','reserve');
        CREATE TABLE liability(client_id INTEGER, label TEXT, principal REAL);
        INSERT INTO liability VALUES(11,'Synthetic mortgage',200);
        CREATE TABLE budget_item(client_id INTEGER, kind TEXT, label TEXT, monthly_amount REAL);
        INSERT INTO budget_item VALUES(11,'income','Synthetic income',30);
        CREATE TABLE goal(client_id INTEGER, label TEXT, kind TEXT, amount_pv REAL, target_year INTEGER);
        INSERT INTO goal VALUES(11,'Synthetic goal','lump',500,2030);
        CREATE TABLE portfolio(id INTEGER, client_id INTEGER, label TEXT, role TEXT);
        INSERT INTO portfolio VALUES(100,11,'Synthetic portfolio','accumulation'),
                                    (200,20,'Other portfolio','withdrawal');
        CREATE TABLE portfolio_holding(portfolio_id INTEGER, symbol TEXT, weight REAL);
        INSERT INTO portfolio_holding VALUES(100,'TEST.MOEX',1),(200,'HIDDEN.MOEX',1);
        CREATE TABLE scenario(id INTEGER, client_id INTEGER, label TEXT, is_base INTEGER);
        INSERT INTO scenario VALUES(101,11,'Synthetic scenario',1),(201,20,'Other scenario',0);
        CREATE TABLE plan_run(id INTEGER, scenario_id INTEGER, status TEXT, t0 TEXT, horizon_years INTEGER);
        INSERT INTO plan_run VALUES(1001,101,'ok','2026-01',20),(2001,201,'failed','2026-01',20);
        CREATE TABLE run_metric(plan_run_id INTEGER, key TEXT, value REAL);
        INSERT INTO run_metric VALUES(1001,'probability_of_success',0.75),(2001,'other metric',0);
        """)
    return path


@pytest.fixture
def legacy_browser(tmp_path: Path, legacy: Path) -> Iterator[tuple[client_form.FormServer, Path]]:
    planner = tmp_path / 'planner.sqlite3'
    with PlannerStore.initialize(planner):
        pass
    server = client_form.create_server(planner, legacy_database=legacy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, legacy
    server.shutdown()
    thread.join()
    server.server_close()


def test_readonly_browser_navigation_and_source_integrity(
    legacy_browser: tuple[client_form.FormServer, Path], capsys: Any,
) -> None:
    server, path = legacy_browser
    before = hashlib.sha256(path.read_bytes()).digest()
    _, _, form = send(server)
    assert '?view=legacy' in form
    route = server.entry_path + '?view=legacy'
    status, _, index = send(server, route)
    assert status == 200
    assert 'c-0001' in index and 'c-0002' in index
    assert 'test@example.invalid' in index
    status, _, page = send(server, route + '&code=c-0001')
    assert status == 200
    assert '&lt;script&gt;Synthetic&lt;/script&gt;' in page
    assert '<script>Synthetic</script>' not in page
    for text in ('test@example.invalid', '2026', 'RU', 'Second version', 'Synthetic child',
                 'Synthetic reserve', 'Synthetic mortgage', 'Synthetic income', 'Synthetic goal',
                 'Synthetic portfolio', 'TEST.MOEX', 'Synthetic scenario', '75', 'Planner'):
        assert text in page
    assert 'HIDDEN.MOEX' not in page and 'Other scenario' not in page
    assert 'method="post"' not in page
    assert f'href="{server.entry_path}"' in page
    assert 'только для чтения' in page
    assert send(server, route + '&code=c-0001&version=1')[0] == 200
    assert send(server, route + '&code=c-0001&run=1001')[0] == 200
    for query in ('&version=20', '&version=3', '&run=2001', '&run=0', '&code=c-0001&code=c-0002'):
        assert send(server, route + '&code=c-0001' + query)[0] == 400
    assert send(server, route, values=fields(form) | {'full_name': 'Blocked'})[0] == 405
    assert send(server, values=fields(form) | {'full_name': 'Planner Synthetic'})[0] == 303
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert sorted(p.name for p in path.parent.glob('legacy.sqlite3*')) == ['legacy.sqlite3']
    assert capsys.readouterr().err == ''


def test_legacy_requires_explicit_flag(tmp_path: Path) -> None:
    planner = tmp_path / 'planner.sqlite3'
    with PlannerStore.initialize(planner):
        pass
    server = client_form.create_server(planner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert 'view=legacy' not in send(server)[2]
        assert send(server, server.entry_path + '?view=legacy')[0] == 400
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.parametrize('kind', ['missing', 'directory', 'invalid', 'planner'])
def test_bad_legacy_path_is_generic_and_never_created(tmp_path: Path, kind: str, capsys: Any) -> None:
    planner = tmp_path / 'planner.sqlite3'
    with PlannerStore.initialize(planner):
        pass
    source = tmp_path / 'source.sqlite3'
    if kind == 'directory':
        source.mkdir()
    elif kind == 'invalid':
        source.write_text('not sqlite')
    elif kind == 'planner':
        with PlannerStore.initialize(source):
            pass
    assert client_form.main(['--database', str(planner), '--legacy-database', str(source)]) == 2
    output = capsys.readouterr()
    assert 'Traceback' not in output.err and str(source) not in output.err
    if kind == 'missing':
        assert not source.exists()


def test_connection_is_readonly_and_optional_tables_can_be_absent(legacy: Path) -> None:
    from okama_planner.legacy_viewer import LegacyReader

    reader = LegacyReader(legacy)
    db = reader.connect()
    try:
        assert db.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("UPDATE client_registry SET full_name='Changed'")
        db.execute('PRAGMA query_only=OFF')
        with pytest.raises(sqlite3.OperationalError):
            db.execute("UPDATE client_registry SET full_name='Changed'")
    finally:
        db.close()
    with sqlite3.connect(legacy) as setup:
        for name in ('person', 'asset', 'liability', 'budget_item', 'goal', 'portfolio',
                     'portfolio_holding', 'scenario', 'plan_run', 'run_metric', 'tax_residency'):
            setup.execute(f'DROP TABLE {name}')
    page = reader.page('/capability/', 'c-0001', '', '')
    assert 'Нет записей.' in page and 'Second version' in page


def test_goal_expense_share_is_percent_not_money(legacy: Path) -> None:
    from okama_planner.legacy_viewer import LegacyReader

    with sqlite3.connect(legacy) as setup:
        setup.execute('ALTER TABLE goal ADD COLUMN amount_basis TEXT')
        setup.execute("UPDATE goal SET amount_pv=0.8, amount_basis='expense_share'")
    page = LegacyReader(legacy).page('/capability/', 'c-0001', '', '')
    assert '80.00 %' in page and 'Доля семейных расходов' in page


@pytest.mark.parametrize('key,value', [('telegram', 'income'), ('note', 'ok'),
                                      ('name', 'female'), ('label', 'expense'), ('symbol', 'reserve')])
def test_free_text_is_not_translated_as_an_enum(key: str, value: str) -> None:
    from okama_planner.legacy_viewer import display

    assert display(key, value, {}) == value


def test_client_index_contacts_dates_and_detail_roundtrip(
    legacy_browser: tuple[client_form.FormServer, Path],
) -> None:
    server, path = legacy_browser
    with sqlite3.connect(path) as db:
        db.executescript("""
        ALTER TABLE client_registry ADD COLUMN phone TEXT;
        ALTER TABLE client_registry ADD COLUMN primary_channel TEXT;
        ALTER TABLE client_registry ADD COLUMN ips_sent_at TEXT;
        UPDATE client_registry SET phone='+1 555 0100', primary_channel='telegram',
            ips_sent_at='2026-09-20' WHERE id=1;
        ALTER TABLE plan_run ADD COLUMN created_at TEXT;
        UPDATE plan_run SET created_at='2026-09-10 12:00:00' WHERE id=1001;
        UPDATE plan_run SET created_at='2026-10-10 12:00:00' WHERE id=2001;
        INSERT INTO scenario VALUES(102,10,'Old version',1);
        INSERT INTO plan_run VALUES(1002,102,'ok','2026-01',20,'2026-09-15 12:00:00');
        INSERT INTO plan_run VALUES(1003,101,'failed','2026-01',20,'2026-10-09 12:00:00');
        """)
    before = hashlib.sha256(path.read_bytes()).digest()
    route = server.entry_path + '?view=legacy'
    status, _, index = send(server, route)
    assert status == 200
    assert '<table' in index
    assert '&lt;script&gt;Synthetic&lt;/script&gt;' in index
    assert '<script>Synthetic</script>' not in index
    assert '+1 555 0100' in index and 'Telegram' in index and 'test@example.invalid' in index
    assert '15.09.2026' in index and '20.09.2026' in index
    assert '10.10.2026' not in index and '09.10.2026' not in index
    assert 'Synthetic goal' not in index and 'Версии исходных данных' not in index
    assert f'href="{route}&amp;code=c-0001"' in index
    second_row = index.split('<tbody>')[1].split('<tr>')[2].split('</tr>')[0]
    assert second_row.count('—') == 4
    _, _, details = send(server, route + '&code=c-0001')
    assert 'Synthetic goal' in details
    assert f'href="{route}">К списку клиентов</a>' in details
    assert 'Other synthetic' not in details
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_client_index_with_minimal_schema_and_no_clients(legacy: Path) -> None:
    from okama_planner.legacy_viewer import LegacyReader

    with sqlite3.connect(legacy) as db:
        db.execute('DROP TABLE scenario')
    page = LegacyReader(legacy).page('/local/', '', '', '')
    assert 'test@example.invalid' in page and '<table' in page and '—' in page
    with sqlite3.connect(legacy) as db:
        db.execute('DELETE FROM client_registry')
    page = LegacyReader(legacy).page('/local/', '', '', '')
    assert 'Нет записей.' in page and 'Форма Planner' in page


def test_imported_notes_are_local_escaped_and_scoped_to_client(
    legacy_browser: tuple[client_form.FormServer, Path],
) -> None:
    server, path = legacy_browser
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE client_intake_note(id INTEGER, registry_id INTEGER, content TEXT, imported_at TEXT);
        INSERT INTO client_intake_note VALUES(1,1,'<script>synthetic</script> Goal: example','2026-10-11');
        INSERT INTO client_intake_note VALUES(2,2,'Other private note','2026-10-11');
        """)
    route = server.entry_path + '?view=legacy'
    _, _, index = send(server, route)
    assert 'Goal: example' not in index
    _, _, card = send(server, route + '&code=c-0001')
    assert '&lt;script&gt;synthetic&lt;/script&gt; Goal: example' in card
    assert '<script>synthetic</script>' not in card and 'Other private note' not in card
