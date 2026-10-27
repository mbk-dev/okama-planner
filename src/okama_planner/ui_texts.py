"""Localized captions for the human-facing local interfaces.

The browser form, the meeting journal and the legacy viewer render the same catalog so a
language is added in one file. Keys are stable identifiers; the browser bundle receives the
``ui_`` subset as JSON and never carries its own translations.
"""

import csv
from functools import lru_cache
from importlib.resources import files
from string import Formatter

from okama_planner.localization import LANGUAGES, LOCALES, locale_code

CATALOG = "ui_texts.csv"
DEFAULT_LANGUAGE = "en"


def _validate(rows: list[dict[str, str]]) -> None:
    seen = set()
    for row in rows:
        key, english = row.get("key"), row.get("en")
        if not key or not english or key in seen:
            raise ValueError(f"Missing or duplicate UI caption: {key!r}")
        seen.add(key)
        places = {name for _, name, _, _ in Formatter().parse(english) if name}
        for language in LANGUAGES:
            value = row.get(language)
            if not value or not value.strip():
                raise ValueError(f"Missing {language} UI caption: {key}")
            if {name for _, name, _, _ in Formatter().parse(value) if name} != places:
                raise ValueError(f"Inconsistent {language} placeholders: {key}")


@lru_cache
def catalog(language: str = DEFAULT_LANGUAGE) -> dict[str, str]:
    """Return the validated caption table for one supported language."""
    locale_code(language)
    with files("okama_planner").joinpath(CATALOG).open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    _validate(rows)
    return {row["key"]: row[language] for row in rows}


class UiText:
    """One language for one interface process."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        locale_code(language)
        self.language = language
        self.locale = LOCALES[language]
        self._captions = catalog(language)

    def text(self, key: str, **values: object) -> str:
        try:
            template = self._captions[key]
        except KeyError:
            raise ValueError(f"Unknown UI caption: {key!r}") from None
        return template.format(**values) if values else template

    def browser(self, prefix: str = "ui_") -> dict[str, str]:
        """Captions for the bundled browser script; keys stay stable in every language."""
        return {key: value for key, value in self._captions.items() if key.startswith(prefix)}
