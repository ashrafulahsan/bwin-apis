"""Shared pytest fixtures.

Tests run against a dedicated `bwindb_test` database, created automatically.
This is not optional tidiness: services commit for real, and several fixtures
truncate tables, so pointing the suite at the development database destroys
its seeded roles and translations.

Override the name with `TEST_POSTGRES_DB` if it collides with anything.
"""

import os

# Must run before any `app` import: settings are read once, at import time,
# and the engine binds to whatever the database name is then.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "bwindb_test")
os.environ["ENVIRONMENT"] = "testing"

from collections.abc import AsyncIterator, Iterator  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Boolean, Integer, String  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from sqlalchemy.orm import Mapped, mapped_column  # noqa: E402

from app.core.config import BASE_DIR, settings  # noqa: E402
from app.core.database import (  # noqa: E402
    AsyncSessionFactory,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    engine,
)
from app.main import app  # noqa: E402
from app.shared.repositories.base import BaseRepository  # noqa: E402


def _ensure_test_database() -> None:
    """Create the test database if it is not there yet."""
    dsn = (
        f"postgresql://{settings.postgres_user}"
        f":{settings.postgres_password.get_secret_value()}"
        f"@{settings.postgres_host}:{settings.postgres_port}/postgres"
    )

    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_db,)
        ).fetchone()

        if not exists:
            connection.execute(f'CREATE DATABASE "{settings.postgres_db}"')


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Bring the test database up to the latest migration.

    Running the real migrations rather than `create_all` means the suite
    exercises what production will actually apply.
    """
    assert (
        settings.postgres_db != "bwindb"
    ), "Refusing to run the suite against the development database."

    _ensure_test_database()
    command.upgrade(Config(str(BASE_DIR / "alembic.ini")), "head")


@pytest.fixture(scope="session")
def client(database: None) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class Widget(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Model that exists only to exercise the generic repository."""

    __tablename__ = "test_widgets"

    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50))
    price: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class WidgetRepository(BaseRepository[Widget]):
    model = Widget


@pytest.fixture(scope="session")
async def widget_table(database: None) -> AsyncIterator[None]:
    """Create the probe table for the session, then drop it."""
    async with engine.begin() as connection:
        await connection.run_sync(Widget.__table__.create, checkfirst=True)

    yield

    async with engine.begin() as connection:
        await connection.run_sync(Widget.__table__.drop, checkfirst=True)


@pytest.fixture
async def session(widget_table: None) -> AsyncIterator[AsyncSession]:
    """A session rolled back after each test.

    Repository-only tests leave nothing behind. Service tests commit, so they
    clean up their own tables - see the fixtures in those modules.
    """
    async with AsyncSessionFactory() as db_session:
        try:
            yield db_session
        finally:
            await db_session.rollback()


@pytest.fixture
def widgets(session: AsyncSession) -> WidgetRepository:
    return WidgetRepository(session)
