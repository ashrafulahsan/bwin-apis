"""Application-wide constants shared across every module."""

from enum import StrEnum

API_V1_PREFIX = "/api/v1"

DEFAULT_SUCCESS_MESSAGE = "Operation completed"


class Environment(StrEnum):
    """Deployment environments the application can run in."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"
