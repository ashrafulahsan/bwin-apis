"""Tests for the response builders."""

from app.core.constants import ErrorCode
from app.core.dependencies import PaginationParams
from app.shared.schemas.response import (
    ErrorDetail,
    created_response,
    deleted_response,
    error_response,
    paginated_response,
    success_response,
)


def test_success_response_defaults() -> None:
    response = success_response()

    assert response.success is True
    assert response.message == "Operation completed"
    assert response.data is None


def test_success_response_carries_data_and_message() -> None:
    response = success_response({"id": 1}, message="Fetched")

    assert response.data == {"id": 1}
    assert response.message == "Fetched"


def test_created_response() -> None:
    response = created_response({"id": 1})

    assert response.success is True
    assert response.message == "Created successfully"


def test_deleted_response_has_no_payload() -> None:
    response = deleted_response()

    assert response.success is True
    assert response.data is None


def test_error_response_shape() -> None:
    payload = error_response(
        message="Email already registered.",
        error_code=ErrorCode.CONFLICT,
        errors=[ErrorDetail(field="body.email", message="taken", type="conflict")],
    )

    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error_code"] == "CONFLICT"
    assert payload["errors"][0]["field"] == "body.email"


def test_error_response_is_json_ready() -> None:
    """`mode="json"` so the enum serializes to a string, not an Enum member."""
    payload = error_response(error_code=ErrorCode.NOT_FOUND)

    assert isinstance(payload["error_code"], str)


def test_paginated_response_keeps_the_standard_envelope() -> None:
    response = paginated_response(
        items=[{"id": 1}, {"id": 2}],
        total_items=45,
        pagination=PaginationParams(page=2, page_size=20),
        message="Courses fetched",
    )
    body = response.model_dump()

    assert body["success"] is True
    assert body["message"] == "Courses fetched"
    assert body["data"]["items"] == [{"id": 1}, {"id": 2}]
    assert body["data"]["meta"] == {
        "page": 2,
        "page_size": 20,
        "total_items": 45,
        "total_pages": 3,
        "has_next": True,
        "has_previous": True,
    }


def test_paginated_response_with_an_empty_result_set() -> None:
    response = paginated_response(
        items=[], total_items=0, pagination=PaginationParams()
    )

    assert response.data is not None
    assert response.data.items == []
    assert response.data.meta.total_pages == 0
