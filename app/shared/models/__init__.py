"""Model mixins shared by more than one feature module.

Nothing here maps a table of its own - these are column sets that several
modules carry identically, kept in one place so they cannot drift apart.
"""

from app.shared.models.seo import (
    DEFAULT_META_ROBOTS,
    ROBOTS_DIRECTIVES,
    SEOFieldsMixin,
)

__all__ = [
    "DEFAULT_META_ROBOTS",
    "ROBOTS_DIRECTIVES",
    "SEOFieldsMixin",
]
