"""Language negotiation helpers.

Pure functions with no FastAPI imports, so they can be reused from background
jobs, CLI tooling and tests. The framework wiring lives in `app.core.i18n`.

Nothing here raises on bad input: an unrecognised language tag falls back to
the default rather than failing the request. A malformed `Accept-Language`
header sent by some proxy must never turn a working page into an error.
"""

from collections.abc import Mapping
from typing import TypeVar

from app.core.constants import (
    DEFAULT_LANGUAGE,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGES,
    Language,
)

T = TypeVar("T")

#: RFC 9110: a request with no explicit quality is the most preferred.
_DEFAULT_QUALITY = 1.0

#: `Accept-Language: *` means "anything you like".
_WILDCARD = "*"


def normalize_language(value: str | None) -> Language | None:
    """Reduce a language tag to a supported `Language`, or `None`.

    Region subtags are dropped, so `bn-BD`, `bn_BD` and `BN` all resolve to
    `Language.BN`.
    """
    if not value:
        return None

    primary = value.strip().lower().replace("_", "-").partition("-")[0]

    try:
        return Language(primary)
    except ValueError:
        return None


def is_supported(value: str | None) -> bool:
    """Whether a language tag maps onto a language the platform serves."""
    return normalize_language(value) is not None


def parse_accept_language(header: str | None) -> list[tuple[str, float]]:
    """Parse an `Accept-Language` header into `(tag, quality)` pairs.

    Sorted by quality, highest first, with the original order preserved among
    equal qualities. Entries with `q=0` are dropped - that is the client
    explicitly refusing a language. Unparseable entries are skipped.

        >>> parse_accept_language("bn-BD,bn;q=0.9,en;q=0.8")
        [('bn-bd', 1.0), ('bn', 0.9), ('en', 0.8)]
    """
    if not header:
        return []

    entries: list[tuple[str, float, int]] = []

    for position, raw_entry in enumerate(header.split(",")):
        entry = raw_entry.strip()
        if not entry:
            continue

        tag, _, parameters = entry.partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue

        quality = _parse_quality(parameters)
        if quality <= 0:
            continue

        entries.append((tag, quality, position))

    # Negate quality so higher comes first, keeping position as the tiebreaker.
    entries.sort(key=lambda entry: (-entry[1], entry[2]))

    return [(tag, quality) for tag, quality, _ in entries]


def _parse_quality(parameters: str) -> float:
    """Read the `q=` parameter, treating anything unparseable as absent."""
    for parameter in parameters.split(";"):
        key, _, value = parameter.partition("=")
        if key.strip().lower() != "q":
            continue
        try:
            return min(max(float(value.strip()), 0.0), 1.0)
        except ValueError:
            return _DEFAULT_QUALITY

    return _DEFAULT_QUALITY


def negotiate_language(
    accept_language: str | None, *, default: Language = DEFAULT_LANGUAGE
) -> Language:
    """Pick the best supported language from an `Accept-Language` header."""
    for tag, _ in parse_accept_language(accept_language):
        if tag == _WILDCARD:
            return default

        language = normalize_language(tag)
        if language is not None:
            return language

    return default


def resolve_language(
    *,
    requested: str | None = None,
    accept_language: str | None = None,
    default: Language = DEFAULT_LANGUAGE,
) -> Language:
    """Resolve the language for a request.

    Precedence is `?lang=` first, then `Accept-Language`, then the default.
    The query parameter wins because it is a deliberate choice - a reader who
    clicks "বাংলা" should get Bengali even though their browser still sends
    `Accept-Language: en`.
    """
    explicit = normalize_language(requested)
    if explicit is not None:
        return explicit

    return negotiate_language(accept_language, default=default)


def language_display_name(language: Language) -> str:
    """The language's own name, for building a language switcher."""
    return LANGUAGE_NAMES.get(language, language.value)


def supported_languages() -> list[Language]:
    """Supported languages, default first, then alphabetical."""
    others = sorted(SUPPORTED_LANGUAGES - {DEFAULT_LANGUAGE})
    return [DEFAULT_LANGUAGE, *others]


def pick_translation(
    translations: Mapping[str, T] | None,
    language: Language,
    *,
    fallback: Language | None = DEFAULT_LANGUAGE,
) -> T | None:
    """Choose a value from a `{"en": ..., "bn": ...}` mapping.

    Falls back to `fallback`, then to any available translation, so a partly
    translated record still renders something rather than a blank field.
    """
    if not translations:
        return None

    for key in (language, fallback):
        if key is None:
            continue
        value = translations.get(key.value)
        if value is not None:
            return value

    return next(iter(translations.values()), None)


def localized_field_name(field: str, language: Language) -> str:
    """Column name for models storing translations in suffixed columns.

    >>> localized_field_name("title", Language.BN)
    'title_bn'
    """
    return f"{field}_{language.value}"
