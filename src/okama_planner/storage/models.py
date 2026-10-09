"""Neutral client identity and append-only planning records."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ClientRegistry(Base):
    __tablename__ = "client_registry"
    __table_args__ = (UniqueConstraint("code"), {"sqlite_autoincrement": True})
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]
    full_name: Mapped[str]
    sex: Mapped[str | None]
    birth_year: Mapped[int | None]
    email: Mapped[str | None]
    phone: Mapped[str | None]
    telegram: Mapped[str | None]
    telegram_id: Mapped[int | None]
    whatsapp: Mapped[str | None]
    max_messenger: Mapped[str | None]
    brokers: Mapped[list[str] | None] = mapped_column(JSON(none_as_null=True))
    primary_channel: Mapped[str | None]
    ips_sent_at: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime)


class TaxResidency(Base):
    __tablename__ = "tax_residency"
    __table_args__ = (UniqueConstraint("registry_id", "year"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int] = mapped_column(ForeignKey("client_registry.id"))
    year: Mapped[int]
    country: Mapped[str] = mapped_column(String(2))
    note: Mapped[str | None]


class Client(Base):
    __tablename__ = "client"
    __table_args__ = (UniqueConstraint("registry_id", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    registry_id: Mapped[int] = mapped_column(ForeignKey("client_registry.id"))
    version: Mapped[int]
    source_digest: Mapped[str]
    note: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PlanSnapshot(Base):
    __tablename__ = "plan_snapshot"
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id"), primary_key=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSON)


# Component payloads follow the public input contract, not private ORM columns.
# IDs inside payloads (e.g. goal_id) remain request identifiers, not database IDs.
class Component:
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id"))
    position: Mapped[int]
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class Person(Component, Base):
    __tablename__ = "person"
    __table_args__ = (UniqueConstraint("client_id", "position"),)


class Asset(Component, Base):
    __tablename__ = "asset"
    __table_args__ = (UniqueConstraint("client_id", "position"),)


class Liability(Component, Base):
    __tablename__ = "liability"
    __table_args__ = (UniqueConstraint("client_id", "position"),)


class BudgetItem(Component, Base):
    __tablename__ = "budget_item"
    __table_args__ = (UniqueConstraint("client_id", "position"),)


class Goal(Component, Base):
    __tablename__ = "goal"
    __table_args__ = (UniqueConstraint("client_id", "position"),)


class Portfolio(Component, Base):
    __tablename__ = "portfolio"
    __table_args__ = (UniqueConstraint("client_id", "position"),)


class Scenario(Base):
    __tablename__ = "scenario"
    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("client.id"))
    label: Mapped[str]
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PlanRun(Base):
    __tablename__ = "plan_run"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenario.id"))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_digest: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime)
