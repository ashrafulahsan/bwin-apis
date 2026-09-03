"""Application-wide constants shared across every module."""

from enum import StrEnum

# API
API_V1_PREFIX = "/api/v1"

# Messages
DEFAULT_SUCCESS_MESSAGE = "Operation completed"
DEFAULT_ERROR_MESSAGE = "Something went wrong"

# Pagination
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# Slugs
SLUG_MAX_LENGTH = 255

# Internationalization
LANGUAGE_QUERY_PARAM = "lang"
ACCEPT_LANGUAGE_HEADER = "accept-language"
CONTENT_LANGUAGE_HEADER = "content-language"

# Uploads
BYTES_PER_MB = 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"})
ALLOWED_DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}
)
ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov"})


class StorageBackend(StrEnum):
    """Where uploaded files physically land.

    Both write to the same relative `key` layout, so switching this in
    `.env` is the entire migration - nothing about a `key` (e.g.
    `avatars/<uuid>.png`) changes between them, only how it resolves to a
    URL.
    """

    LOCAL = "local"
    S3 = "s3"


class Language(StrEnum):
    """Languages the platform serves content in."""

    EN = "en"
    BN = "bn"


DEFAULT_LANGUAGE = Language.EN
SUPPORTED_LANGUAGES: frozenset[Language] = frozenset(Language)

#: Endonyms - each language named in itself, for language switchers.
LANGUAGE_NAMES: dict[Language, str] = {
    Language.EN: "English",
    Language.BN: "বাংলা",
}


class Environment(StrEnum):
    """Deployment environments the application can run in."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


class TokenType(StrEnum):
    """JWT token flavours issued by the auth module."""

    ACCESS = "access"
    REFRESH = "refresh"


class SortOrder(StrEnum):
    """Sort direction accepted by list endpoints."""

    ASC = "asc"
    DESC = "desc"


class ErrorCode(StrEnum):
    """Machine readable error identifiers returned to clients."""

    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
