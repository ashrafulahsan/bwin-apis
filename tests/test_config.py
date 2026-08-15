"""Tests for centralized configuration."""

import pytest
from pydantic import SecretStr

from app.core.config import (
    DEV_SECRET_KEY,
    MIN_SECRET_KEY_BYTES,
    Settings,
    get_settings,
)
from app.core.constants import Environment

#: Long enough to satisfy the HS256 key length rule, so tests about other
#: production checks are not tripped up by this one.
PRODUCTION_SECRET = "a-real-production-secret-of-sufficient-length"


def _build(**overrides: object) -> Settings:
    """Build settings from explicit values, ignoring any local `.env`."""
    defaults: dict[str, object] = {
        "_env_file": None,
        "environment": Environment.DEVELOPMENT,
        "debug": True,
    }
    return Settings(**{**defaults, **overrides})  # type: ignore[arg-type]


def test_settings_are_cached() -> None:
    assert get_settings() is get_settings()


def test_database_urls_are_assembled_from_parts() -> None:
    settings = _build(
        postgres_user="bwin",
        postgres_password=SecretStr("s3cret"),
        postgres_host="db",
        postgres_port=5433,
        postgres_db="bwin_db",
    )

    assert settings.database_url == "postgresql+asyncpg://bwin:s3cret@db:5433/bwin_db"
    assert settings.sync_database_url.startswith("postgresql+psycopg://")


def test_redis_url_includes_password_only_when_set() -> None:
    assert _build().redis_url == "redis://localhost:6379/0"
    assert (
        _build(redis_password=SecretStr("pw")).redis_url
        == "redis://:pw@localhost:6379/0"
    )


def test_secrets_are_not_exposed_in_model_dump() -> None:
    dumped = str(_build(postgres_password=SecretStr("s3cret")).model_dump())

    assert "s3cret" not in dumped


def test_docs_are_disabled_in_production() -> None:
    settings = _build(
        environment=Environment.PRODUCTION,
        debug=False,
        secret_key=SecretStr(PRODUCTION_SECRET),
    )

    assert settings.is_production
    assert settings.docs_url is None
    assert settings.openapi_url is None


def test_production_rejects_the_default_secret_key() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY"):
        _build(
            environment=Environment.PRODUCTION,
            debug=False,
            secret_key=SecretStr(DEV_SECRET_KEY),
        )


def test_production_rejects_a_short_secret_key() -> None:
    """A short HMAC key weakens every token, and PyJWT only warns about it."""
    with pytest.raises(ValueError, match="at least"):
        _build(
            environment=Environment.PRODUCTION,
            debug=False,
            secret_key=SecretStr("x" * (MIN_SECRET_KEY_BYTES - 1)),
        )


def test_the_development_key_is_long_enough_to_sign_with() -> None:
    """Short enough to be obviously fake, long enough not to warn on boot."""
    assert len(DEV_SECRET_KEY.encode("utf-8")) >= MIN_SECRET_KEY_BYTES


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValueError, match="DEBUG"):
        _build(
            environment=Environment.PRODUCTION,
            debug=True,
            secret_key=SecretStr(PRODUCTION_SECRET),
        )


def test_max_upload_size_converts_to_bytes() -> None:
    assert _build(max_upload_size_mb=10).max_upload_size_bytes == 10 * 1024 * 1024
