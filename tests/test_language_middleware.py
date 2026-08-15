"""Tests for the language middleware and dependency, over real HTTP."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.constants import Language
from app.core.dependencies import LanguageDep
from app.core.i18n import LanguageMiddleware, get_current_language


@pytest.fixture(scope="module")
def language_client() -> TestClient:
    """An app exposing both ways of reading the language."""
    app = FastAPI()
    app.add_middleware(LanguageMiddleware)

    @app.get("/via-dependency")
    async def _via_dependency(language: LanguageDep) -> dict[str, str]:
        return {"language": language.value}

    @app.get("/via-context")
    async def _via_context() -> dict[str, str]:
        """A router reading the ContextVar the middleware established."""
        return {"language": get_current_language().value}

    return TestClient(app)


# -- Detection ----------------------------------------------------------


@pytest.mark.parametrize("path", ["/via-dependency", "/via-context"])
def test_defaults_to_english(language_client: TestClient, path: str) -> None:
    assert language_client.get(path).json() == {"language": "en"}


@pytest.mark.parametrize("path", ["/via-dependency", "/via-context"])
def test_query_parameter_selects_the_language(
    language_client: TestClient, path: str
) -> None:
    response = language_client.get(path, params={"lang": "bn"})

    assert response.json() == {"language": "bn"}


@pytest.mark.parametrize("path", ["/via-dependency", "/via-context"])
def test_accept_language_header_selects_the_language(
    language_client: TestClient, path: str
) -> None:
    response = language_client.get(path, headers={"Accept-Language": "bn-BD,bn;q=0.9"})

    assert response.json() == {"language": "bn"}


@pytest.mark.parametrize("path", ["/via-dependency", "/via-context"])
def test_query_parameter_overrides_the_header(
    language_client: TestClient, path: str
) -> None:
    response = language_client.get(
        path, params={"lang": "bn"}, headers={"Accept-Language": "en-US,en;q=0.9"}
    )

    assert response.json() == {"language": "bn"}


@pytest.mark.parametrize("path", ["/via-dependency", "/via-context"])
def test_unsupported_language_falls_back_instead_of_failing(
    language_client: TestClient, path: str
) -> None:
    response = language_client.get(path, params={"lang": "fr"})

    assert response.status_code == 200
    assert response.json() == {"language": "en"}


def test_a_malformed_header_does_not_break_the_request(
    language_client: TestClient,
) -> None:
    response = language_client.get(
        "/via-context", headers={"Accept-Language": ";;;q=,,"}
    )

    assert response.status_code == 200
    assert response.json() == {"language": "en"}


# -- Response headers ---------------------------------------------------


def test_content_language_is_advertised(language_client: TestClient) -> None:
    response = language_client.get("/via-context", params={"lang": "bn"})

    assert response.headers["content-language"] == "bn"


def test_responses_vary_on_accept_language(language_client: TestClient) -> None:
    """Shared caches must key on the header, not just the URL."""
    response = language_client.get("/via-context")

    assert "Accept-Language" in response.headers["vary"]


# -- Isolation ----------------------------------------------------------


def test_language_does_not_leak_between_requests(
    language_client: TestClient,
) -> None:
    """The ContextVar is reset once the request finishes."""
    assert language_client.get("/via-context", params={"lang": "bn"}).json() == {
        "language": "bn"
    }
    assert language_client.get("/via-context").json() == {"language": "en"}
    assert get_current_language() is Language.EN


# -- Wired into the real application ------------------------------------


def test_the_live_application_negotiates_from_the_header(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health", headers={"Accept-Language": "bn-BD,bn;q=0.9"}
    )

    assert response.status_code == 200
    assert response.headers["content-language"] == "bn"
    assert response.json()["data"]["language"] == "bn"


def test_the_live_application_honours_the_query_parameter(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health",
        params={"lang": "bn"},
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )

    assert response.json()["data"]["language"] == "bn"
    assert response.headers["content-language"] == "bn"


def test_the_query_parameter_is_documented_in_openapi(client: TestClient) -> None:
    """`?lang=` reaches the schema only because it is declared as a dependency."""
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/api/v1/health"]["get"]["parameters"]

    assert any(parameter["name"] == "lang" for parameter in parameters)
