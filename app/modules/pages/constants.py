"""Constants for the pages module.

A page is standalone content with its own address - "About us", "Privacy
policy", a landing page. It carries the same search metadata a blog post does,
from the same shared mixin, so the two cannot drift apart and a client
rendering `<head>` reads the same field names whichever it is rendering.

Publication works the way it does for posts: `status` is a transition with its
own permission rather than a field an author can set, which is what makes the
Editor role mean anything.
"""

from enum import StrEnum

PAGE_TITLE_MAX_LENGTH = 200
PAGE_SLUG_MAX_LENGTH = 255
PAGE_DESCRIPTION_MAX_LENGTH = 500
PAGE_IMAGE_URL_MAX_LENGTH = 500
PAGE_IMAGE_ALT_MAX_LENGTH = 255


class PageStatus(StrEnum):
    """Where a page is in its life.

    `DRAFT` is being written and is not public. `PUBLISHED` is live, or
    scheduled - a published page whose `published_at` is still in the future
    is not served as live until that moment passes. `ARCHIVED` was live once
    and has been retired, which is not the same as deleted: its URL still has
    to resolve for anyone holding a link.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


DEFAULT_PAGE_STATUS = PageStatus.DRAFT

#: Columns a free-text search looks at. The body is included deliberately -
#: "which page mentions the refund window?" is the question an editor actually
#: has, and a title-only search cannot answer it.
PAGE_SEARCH_FIELDS = ("title", "slug", "description", "content")
