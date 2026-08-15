"""Centralized application settings loaded from the environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constants import (
    API_V1_PREFIX,
    BYTES_PER_MB,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    Environment,
)

BASE_DIR = Path(__file__).resolve().parents[2]

# Placeholder used for local development only; refused in production.
DEV_SECRET_KEY = "change-me-in-production"


class Settings(BaseSettings):
    """Environment driven configuration.

    Values are read from the process environment first and fall back to the
    `.env` file, so containers can override anything without a rebuild.
    Secrets are wrapped in `SecretStr` to keep them out of logs and tracebacks.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ----------------------------------------------------
    project_name: str = "BWIN Consultants API"
    description: str = "CMS + LMS platform backend for BWIN Consultants."
    version: str = "0.1.0"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = True

    # -- API ------------------------------------------------------------
    api_v1_prefix: str = API_V1_PREFIX

    # -- Server ---------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # -- Security -------------------------------------------------------
    secret_key: SecretStr = SecretStr(DEV_SECRET_KEY)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    password_min_length: int = 8

    # -- Database -------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: SecretStr = SecretStr("postgres")
    postgres_db: str = "bwin_db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    # -- Redis ----------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr | None = None
    cache_ttl_seconds: int = 300

    # -- CORS - provide as a JSON array in `.env` -----------------------
    cors_origins: list[str] = ["http://localhost:3000"]

    # -- Pagination -----------------------------------------------------
    default_page_size: int = DEFAULT_PAGE_SIZE
    max_page_size: int = MAX_PAGE_SIZE

    # -- Storage --------------------------------------------------------
    upload_dir: Path = BASE_DIR / "app" / "storage" / "uploads"
    export_dir: Path = BASE_DIR / "app" / "storage" / "exports"
    max_upload_size_mb: int = 10

    # -- Logging --------------------------------------------------------
    log_level: str = "INFO"

    # -- Derived values -------------------------------------------------
    # Plain properties rather than computed fields, so credentials never
    # land in `model_dump()` output.

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def is_testing(self) -> bool:
        return self.environment is Environment.TESTING

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN used by the application."""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Blocking DSN used by Alembic migrations."""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        credentials = (
            f":{self.redis_password.get_secret_value()}@" if self.redis_password else ""
        )
        return (
            f"redis://{credentials}{self.redis_host}:{self.redis_port}/{self.redis_db}"
        )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * BYTES_PER_MB

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

    # -- Validation and setup -------------------------------------------

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> "Settings":
        """Fail fast rather than boot production with development defaults."""
        if not self.is_production:
            return self

        if self.secret_key.get_secret_value() == DEV_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set to a unique value in production.")
        if self.debug:
            raise ValueError("DEBUG must be disabled in production.")

        return self

    def ensure_storage_dirs(self) -> None:
        """Create the upload and export directories if they are missing."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, usable as a FastAPI dependency."""
    return Settings()


settings = get_settings()
