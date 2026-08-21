"""Constants and lifecycle values for courses."""

from enum import StrEnum

COURSE_CODE_MAX_LENGTH = 100
COURSE_TITLE_MAX_LENGTH = 255
COURSE_SLUG_MAX_LENGTH = 255
COURSE_DESCRIPTION_MAX_LENGTH = 1000
COURSE_IMAGE_URL_MAX_LENGTH = 500
COURSE_CURRENCY_MAX_LENGTH = 3


class CourseLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class CourseLanguage(StrEnum):
    ENGLISH = "english"
    BANGLA = "bangla"


class CourseStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class CourseVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


COURSE_SEARCH_FIELDS = (
    "course_code",
    "title",
    "slug",
    "short_description",
    "description",
)
