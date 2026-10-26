"""Personal access is explicit, local and enforced by Planner, not an LLM argument."""

from pathlib import Path

import pytest
import okama_planner.ai as ai
from okama_planner.storage import PlannerStore

MARKER = "SYNTHETIC_PRIVATE_IDENTITY"


def test_default_access_masks_identity_and_denies_all_persistent_writes(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    with PlannerStore.initialize(path) as store:
        code = store.create_client({"full_name": MARKER, "crm_id": "CRM-0007"})["code"]
    access = getattr(ai, "PlannerClientAccess", None)
    assert access is not None, "Planner must own the personal-data access switch"
    service = access(path)
    assert MARKER not in str(service.client_get(code))
    assert "CRM-0007" not in str(service.client_get(code))
    for method, args in [
        ("client_create", ({"full_name": "Another"},)),
        ("client_update", (code, {"birth_year": 1980})),
        ("client_delete", (code,)),
        ("client_set_tax_residency", (code, 2026, "RU")),
        ("client_save_plan", (code, {})),
        ("meeting_save", (code, {"goal": "Private"})),
    ]:
        with pytest.raises(ValueError):
            getattr(service, method)(*args)
    with PlannerStore.open(path) as store:
        assert store.get_client(code)["birth_year"] is None
        assert len(store.list_clients()) == 1


def test_explicit_personal_access_crud_stays_in_planner_and_can_be_revoked(tmp_path: Path) -> None:
    path = tmp_path / "clients.db"
    PlannerStore.initialize(path).close()
    access = getattr(ai, "PlannerClientAccess", None)
    assert access is not None, "Missing Planner-owned personal access"
    service = access(path, allow_personal_data=True)
    record = service.client_create(
        {"full_name": MARKER, "crm_id": "CRM-007", "email": "fake@example.invalid"}
    )
    code = record["code"]
    assert service.client_get(code)["full_name"] == MARKER
    assert service.client_update(code, {"crm_id": "CRM-008"})["crm_id"] == "CRM-008"
    meeting = service.meeting_save(
        code, {"goal": MARKER, "date": "2026-10-26", "format": "online", "notes": MARKER}
    )
    assert service.meeting_list(code)[0]["notes"] == MARKER
    anonymous = access(path)
    assert MARKER not in str(anonymous.meeting_list(code))
    assert MARKER not in str(anonymous.client_list())
    assert service.meeting_delete(code, meeting["id"], meeting["revision"])["deleted"] is True
    assert service.client_delete(code)["deleted"] is True
    assert service.client_list() == []
    with PlannerStore.open(path) as store:
        assert store.create_client({"full_name": "Next"})["code"] == "c-0002"
