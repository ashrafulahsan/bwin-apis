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

# Uploads
BYTES_PER_MB = 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"})
ALLOWED_DOCUMENT_EXTENSIONS = frozenset(
    {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}
)
ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".webm", ".mov"})


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
