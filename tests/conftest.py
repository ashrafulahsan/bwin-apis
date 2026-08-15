"""Shared pytest fixtures."""

from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import (
    AsyncSessionFactory,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    engine,
)
from app.main import app
from app.shared.repositories.base import BaseRepository


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
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
async def widget_table() -> AsyncIterator[None]:
    """Create the probe table for the session, then drop it."""
    async with engine.begin() as connection:
        await connection.run_sync(Widget.__table__.create, checkfirst=True)

    yield

    async with engine.begin() as connection:
        await connection.run_sync(Widget.__table__.drop, checkfirst=True)


@pytest.fixture
async def session(widget_table: None) -> AsyncIterator[AsyncSession]:
    """A session rolled back after each test, so tests cannot leak rows.

    Repositories only flush, so nothing survives the rollback.
    """
    async with AsyncSessionFactory() as db_session:
        try:
            yield db_session
        finally:
            await db_session.rollback()


@pytest.fixture
def widgets(session: AsyncSession) -> WidgetRepository:
    return WidgetRepository(session)
