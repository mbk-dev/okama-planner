"""Shared presentation terminology; user input and provenance remain untouched."""

import csv
from functools import lru_cache
from importlib.resources import files

LANGUAGES = ("en", "ru", "zh", "de", "es")


@lru_cache
def terminology(language: str = "en") -> dict[str, str]:
    """Return English-caption to localized-caption mapping from the packaged CSV."""
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language {language!r}; expected one of {LANGUAGES}")
    with files("okama_planner").joinpath("terminology.csv").open(encoding="utf-8", newline="") as source:
        return {row["en"]: row[language] for row in csv.DictReader(source)}


def translate(text: str, language: str = "en", **values: str) -> str:
    """Translate a template caption, substituting only explicitly supplied values."""
    return terminology(language).get(text, text).format(**values) if values else terminology(language).get(
        text, text
    )
