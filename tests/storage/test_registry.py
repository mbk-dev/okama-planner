from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import pytest

from okama_planner.storage import PlannerStore


def test_registry_roundtrip_and_stable_code(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path / "registry.db") as store:
        details = {
            "full_name": "Synthetic Example",
            "sex": "female",
            "birth_year": 1980,
            "email": "example@example.invalid",
            "phone": "+10000000000",
            "telegram": "@example",
            "telegram_id": 123456789,
            "whatsapp": "+10000000001",
            "max_messenger": "example",
            "brokers": ["Broker B", "Broker A"],
            "primary_channel": "email",
            "ips_sent_at": "2026-10-09",
            "note": "Fictional",
        }
        first = store.create_client(details)
        assert first["id"] == 1
        assert first["code"] == "c-0001"
        assert date.fromisoformat(first["ips_sent_at"]) == date(2026, 10, 9)
        assert datetime.fromisoformat(first["created_at"]).utcoffset().total_seconds() == 0
        assert {k: first[k] for k in details} == details
        assert store.get_client("c-0001") == first
        second = store.create_client({"full_name": "Synthetic Example", "brokers": []})
        assert second["code"] == "c-0002"
        assert second["brokers"] == []
        assert len(store.list_clients()) == 2
        patched = store.update_client(first["code"], {"full_name": "Synthetic Renamed", "brokers": None})
        assert patched["code"] == first["code"]
        assert patched["created_at"] == first["created_at"]
        assert patched["email"] == first["email"]
        assert patched["brokers"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"email": None},
        {"email": "   "},
        {"primary_channel": "telegram"},
        {"code": "other"},
        {"id": 2},
        {"created_at": "2020-01-01"},
        {"telegram_id": True},
        {"telegram_id": "123"},
        {"brokers": [""]},
        {"full_name": " "},
        {"birth_year": True},
        {"sex": "invalid"},
    ],
)
def test_invalid_patch_is_atomic(tmp_path: Path, changes: dict) -> None:
    with PlannerStore.initialize(tmp_path / "patch.db") as store:
        before = store.create_client(
            {"full_name": "Synthetic One", "email": "one@example.invalid", "primary_channel": "email"}
        )
        with pytest.raises(ValueError):
            store.update_client(before["code"], changes)
        assert store.get_client(before["code"]) == before
        cleared = store.update_client(before["code"], {"email": None, "primary_channel": None})
        assert cleared["email"] is None
        assert cleared["primary_channel"] is None


def test_missing_client_and_residency(tmp_path: Path) -> None:
    with PlannerStore.initialize(tmp_path / "residency.db") as store:
        client = store.create_client({"full_name": "Synthetic One"})
        assert store.get_tax_residency(client["code"], 2026) is None
        record = store.set_tax_residency(client["code"], 2026, "de", note="Synthetic")
        assert record["country"] == "DE"
        assert record["year"] == 2026
        assert store.get_tax_residency(client["code"], 2025) is None
        assert store.set_tax_residency(client["code"], 2026, "US")["id"] == record["id"]
        with pytest.raises(ValueError):
            store.set_tax_residency(client["code"], 2026, "ZZ")
        with pytest.raises(LookupError):
            store.get_client("c-9999")
        with pytest.raises(LookupError):
            store.set_tax_residency("c-9999", 2026, "DE")
        assert store.get_tax_residency(client["code"], 2026)["country"] == "US"


def test_concurrent_codes(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.db"
    PlannerStore.initialize(path).close()

    def create(index: int) -> str:
        with PlannerStore.open(path) as store:
            return store.create_client({"full_name": f"Synthetic {index}"})["code"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        codes = list(pool.map(create, range(6)))
    assert len(set(codes)) == 6
    with PlannerStore.open(path) as store:
        assert len(store.list_clients()) == 6
