"""Client identity and annual tax residence, independent of financial versions."""

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from .models import ClientRegistry, TaxResidency
from .validation import ClientDetails, ResidencyDetails


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def record(row: Any) -> dict[str, Any]:
    data = {}
    for column in inspect(type(row)).columns:
        value = getattr(row, column.key)
        if isinstance(value, datetime):
            value = value.replace(tzinfo=UTC).isoformat()
        elif isinstance(value, date):
            value = value.isoformat()
        data[column.key] = value
    return data


def require_client(session: Session, code: str) -> ClientRegistry:
    row = session.scalar(select(ClientRegistry).where(ClientRegistry.code == code))
    if row is None:
        raise LookupError(f"Unknown client code: {code}")
    return row


class RegistryMethods:
    def create_client(self, details: dict[str, Any]) -> dict[str, Any]:
        data = ClientDetails.model_validate(details).model_dump()
        with self._transaction() as session:
            # A provisional code is never committed; flush allocates an AUTOINCREMENT ID.
            row = ClientRegistry(code="", created_at=now(), **data)
            session.add(row)
            session.flush()
            row.code = f"c-{row.id:04d}"
            session.flush()
            return record(row)

    def get_client(self, code: str) -> dict[str, Any]:
        with self._transaction() as session:
            return record(require_client(session, code))

    def list_clients(self) -> list[dict[str, Any]]:
        with self._transaction() as session:
            return [
                record(row) for row in session.scalars(select(ClientRegistry).order_by(ClientRegistry.id))
            ]

    def update_client(self, code: str, changes: dict[str, Any]) -> dict[str, Any]:
        unknown = set(changes) - ClientDetails.model_fields.keys()
        if unknown:
            raise ValueError(f"Fields cannot be updated: {sorted(unknown)}")
        with self._transaction() as session:
            row = require_client(session, code)
            merged = {key: getattr(row, key) for key in ClientDetails.model_fields}
            data = ClientDetails.model_validate(merged | changes).model_dump()
            for key, value in data.items():
                setattr(row, key, value)
            session.flush()
            return record(row)

    def set_tax_residency(
        self,
        code: str,
        year: int,
        country: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        data = ResidencyDetails(year=year, country=country, note=note).model_dump()
        with self._transaction() as session:
            client = require_client(session, code)
            row = session.scalar(
                select(TaxResidency).where(
                    TaxResidency.registry_id == client.id,
                    TaxResidency.year == year,
                )
            )
            if row is None:
                row = TaxResidency(registry_id=client.id, **data)
                session.add(row)
            else:
                row.country, row.note = data["country"], data["note"]
            session.flush()
            return record(row)

    def get_tax_residency(self, code: str, year: int) -> dict[str, Any] | None:
        ResidencyDetails(year=year, country="US")
        with self._transaction() as session:
            client = require_client(session, code)
            row = session.scalar(
                select(TaxResidency).where(
                    TaxResidency.registry_id == client.id,
                    TaxResidency.year == year,
                )
            )
            return None if row is None else record(row)
