"""Constants for the master CRUD module.

The module is a small dynamic-content system. A **master CRUD field** defines
one input - "Phone number", a number, required - and belongs to a category. A
**master CRUD** is one record filed under a category, and its **field values**
answer that category's fields. Adding a question to a form is therefore a row
rather than a migration, which is the whole point of the arrangement.

The category is what ties the three together: a record may only carry values
for fields defined on its own category. A foreign key can name a table but
never a subset of one, so the service enforces that on every write.
"""

from enum import StrEnum

MASTER_CRUD_TITLE_MAX_LENGTH = 200
MASTER_CRUD_SLUG_MAX_LENGTH = 255
MASTER_CRUD_LINK_MAX_LENGTH = 500
MASTER_CRUD_FIELD_NAME_MAX_LENGTH = 150

#: Past this a value stops being a form answer and becomes a document.
MASTER_CRUD_VALUE_MAX_LENGTH = 5000

#: The first `order` given to a record when its category holds none yet.
FIRST_MASTER_CRUD_ORDER = 1


class MasterCrudStatus(StrEnum):
    """Whether a record or a field is in use.

    Inactive is not deletion: a field that is no longer asked of new records
    still has to name the values already stored under it, and an inactive
    record still exists for whoever holds a link to it.
    """

    ACTIVE = "active"
    INACTIVE = "inactive"


class FieldType(StrEnum):
    """What kind of input a field is, and how its value is validated.

    The set is deliberately small and closed. A free-text `field_type` would
    let "number" arrive spelled four ways and make every validation and every
    front-end switch statement guess.
    """

    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    EMAIL = "email"
    URL = "url"
    #: Choice inputs. The options themselves are not stored - the front end
    #: owns them - so a value is validated as ordinary text.
    RADIO = "radio"
    CHECKBOX = "checkbox"
    SELECT = "select"


DEFAULT_MASTER_CRUD_STATUS = MasterCrudStatus.ACTIVE
DEFAULT_FIELD_TYPE = FieldType.TEXT

#: Columns a free-text search looks at.
MASTER_CRUD_SEARCH_FIELDS = ("title", "slug", "description", "link")
MASTER_CRUD_FIELD_SEARCH_FIELDS = ("field_name",)

#: Accepted spellings of a boolean value, lowercased before comparison. Stored
#: normalized to "true"/"false", so a reader never has to know which was sent.
TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
FALSE_VALUES = frozenset({"false", "0", "no", "off"})
