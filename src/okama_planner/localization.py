"""Shared presentation terminology; user input and provenance remain untouched."""

import csv
import math
from collections.abc import Iterable, Mapping
from datetime import date
from functools import lru_cache, wraps
from importlib.resources import files
from string import Formatter
from typing import Any, ParamSpec, TypeVar
from collections.abc import Callable

from pydantic import ValidationError

LANGUAGES = ("en", "ru", "zh", "de", "es")
LOCALES = {"en": "en-US", "ru": "ru-RU", "zh": "zh-CN", "de": "de-DE", "es": "es-ES"}
EXCEL_LOCALES = {"en": "409", "ru": "419", "zh": "804", "de": "407", "es": "C0A"}
CLIENT_FIELDS = {
    "id": "Record ID",
    "code": "Client code",
    "full_name": "Full name",
    "sex": "Sex",
    "birth_year": "Birth year",
    "email": "Email",
    "phone": "Phone",
    "telegram": "Telegram",
    "telegram_id": "Telegram ID",
    "whatsapp": "WhatsApp",
    "max_messenger": "MAX",
    "brokers": "Brokers",
    "primary_channel": "Primary contact channel",
    "ips_sent_at": "IPS sent date",
    "note": "Note",
    "created_at": "Created at",
    "updated_at": "Updated at",
    "registry_id": "Registry ID",
    "year": "Year",
    "country": "Country",
}
ENUM_CAPTIONS = {
    "female": "Female",
    "male": "Male",
    "email": "Email",
    "phone": "Phone",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "max": "MAX",
}

P = ParamSpec("P")
T = TypeVar("T")


def presentation_boundary(function: Callable[P, T]) -> Callable[P, T]:
    """Translate expected presentation failures; retain English compatibility by default."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        language = kwargs.get("language", "en")
        locale_code(language)
        try:
            return function(*args, **kwargs)
        except (ValueError, RuntimeError, LookupError, OSError) as error:
            if language == "en":
                raise
            if isinstance(error, ValidationError):
                raise ValueError(localized_error(error, language)) from None
            raise type(error)(localized_error(error, language)) from None

    return wrapped


def locale_code(language: str = "en") -> str:
    """Resolve a supported language explicitly, independently of plan currency."""
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language {language!r}; expected one of {LANGUAGES}")
    return LOCALES[language]


def validate_terminology(rows: Iterable[Mapping[str, str]]) -> None:
    """Reject incomplete catalogs, ambiguous keys and inconsistent substitutions."""
    seen_keys, seen_texts = set(), set()
    for row in rows:
        key, english = row.get("key"), row.get("en")
        if not key or key in seen_keys or not english or english in seen_texts:
            raise ValueError(f"Missing or duplicate terminology key/caption: {key!r}")
        seen_keys.add(key)
        seen_texts.add(english)
        placeholders = {field for _, field, _, _ in Formatter().parse(english) if field is not None}
        for language in LANGUAGES:
            value = row.get(language)
            if not value or not value.strip():
                raise ValueError(f"Missing {language} translation: {key}")
            fields = {field for _, field, _, _ in Formatter().parse(value) if field is not None}
            if fields != placeholders:
                raise ValueError(f"Inconsistent {language} placeholders: {key}")


@lru_cache
def terminology(language: str = "en") -> dict[str, str]:
    """Return English-caption to localized-caption mapping from the validated CSV."""
    locale_code(language)
    with files("okama_planner").joinpath("terminology.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    validate_terminology(rows)
    return {row["en"]: row[language] for row in rows}


def translate(text: str, language: str = "en", **values: Any) -> str:
    """Translate a template caption, substituting only explicitly supplied values."""
    value = terminology(language).get(text, text)
    return value.format(**values) if values else value


def format_number(value: float, language: str = "en", *, decimals: int = 2) -> str:
    """Format a finite number without changing its currency or underlying value."""
    locale_code(language)
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError("Number must be finite")
    if isinstance(decimals, bool) or not 0 <= decimals <= 12:
        raise ValueError("Decimals must be between 0 and 12")
    formatted = f"{value:,.{decimals}f}"
    thousands, decimal = {"ru": ("\u00a0", ","), "de": (".", ","), "es": (".", ",")}.get(language, (",", "."))
    return formatted.replace(",", "\x00").replace(".", decimal).replace("\x00", thousands)


def format_date(value: str | date, language: str = "en") -> str:
    """Format ISO dates/months; machine snapshots retain the original ISO values."""
    locale_code(language)
    text = value.isoformat() if isinstance(value, date) else value
    month_only = len(text) == 7
    parsed = date.fromisoformat(text + "-01" if month_only else text[:10])
    if language == "zh":
        return f"{parsed.year}年{parsed.month}月" + ("" if month_only else f"{parsed.day}日")
    if month_only:
        return (
            f"{parsed.month:02d}.{parsed.year}"
            if language in {"ru", "de"}
            else f"{parsed.month:02d}/{parsed.year}"
        )
    return parsed.strftime({"en": "%m/%d/%Y", "ru": "%d.%m.%Y", "de": "%d.%m.%Y", "es": "%d/%m/%Y"}[language])


def excel_number_format(value: str, language: str = "en") -> str:
    """Attach an Excel LCID while retaining numeric cells and format semantics."""
    locale_code(language)
    if language == "en" or value == "General" or "[$-" in value:
        return value
    return f"[$-{EXCEL_LOCALES[language]}]{value}"


def client_presentation(record: Mapping[str, Any], language: str = "en") -> list[dict[str, Any]]:
    """Return separate localized field/value displays without mutating a registry record."""
    locale_code(language)
    rows = []
    for key, value in record.items():
        display = value
        if key in {"sex", "primary_channel"} and value is not None:
            display = translate(ENUM_CAPTIONS.get(value, value), language)
        if key in {"ips_sent_at", "created_at", "updated_at"} and value:
            display = format_date(value, language)
            if key != "ips_sent_at":
                display += f" {str(value)[11:]}"
        rows.append({"key": key, "label": translate(CLIENT_FIELDS.get(key, key), language), "value": display})
    return rows


def localized_validation_errors(error: ValidationError, language: str = "en") -> list[dict[str, Any]]:
    """Describe validation failures without returning submitted values or exception objects."""
    labels = terminology(language)
    generic = {
        "missing": "Field is required",
        "extra_forbidden": "Unknown field",
        "literal_error": "Select one of the supported values",
        "enum": "Select one of the supported values",
        "greater_than_equal": "Value is below the allowed minimum",
        "less_than_equal": "Value exceeds the allowed maximum",
        "string_pattern_mismatch": "Value does not match the required format",
    }
    rows = []
    for detail in error.errors(include_input=False, include_context=False, include_url=False):
        message = detail["msg"].removeprefix("Value error, ")
        caption = message if message in labels else generic.get(detail["type"], "Invalid value")
        rows.append({"loc": list(detail["loc"]), "type": detail["type"], "msg": translate(caption, language)})
    return rows


def localized_error(error: Exception, language: str = "en") -> str:
    """Localize a boundary error; untranslated diagnostics never expose private input values."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(map(str, row['loc']))}: {row['msg']}"
            for row in localized_validation_errors(error, language)
        )
    text = str(error)
    return translate(
        text if text in terminology(language) else "The operation could not be completed", language
    )
