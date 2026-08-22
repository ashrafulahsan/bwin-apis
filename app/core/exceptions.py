"""Application exception hierarchy and the handlers that render it.

Services raise these instead of `HTTPException`, which keeps HTTP concerns out
of the business layer. The handlers registered here turn every failure - ours,
FastAPI's, and unexpected ones - into the standard error envelope.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.constants import DEFAULT_ERROR_MESSAGE, ErrorCode
from app.shared.schemas.response import ErrorDetail, error_response

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Base class for every expected application failure."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    message: str = DEFAULT_ERROR_MESSAGE

    def __init__(
        self,
        message: str | None = None,
        *,
        error_code: ErrorCode | None = None,
        errors: list[ErrorDetail] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        self.errors = errors
        self.headers = headers
        super().__init__(self.message)


class BadRequestException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = ErrorCode.BAD_REQUEST
    message = "The request could not be processed."


class UnauthorizedException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED
    message = "Authentication credentials are missing or invalid."

    def __init__(self, message: str | None = None, **kwargs: object) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class ForbiddenException(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action."


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.NOT_FOUND
    message = "The requested resource was not found."

    def __init__(
        self, resource: str | None = None, message: str | None = None, **kwargs: object
    ) -> None:
        if message is None and resource is not None:
            message = f"{resource} not found."
        super().__init__(message, **kwargs)  # type: ignore[arg-type]


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = ErrorCode.CONFLICT
    message = "The resource already exists or conflicts with the current state."


class ValidationException(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = ErrorCode.VALIDATION_ERROR
    message = "The submitted data is invalid."


class TooManyRequestsException(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = ErrorCode.RATE_LIMITED
    message = "Too many requests. Please try again later."


class ServiceUnavailableException(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.SERVICE_UNAVAILABLE
    message = "The service is temporarily unavailable."


# -- Handlers -----------------------------------------------------------

_STATUS_TO_ERROR_CODE: dict[int, ErrorCode] = {
    status.HTTP_400_BAD_REQUEST: ErrorCode.BAD_REQUEST,
    status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
    status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
    status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
    status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
    status.HTTP_422_UNPROCESSABLE_CONTENT: ErrorCode.VALIDATION_ERROR,
    status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
    status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.SERVICE_UNAVAILABLE,
}


def _error_code_for(status_code: int) -> ErrorCode:
    """Map an HTTP status onto an error code, defaulting by status class."""
    if status_code in _STATUS_TO_ERROR_CODE:
        return _STATUS_TO_ERROR_CODE[status_code]
    return (
        ErrorCode.BAD_REQUEST if 400 <= status_code < 500 else ErrorCode.INTERNAL_ERROR
    )


def _to_error_details(raw_errors: list[dict[str, object]]) -> list[ErrorDetail]:
    """Flatten Pydantic's error list into the API's `errors` shape."""
    details: list[ErrorDetail] = []
    for error in raw_errors:
        location = [str(part) for part in error.get("loc", ())]
        details.append(
            ErrorDetail(
                field=".".join(location) or None,
                message=str(error.get("msg", DEFAULT_ERROR_MESSAGE)),
                type=str(error["type"]) if error.get("type") else None,
            )
        )
    return details


async def app_exception_handler(_: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            message=exc.message, error_code=exc.error_code, errors=exc.errors
        ),
        headers=exc.headers,
    )


async def http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Render FastAPI's own aborts (404 routing, 405, security guards)."""
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response(
            message=str(exc.detail),
            error_code=_error_code_for(exc.status_code),
        ),
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_response(
            message="Request validation failed.",
            error_code=ErrorCode.VALIDATION_ERROR,
            errors=_to_error_details(exc.errors()),  # type: ignore[arg-type]
        ),
    )


async def pydantic_validation_exception_handler(
    _: Request, exc: ValidationError
) -> JSONResponse:
    """Catch model validation raised outside request parsing (e.g. in services)."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_response(
            message="Data validation failed.",
            error_code=ErrorCode.VALIDATION_ERROR,
            errors=_to_error_details(exc.errors()),  # type: ignore[arg-type]
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort: log the traceback, never leak internals to the client."""
    logger.exception(
        "Unhandled error on %s %s", request.method, request.url.path, exc_info=exc
    )
    message = str(exc) if settings.debug else "An unexpected error occurred."
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response(message=message, error_code=ErrorCode.INTERNAL_ERROR),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire every handler onto the application."""
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)
