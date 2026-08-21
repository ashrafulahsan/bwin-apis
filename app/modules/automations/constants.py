"""Constants and lifecycle values for automations.

An automation is a publishable catalogue entry describing an automated
service or workflow. It carries the same search metadata a course or a page
does, from the same shared mixin, so a client rendering `<head>` reads the
same field names whichever it is rendering.

Publication works the way it does for courses and pages: `status` is a
transition with its own permission rather than a field an author can set,
which is what makes the Editor role mean anything.
"""

from enum import StrEnum

AUTOMATION_TITLE_MAX_LENGTH = 255
AUTOMATION_SLUG_MAX_LENGTH = 255
AUTOMATION_IMAGE_URL_MAX_LENGTH = 500


class AutomationStatus(StrEnum):
    """Where an automation is in its life.

    `DRAFT` is being written and is not public. `PUBLISHED` is live, or
    scheduled - a published automation whose `published_at` is still in the
    future is not served as live until that moment passes. `ARCHIVED` was
    live once and has been retired, which is not the same as deleted: its URL
    still has to resolve for anyone holding a link.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


DEFAULT_AUTOMATION_STATUS = AutomationStatus.DRAFT

#: Columns a free-text search looks at. `lists` is deliberately absent: it is
#: JSON, and a `LIKE` across it would scan the whole table to answer a
#: question nobody asks of it.
AUTOMATION_SEARCH_FIELDS = (
    "title",
    "slug",
    "description",
)
