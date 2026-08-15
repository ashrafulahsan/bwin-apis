"""Loading translations from JSON locale files.

Seed strings live in `locales/<language>.json` so they can be reviewed in a
pull request, then imported into the database. Files may be nested or flat;
both forms produce the same dot-namespaced keys:

    {"dashboard": {"title": "Dashboard"}}   ->  {"dashboard.title": "Dashboard"}
    {"dashboard.title": "Dashboard"}        ->  {"dashboard.title": "Dashboard"}
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.core.constants import Language
from app.modules.translations.constants import KEY_SEPARATOR, LOCALES_DIRNAME

LOCALES_DIR = Path(__file__).resolve().parent / LOCALES_DIRNAME


def flatten_translations(
    data: Mapping[str, Any], *, prefix: str = ""
) -> dict[str, str]:
    """Flatten nested translation JSON into dot-separated keys.

    Non-string leaves (numbers, booleans) are coerced to text, so a locale
    file written with `"count": 5` still loads instead of failing.
    """
    flattened: dict[str, str] = {}

    for key, value in data.items():
        path = f"{prefix}{KEY_SEPARATOR}{key}" if prefix else str(key)

        if isinstance(value, Mapping):
            flattened.update(flatten_translations(value, prefix=path))
        elif value is None:
            continue
        else:
            flattened[path] = str(value)

    return flattened


def load_locale_file(path: Path) -> dict[str, str]:
    """Read one locale file into a flat `{key: value}` map."""
    if not path.is_file():
        raise FileNotFoundError(f"Locale file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, Mapping):
        raise ValueError(f"{path.name} must contain a JSON object.")

    return flatten_translations(data)


def locale_path(language: Language, *, directory: Path | None = None) -> Path:
    return (directory or LOCALES_DIR) / f"{language.value}.json"


def load_language(
    language: Language, *, directory: Path | None = None
) -> dict[str, str]:
    """Read the locale file for one language."""
    return load_locale_file(locale_path(language, directory=directory))


def load_all_locales(
    *, directory: Path | None = None
) -> dict[Language, dict[str, str]]:
    """Read every locale file that exists, skipping languages without one."""
    source = directory or LOCALES_DIR
    bundles: dict[Language, dict[str, str]] = {}

    for language in Language:
        path = locale_path(language, directory=source)
        if path.is_file():
            bundles[language] = load_locale_file(path)

    return bundles
