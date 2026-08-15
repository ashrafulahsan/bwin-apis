"""Standard API response envelopes used by every endpoint."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.constants import (
    DEFAULT_ERROR_MESSAGE,
    DEFAULT_SUCCESS_MESSAGE,
    ErrorCode,
)

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Uniform success envelope: `{success, message, data}`."""

    success: bool = Field(default=True, description="Whether the request succeeded.")
    message: str = Field(
        default=DEFAULT_SUCCESS_MESSAGE, description="Human readable result message."
    )
    data: T | None = Field(default=None, description="Response payload.")


class ErrorDetail(BaseModel):
    """A single field level problem, used for validation failures."""

    field: str | None = Field(default=None, description="Offending field path.")
    message: str = Field(description="What went wrong with this field.")
    type: str | None = Field(default=None, description="Machine readable error type.")


class ErrorResponse(BaseModel):
    """Uniform failure envelope.

    Keeps the `{success, message, data}` shape and adds `error_code` plus an
    optional `errors` list so clients can map failures onto form fields.
    """

    success: bool = Field(default=False)
    message: str = Field(default=DEFAULT_ERROR_MESSAGE)
    data: None = Field(default=None)
    error_code: ErrorCode = Field(default=ErrorCode.INTERNAL_ERROR)
    errors: list[ErrorDetail] | None = Field(default=None)


def success_response(
    data: T | None = None, message: str = DEFAULT_SUCCESS_MESSAGE
) -> APIResponse[T]:
    """Build a successful `APIResponse` envelope."""
    return APIResponse[T](success=True, message=message, data=data)


def error_response(
    message: str = DEFAULT_ERROR_MESSAGE,
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
    errors: list[ErrorDetail] | None = None,
) -> dict[str, Any]:
    """Build a failure envelope as a JSON-ready dict."""
    return ErrorResponse(
        message=message, error_code=error_code, errors=errors
    ).model_dump(mode="json")
