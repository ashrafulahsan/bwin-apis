"""Tests for the declarative Base, naming rules and live connectivity."""

import uuid

import pytest
from sqlalchemy import Column, String, select, text

from app.core.database import (
    NAMING_CONVENTION,
    AsyncSessionFactory,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    check_database_connection,
    engine,
    pluralize,
    to_snake_case,
)


class _Model(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Throwaway model used to assert the Base conventions."""

    __tablename__ = "core_probe_models"

    name = Column(String(50))


@pytest.mark.parametrize(
    ("class_name", "expected"),
    [
        ("User", "user"),
        ("CourseModule", "course_module"),
        ("CMSPage", "cms_page"),
        ("LMSCourseEnrollment", "lms_course_enrollment"),
    ],
)
def test_to_snake_case(class_name: str, expected: str) -> None:
    assert to_snake_case(class_name) == expected


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("user", "users"),
        ("course_module", "course_modules"),
        ("category", "categories"),
        ("gateway", "gateways"),
        ("class", "classes"),
        ("quiz", "quizzes"),
        ("person", "people"),
        ("media_batch", "media_batches"),
    ],
)
def test_pluralize(word: str, expected: str) -> None:
    assert pluralize(word) == expected


def test_tablename_is_generated_as_snake_case_plural() -> None:
    class CourseModule(Base, UUIDPrimaryKeyMixin):
        """Declared without `__tablename__` so Base has to derive it."""

    assert CourseModule.__tablename__ == "course_modules"


def test_metadata_uses_the_naming_convention() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION
    assert Base.metadata.naming_convention["pk"] == "pk_%(table_name)s"


def test_mixins_contribute_their_columns() -> None:
    columns = set(_Model.__table__.columns.keys())

    assert {"id", "created_at", "updated_at", "deleted_at"} <= columns
    assert _Model.__table__.c.id.primary_key
    assert _Model.__table__.c.created_at.server_default is not None
    assert _Model.__table__.c.updated_at.onupdate is not None


def test_uuid_primary_key_defaults_server_side() -> None:
    default = _Model.__table__.c.id.server_default
    assert "gen_random_uuid()" in str(default.arg)


def test_soft_delete_flag_reflects_deleted_at() -> None:
    instance = _Model()
    assert instance.is_deleted is False
    instance.deleted_at = None
    assert instance.is_deleted is False


def test_repr_includes_the_class_name_and_id() -> None:
    instance = _Model()
    instance.id = uuid.UUID("3f7c1a9e-8b21-4d0e-9c55-1a2b3c4d5e6f")

    assert repr(instance) == "<_Model id=3f7c1a9e-8b21-4d0e-9c55-1a2b3c4d5e6f>"


# -- Live database ------------------------------------------------------


@pytest.mark.asyncio
async def test_database_connection_succeeds() -> None:
    assert await check_database_connection() is True


@pytest.mark.asyncio
async def test_session_dependency_executes_queries() -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(select(text("1")))
        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_base_metadata_round_trips_against_postgres() -> None:
    """Create the probe table, insert a row, and confirm the DB filled it in."""
    table = _Model.__table__

    async with engine.begin() as connection:
        await connection.run_sync(table.create, checkfirst=True)

    try:
        async with AsyncSessionFactory() as session:
            instance = _Model(name="probe")
            session.add(instance)
            await session.commit()
            await session.refresh(instance)

            assert isinstance(instance.id, uuid.UUID)
            assert instance.created_at is not None
            assert instance.updated_at is not None
            assert instance.deleted_at is None
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(table.drop, checkfirst=True)
