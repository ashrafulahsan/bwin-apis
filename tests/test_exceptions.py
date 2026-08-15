"""Tests proving every failure path renders the standard error envelope."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.constants import ErrorCode
from app.core.dependencies import PaginationDep
from app.core.exceptions import (
    ConflictException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
    register_exception_handlers,
)


class _Payload(BaseModel):
    name: str
    age: int


@pytest.fixture(scope="module")
def error_client() -> TestClient:
    """A throwaway app exposing one route per failure mode."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    async def _not_found() -> None:
        raise NotFoundException("User")

    @app.get("/conflict")
    async def _conflict() -> None:
        raise ConflictException("Email already registered.")

    @app.get("/unauthorized")
    async def _unauthorized() -> None:
        raise UnauthorizedException()

    @app.get("/forbidden")
    async def _forbidden() -> None:
        raise ForbiddenException()

    @app.post("/validate")
    async def _validate(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    @app.get("/paginated")
    async def _paginated(pagination: PaginationDep) -> dict[str, int]:
        return {"offset": pagination.offset, "limit": pagination.limit}

    return TestClient(app, raise_server_exceptions=False)


def test_not_found_uses_the_error_envelope(error_client: TestClient) -> None:
    response = error_client.get("/not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["message"] == "User not found."
    assert body["error_code"] == ErrorCode.NOT_FOUND


def test_conflict_carries_a_custom_message(error_client: TestClient) -> None:
    response = error_client.get("/conflict")

    assert response.status_code == 409
    assert response.json()["message"] == "Email already registered."
    assert response.json()["error_code"] == ErrorCode.CONFLICT


def test_unauthorized_sets_the_www_authenticate_header(
    error_client: TestClient,
) -> None:
    response = error_client.get("/unauthorized")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_forbidden_maps_to_403(error_client: TestClient) -> None:
    assert error_client.get("/forbidden").status_code == 403


def test_validation_errors_are_flattened_per_field(error_client: TestClient) -> None:
    response = error_client.post("/validate", json={"age": "not-a-number"})

    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == ErrorCode.VALIDATION_ERROR
    fields = {error["field"] for error in body["errors"]}
    assert fields == {"body.name", "body.age"}


def test_unknown_route_uses_the_error_envelope(error_client: TestClient) -> None:
    body = error_client.get("/nope").json()

    assert body["success"] is False
    assert body["error_code"] == ErrorCode.NOT_FOUND


def test_wrong_method_maps_to_method_not_allowed(error_client: TestClient) -> None:
    response = error_client.post("/not-found")

    assert response.status_code == 405
    assert response.json()["error_code"] == ErrorCode.METHOD_NOT_ALLOWED


def test_pagination_dependency_computes_offset(error_client: TestClient) -> None:
    response = error_client.get("/paginated", params={"page": 3, "page_size": 25})

    assert response.json() == {"offset": 50, "limit": 25}


def test_pagination_rejects_an_oversized_page(error_client: TestClient) -> None:
    response = error_client.get("/paginated", params={"page_size": 5000})

    assert response.status_code == 422
    assert response.json()["error_code"] == ErrorCode.VALIDATION_ERROR
