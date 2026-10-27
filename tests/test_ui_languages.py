"""Every human interface renders in every supported language."""

import http.client
import json
import threading

import pytest

from okama_planner.client_form import FormServer, create_server
from okama_planner.localization import LANGUAGES
from okama_planner.storage import PlannerStore
from okama_planner.ui_texts import catalog

CYRILLIC = range(0x0400, 0x0500)


def has_cyrillic(text: str) -> bool:
    return any(ord(character) in CYRILLIC for character in text)


@pytest.fixture
def server_factory(tmp_path):
    servers: list[FormServer] = []

    def make(language: str) -> FormServer:
        path = tmp_path / f"clients-{language}.sqlite3"
        with PlannerStore.initialize(path) as store:
            store.create_client({"full_name": "Synthetic Client", "crm_id": "CRM-1"})
            store.save_meeting("c-0001", {"goal": "Review", "date": "2026-10-20", "format": "online"})
        server = create_server(path, language=language)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        return server

    try:
        yield make
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def get(server: FormServer, query: str = "") -> str:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request("GET", server.entry_path + query)
    response = connection.getresponse()
    body = response.read().decode()
    connection.close()
    return body


def test_catalog_covers_every_language() -> None:
    english = catalog("en")
    assert english, "the UI catalog must not be empty"
    for language in LANGUAGES:
        assert set(catalog(language)) == set(english), f"{language} misses captions"


@pytest.mark.parametrize("language", LANGUAGES)
def test_client_form_renders_in_each_language(server_factory, language: str) -> None:
    captions = catalog(language)
    page = get(server_factory(language))
    assert f'<html lang="{language}">' in page
    assert captions["ui_clients_and_plans"] in page
    assert captions["field.full_name"] in page
    assert captions["ui_save"] in page
    if language != "ru":
        assert not has_cyrillic(page), "untranslated Russian text reached a non-Russian interface"


@pytest.mark.parametrize("language", LANGUAGES)
def test_journal_page_carries_localized_captions(server_factory, language: str) -> None:
    captions = catalog(language)
    page = get(server_factory(language), "?view=meetings&code=c-0001")
    assert f'data-language="{language}"' in page
    assert f"<title>{captions['ui_meeting_journal_title']}</title>" in page
    start = page.index("data-strings='") + len("data-strings='")
    payload = page[start:page.index("'", start)]
    strings = json.loads(payload.replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&"))
    assert strings["ui_save"] == captions["ui_save"]
    assert strings["ui_new_meeting"] == captions["ui_new_meeting"]
    assert not any(value == key for key, value in strings.items() if language != "en")


@pytest.mark.parametrize("language", LANGUAGES)
def test_legacy_viewer_renders_in_each_language(server_factory, language: str) -> None:
    captions = catalog(language)
    page = get(server_factory(language), "?view=legacy")
    assert captions["legacy.clients_heading"] in page
    assert captions["legacy.lfp_date"] in page
    if language != "ru":
        assert not has_cyrillic(page), "untranslated Russian text reached the legacy viewer"
