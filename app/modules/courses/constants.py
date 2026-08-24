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


# --- Course contents -----------------------------------------------------

CONTENT_TITLE_MAX_LENGTH = 255
CONTENT_SLUG_MAX_LENGTH = 255
CONTENT_URL_MAX_LENGTH = 500
CONTENT_FILE_NAME_MAX_LENGTH = 255


class ContentType(StrEnum):
    """What a piece of course content actually is.

    The type decides which of the per-kind column groups on
    `course_contents` carry meaning; the rest stay NULL.
    """

    VIDEO = "video"
    LIVE_CLASS = "live_class"
    DOCUMENT = "document"
    QUIZ = "quiz"


class VideoProvider(StrEnum):
    YOUTUBE = "youtube"
    VIMEO = "vimeo"
    BUNNY = "bunny"
    S3 = "s3"
    SELF_HOSTED = "self_hosted"
    EXTERNAL = "external"


class LiveProvider(StrEnum):
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    MS_TEAMS = "ms_teams"
    JITSI = "jitsi"
    CUSTOM = "custom"


class LiveClassStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    ENDED = "ended"
    CANCELLED = "cancelled"


class DocumentType(StrEnum):
    PDF = "pdf"
    DOC = "doc"
    PPT = "ppt"
    SHEET = "sheet"
    IMAGE = "image"
    OTHER = "other"


class ContentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


COURSE_CONTENT_SEARCH_FIELDS = ("title", "slug", "description")


# --- Reviews -------------------------------------------------------------

REVIEW_TITLE_MAX_LENGTH = 255
REVIEW_NAME_MAX_LENGTH = 150
REVIEW_EMAIL_MAX_LENGTH = 255

REVIEW_MIN_RATING = 1
REVIEW_MAX_RATING = 5


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SPAM = "spam"


class ReviewSource(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    IMPORTED = "imported"
    ADMIN = "admin"


REVIEW_SEARCH_FIELDS = ("title", "comment", "reviewer_name")


# --- Certificate templates -----------------------------------------------

CERTIFICATE_NAME_MAX_LENGTH = 150
CERTIFICATE_CODE_MAX_LENGTH = 100


class CertificateType(StrEnum):
    COMPLETION = "completion"
    PARTICIPATION = "participation"
    ACHIEVEMENT = "achievement"
    EXCELLENCE = "excellence"


class CertificateOrientation(StrEnum):
    LANDSCAPE = "landscape"
    PORTRAIT = "portrait"


class CertificatePageSize(StrEnum):
    A4 = "a4"
    A5 = "a5"
    LETTER = "letter"
    LEGAL = "legal"


class CertificateStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


CERTIFICATE_TEMPLATE_SEARCH_FIELDS = ("name", "code", "description")


# --- Projects ------------------------------------------------------------

PROJECT_TITLE_MAX_LENGTH = 255
PROJECT_SLUG_MAX_LENGTH = 255


class ProjectType(StrEnum):
    INDIVIDUAL = "individual"
    GROUP = "group"
    CAPSTONE = "capstone"
    ASSIGNMENT = "assignment"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


PROJECT_SEARCH_FIELDS = ("title", "slug", "short_description", "description")


# --- Job successes -------------------------------------------------------

JOB_SUCCESS_NAME_MAX_LENGTH = 150
JOB_SUCCESS_TITLE_MAX_LENGTH = 255


class JobType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    FREELANCE = "freelance"
    INTERNSHIP = "internship"


class WorkMode(StrEnum):
    ONSITE = "onsite"
    REMOTE = "remote"
    HYBRID = "hybrid"


class SalaryPeriod(StrEnum):
    HOURLY = "hourly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class JobSuccessStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


JOB_SUCCESS_SEARCH_FIELDS = (
    "student_name",
    "company_name",
    "job_title",
    "story",
)


# --- Course FAQs ---------------------------------------------------------

FAQ_QUESTION_MAX_LENGTH = 500
FAQ_GROUP_MAX_LENGTH = 100


class FaqStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


COURSE_FAQ_SEARCH_FIELDS = ("question", "answer", "faq_group")
