"""Application settings loaded from the environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import API_V1_PREFIX, Environment


class Settings(BaseSettings):
    """Environment driven configuration.

    Values are read from the process environment first and fall back to the
    `.env` file, so containers can override anything without a rebuild.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    project_name: str = "BWIN Consultants API"
    description: str = "CMS + LMS platform backend for BWIN Consultants."
    version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = True

    # API
    api_v1_prefix: str = API_V1_PREFIX

    # CORS - provide as a JSON array in `.env`
    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def docs_url(self) -> str | None:
        """Swagger UI is disabled in production."""
        return None if self.is_production else "/docs"

    @property
    def redoc_url(self) -> str | None:
        return None if self.is_production else "/redoc"

    @property
    def openapi_url(self) -> str | None:
        return None if self.is_production else "/openapi.json"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, usable as a FastAPI dependency."""
    return Settings()


settings = get_settings()
