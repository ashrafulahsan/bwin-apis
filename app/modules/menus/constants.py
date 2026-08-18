"""Constants for the menus module.

A menu item is a link in a navigation tree. Which navigation it belongs to -
the main bar, the footer, a sidebar - is not a column of its own: it is a row
in `categories` from the **Menu Category** taxonomy, exactly as a blog post
draws its category from `blog_category`. One vocabulary, managed in one place,
in a tree the categories module already knows how to nest, rename and retire.

That taxonomy is seeded by migration with a fixed identifier, so the module
works on a fresh database and every environment agrees on which type is which.
"""

import uuid
from typing import Final

MENU_TITLE_MAX_LENGTH = 200
MENU_ICON_MAX_LENGTH = 100
MENU_IMAGE_MAX_LENGTH = 500
MENU_LINK_MAX_LENGTH = 500

#: The category type a menu item's category must come from. Pinned to a known
#: identifier rather than generated, because the value was specified and every
#: environment has to resolve the same taxonomy.
MENU_CATEGORY_TYPE_ID: Final[uuid.UUID] = uuid.UUID(
    "ae340508-652a-414a-b5b9-2daf24a728d8"
)

#: The same row by slug. Code looks the taxonomy up by id first and falls back
#: to this, so a database that re-seeded the row under a fresh id still works.
MENU_CATEGORY_TYPE_SLUG = "menu_category"
MENU_CATEGORY_TYPE_NAME = "Menu Category"

#: How deep a menu may nest, counting the top level as 1. Matches
#: `MAX_CATEGORY_DEPTH`, and for the same reason: deeper reads badly in a
#: navigation bar and costs a query per level to resolve.
MAX_MENU_DEPTH = 5

#: The first `order` given to an item when its siblings are empty. Orders are
#: positive, so nothing sorts above an unnumbered row by accident.
FIRST_MENU_ORDER = 1

#: Columns a free-text search looks at.
MENU_SEARCH_FIELDS = ("title", "description", "link")
