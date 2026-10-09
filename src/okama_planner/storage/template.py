"""Generate a schema-only SQLite template; never copy an advisor's working database."""

from pathlib import Path

from .database import PlannerStore


def create_template(path: Path | str) -> None:
    with PlannerStore.initialize(path):
        pass
