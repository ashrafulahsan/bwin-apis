"""Standard API response envelope used by every endpoint."""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.core.constants import DEFAULT_SUCCESS_MESSAGE

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Uniform response shape: `{success, message, data}`."""

    success: bool = Field(default=True, description="Whether the request succeeded.")
    message: str = Field(
        default=DEFAULT_SUCCESS_MESSAGE, description="Human readable result message."
    )
    data: T | None = Field(default=None, description="Response payload.")


def success_response(
    data: T | None = None, message: str = DEFAULT_SUCCESS_MESSAGE
) -> APIResponse[T]:
    """Build a successful `APIResponse` envelope."""
    return APIResponse[T](success=True, message=message, data=data)
