"""Human-only meeting records; optimistic edits also detect writes by older clients."""

import hashlib
import json
import re
from datetime import date, time
from typing import Any

from sqlalchemy import select

from .advisor_models import ClientMeeting
from .registry import require_client

FIELDS = {"goal", "date", "time", "format", "notes"}


def meeting_record(row: ClientMeeting) -> dict[str, Any]:
    raw = {key: getattr(row, key) for key in ("id", "registry_id", "goal", "date", "time", "format", "notes")}
    raw["date"] = raw["date"].isoformat()
    raw["time"] = raw["time"].isoformat() if raw["time"] is not None else ""
    raw["format"] = str(raw["format"])
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {**raw, "time": raw["time"][:5], "revision": digest}


def meeting_values(values: dict[str, Any]) -> dict[str, Any]:
    if set(values) - FIELDS:
        raise ValueError("Unknown meeting field")
    goal, day, clock = values.get("goal", ""), values.get("date", ""), values.get("time", "")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("A meeting goal is required")
    if not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
        raise ValueError("Expected an ISO meeting date")
    if clock and (not isinstance(clock, str) or not re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", clock)):
        raise ValueError("Expected a valid HH:MM time")
    if values.get("format") not in {"in_person", "online", "phone"}:
        raise ValueError("Unknown meeting format")
    notes = values.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 200_000:
        raise ValueError("Invalid meeting notes")
    return {
        "goal": goal,
        "date": date.fromisoformat(day),
        "time": time.fromisoformat(clock) if clock else None,
        "format": values["format"],
        "notes": notes,
    }


class MeetingMethods:
    def list_meetings(self, code: str) -> list[dict[str, Any]]:
        with self._transaction() as session:
            client = require_client(session, code)
            rows = session.scalars(
                select(ClientMeeting)
                .where(ClientMeeting.registry_id == client.id)
                .order_by(ClientMeeting.date.desc(), ClientMeeting.time.desc(), ClientMeeting.id.desc())
            )
            return [meeting_record(row) for row in rows]

    def save_meeting(
        self,
        code: str,
        values: dict[str, Any],
        meeting_id: int | None = None,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        data = meeting_values(values)
        with self._transaction() as session:
            client = require_client(session, code)
            if meeting_id is None:
                if expected_revision is not None:
                    raise ValueError("A new meeting has no revision")
                row = ClientMeeting(registry_id=client.id, **data)
                session.add(row)
            else:
                if type(meeting_id) is not int or meeting_id < 1:
                    raise ValueError("Invalid meeting ID")
                row = session.scalar(
                    select(ClientMeeting).where(
                        ClientMeeting.id == meeting_id, ClientMeeting.registry_id == client.id
                    )
                )
                if row is None:
                    raise LookupError("Unknown client meeting")
                if expected_revision != meeting_record(row)["revision"]:
                    raise ValueError("Meeting changed; reload before saving")
                for key, value in data.items():
                    setattr(row, key, value)
            session.flush()
            return meeting_record(row)
