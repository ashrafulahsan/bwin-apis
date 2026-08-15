"""URL slug generation for CMS pages, courses and other addressable content."""

import re
import secrets
import unicodedata
from collections.abc import Awaitable, Callable, Iterator
from itertools import islice

from app.core.constants import SLUG_MAX_LENGTH

# Characters that NFKD normalization does not decompose into ASCII.
_TRANSLITERATIONS = {
    "ß": "ss",
    "æ": "ae",
    "œ": "oe",
    "ø": "o",
    "å": "aa",
    "đ": "d",
    "ð": "d",
    "þ": "th",
    "ł": "l",
    "ı": "i",
    "№": "no",
    "&": " and ",
    "@": " at ",
}

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

# Dropped outright rather than turned into a separator, so "CEO's Guide"
# slugifies to `ceos-guide` instead of `ceo-s-guide`.
_ELIDED = re.compile(r"['‘’ʼ`]")


def slugify(
    value: str,
    *,
    separator: str = "-",
    max_length: int | None = SLUG_MAX_LENGTH,
) -> str:
    """Convert arbitrary text into a lowercase, URL-safe slug.

    Returns an empty string when nothing survives - a title made only of
    emoji, for example. Callers that need a guaranteed slug should use
    `generate_unique_slug`, which falls back to a random token.

        >>> slugify("Café & Bar: São Paulo!")
        'cafe-and-bar-sao-paulo'
    """
    lowered = _ELIDED.sub("", value.strip().lower())

    for source, replacement in _TRANSLITERATIONS.items():
        lowered = lowered.replace(source, replacement)

    # NFKD splits accented characters into base + combining mark, and the
    # ASCII encode then drops the marks.
    ascii_only = (
        unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")
    )

    slug = _NON_ALPHANUMERIC.sub(separator, ascii_only).strip(separator)

    if max_length is not None and len(slug) > max_length:
        slug = _truncate(slug, max_length, separator)

    return slug


def _truncate(slug: str, max_length: int, separator: str) -> str:
    """Cut to `max_length`, preferring a word boundary over a mid-word chop."""
    clipped = slug[:max_length]
    head, found, _ = clipped.rpartition(separator)

    # Only honour the boundary if it keeps a reasonable amount of the slug.
    if found and len(head) >= max_length // 2:
        clipped = head

    return clipped.strip(separator)


def slug_candidates(
    base: str,
    *,
    separator: str = "-",
    max_length: int | None = SLUG_MAX_LENGTH,
    start: int = 2,
) -> Iterator[str]:
    """Yield `base`, `base-2`, `base-3`, ... indefinitely.

    Each candidate respects `max_length`, trimming the stem rather than the
    numeric suffix so the result stays unique.
    """
    yield base

    counter = start
    while True:
        suffix = f"{separator}{counter}"
        if max_length is None:
            yield f"{base}{suffix}"
        else:
            stem = base[: max_length - len(suffix)].strip(separator)
            yield f"{stem}{suffix}"
        counter += 1


async def generate_unique_slug(
    value: str,
    exists: Callable[[str], Awaitable[bool]],
    *,
    separator: str = "-",
    max_length: int | None = SLUG_MAX_LENGTH,
    max_attempts: int = 100,
) -> str:
    """Slugify `value` and suffix it until `exists` reports the slug is free.

    `exists` is the repository lookup, e.g. `repository.slug_exists`. After
    `max_attempts` collisions it appends a random token rather than looping
    forever against a hot table.
    """
    base = slugify(value, separator=separator, max_length=max_length) or _random_token()

    candidates = slug_candidates(
        base, separator=separator, max_length=max_length, start=2
    )
    for candidate in islice(candidates, max_attempts):
        if not await exists(candidate):
            return candidate

    return _with_random_suffix(base, separator=separator, max_length=max_length)


def _random_token(length: int = 8) -> str:
    return secrets.token_hex(length // 2)


def _with_random_suffix(
    base: str, *, separator: str, max_length: int | None, token_length: int = 8
) -> str:
    suffix = f"{separator}{_random_token(token_length)}"
    if max_length is None:
        return f"{base}{suffix}"
    stem = base[: max_length - len(suffix)].strip(separator)
    return f"{stem}{suffix}"
