"""Explicit database creation, schema checks and transaction boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
import os
import re
from pathlib import Path
from threading import RLock
from urllib.parse import quote
from typing import Any, Self

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.config import Config
from sqlalchemy import Connection, Engine, URL, create_engine, event, inspect
from sqlalchemy.orm import Session

from .registry import RegistryMethods
from .plans import PlanMethods
from .models import Base

HEAD = "0002"
REVISIONS = {"0001", HEAD}
# Alembic command/env module proxies are shared within one Python process.
_MIGRATION_LOCK = RLock()


def make_engine(path: Path | str) -> Engine:
    uri = "file:" + quote(str(Path(path).resolve()), safe="/")
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=uri, query={"mode": "rw", "uri": "true"}),
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure(connection: Any, record: Any) -> None:
        connection.isolation_level = None
        connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin(connection: Connection) -> None:
        statement = "BEGIN IMMEDIATE" if connection.get_execution_options().get("sqlite_write") else "BEGIN"
        connection.exec_driver_sql(statement)

    return engine


def migration_config(connection: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations").replace("%", "%%"))
    config.attributes["connection"] = connection
    return config


def _revision(connection: Connection) -> str:
    if "alembic_version" not in inspect(connection).get_table_names():
        raise ValueError("Unrecognized database schema: missing revision")
    revisions = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalars().all()
    if len(revisions) != 1 or revisions[0] not in REVISIONS:
        raise ValueError("Unrecognized database schema revision")
    return revisions[0]


def _validate_schema(connection: Connection) -> None:
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})
    if compare_metadata(context, Base.metadata):
        raise ValueError("Database schema does not match its declared revision")
    inspector = inspect(connection)
    for name, table in Base.metadata.tables.items():
        expected = [column.name for column in table.primary_key.columns]
        if inspector.get_pk_constraint(name)["constrained_columns"] != expected:
            raise ValueError(f"Database schema has an invalid primary key: {name}")
    # Alembic autogeneration does not compare primary keys or SQLite AUTOINCREMENT.
    sql = connection.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='client_registry'"
    ).scalar_one()
    sql = re.sub(r"/\*.*?\*/|--[^\n]*", "", sql, flags=re.S)
    if not re.search(r"\bid\s+INTEGER\s+NOT\s+NULL\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", sql, re.I):
        raise ValueError("Database schema must preserve client identity AUTOINCREMENT")


def upgrade_database(path: Path | str) -> None:
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    engine = make_engine(path)
    try:
        with _MIGRATION_LOCK, engine.begin() as connection:
            _revision(connection)
            command.upgrade(migration_config(connection), "head")
            _validate_schema(connection)
    finally:
        engine.dispose()


class PlannerStore(RegistryMethods, PlanMethods):
    """Local client/planning repository; operations commit or roll back together."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @classmethod
    def initialize(cls, path: Path | str) -> Self:
        path = Path(path).resolve()
        # Exclusive creation prevents overwriting an existing database, even in a race.
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        engine = make_engine(path)
        try:
            with _MIGRATION_LOCK, engine.begin() as connection:
                command.upgrade(migration_config(connection), "head")
            return cls(engine)
        except BaseException:
            engine.dispose()
            raise

    @classmethod
    def open(cls, path: Path | str) -> Self:
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        engine = make_engine(path)
        try:
            with engine.connect() as connection:
                if _revision(connection) != HEAD:
                    raise ValueError("Database schema needs upgrade_database before opening")
                _validate_schema(connection)
            return cls(engine)
        except BaseException:
            engine.dispose()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        with self.engine.connect().execution_options(sqlite_write=True) as connection:
            # Serialize version/code assignment before reading the current maximum.
            connection.begin()
            with Session(bind=connection) as session:
                try:
                    yield session
                    session.flush()
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
