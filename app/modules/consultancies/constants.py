"""Constants and enums for consultancies."""

from enum import StrEnum

CONSULTANCY_CODE_MAX_LENGTH = 100
CONSULTANCY_TITLE_MAX_LENGTH = 255
CONSULTANCY_SLUG_MAX_LENGTH = 255
CONSULTANCY_IMAGE_URL_MAX_LENGTH = 500


class ConsultancyType(StrEnum):
    GENERAL = "general"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    ACADEMIC = "academic"
    NON_PROFIT = "non_profit"


class ConsultancyStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


CONSULTANCY_SEARCH_FIELDS = (
    "consultancy_code",
    "title",
    "slug",
    "description",
)
