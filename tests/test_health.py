"""Smoke tests proving the application boots and serves v1 routes."""

from fastapi.testclient import TestClient

from app.core.config import settings


def test_health_check_returns_standard_envelope(client: TestClient) -> None:
    response = client.get(f"{settings.api_v1_prefix}/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["message"] == "Service is healthy"
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == settings.version
    assert body["data"]["language"] == "en"


def test_openapi_schema_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert f"{settings.api_v1_prefix}/health" in response.json()["paths"]


def test_docs_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
