"""Constants for the translations module."""

import re

#: Translation keys are dot-namespaced: `dashboard.title`, `course.enroll`.
#: Requiring a namespace keeps thousands of UI strings navigable and lets the
#: frontend fetch only the group a screen needs.
TRANSLATION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")

TRANSLATION_KEY_MAX_LENGTH = 255
TRANSLATION_NAMESPACE_MAX_LENGTH = 64

#: Separator between namespace and the rest of the key.
KEY_SEPARATOR = "."

#: Directory holding the seed `<language>.json` files.
LOCALES_DIRNAME = "locales"


def namespace_of(key: str) -> str:
    """First segment of a translation key: `dashboard.title` -> `dashboard`."""
    return key.partition(KEY_SEPARATOR)[0]
