"""Constants for the categories module.

Categories are organised in two levels of structure. A **category type** names
a taxonomy - "Blog Topics", "Course Subjects", "Support Topics" - and the
**categories** inside it form a tree. Keeping the taxonomy in its own table
means a new one is a row rather than a migration, and stops unrelated
vocabularies sharing a namespace.
"""

from enum import StrEnum

CATEGORY_NAME_MAX_LENGTH = 150
CATEGORY_SLUG_MAX_LENGTH = 180

#: How deep a category tree may go, counting the root as level 1. Deep trees
#: read badly in a navigation menu and cost a query per level to resolve, and
#: no real taxonomy on this platform needs more.
MAX_CATEGORY_DEPTH = 5


class CategoryStatus(StrEnum):
    """Whether a category is offered for use.

    Inactive is not deletion: a category that is no longer being assigned to
    new content still has to name the content already filed under it.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


DEFAULT_CATEGORY_STATUS = CategoryStatus.ACTIVE
