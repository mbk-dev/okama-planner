"""Create the project-local parent before pytest initializes its base directory."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    (config.rootpath / 'tmp').mkdir(exist_ok=True)
