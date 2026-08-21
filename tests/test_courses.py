"""Tests for the courses module."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import PaginationParams
from app.core.exceptions import ConflictException
from app.modules.activity_logs.models.activity_log import ActivityLog, ActivityModule
from app.modules.courses.constants import CourseStatus
from app.modules.courses.models.course import Course
from app.modules.courses.schemas.course import CourseCreate, CourseUpdate
from app.modules.courses.services.course import CourseService
from app.modules.users.models.user import User


@pytest.fixture
async def courses(session: AsyncSession) -> AsyncIterator[CourseService]:
    await session.execute(delete(Course))
    await session.execute(delete(User))
    await session.commit()

    user = User(email="course-owner@example.com", first_name="Course Owner")
    session.add(user)
    await session.flush()
    yield CourseService(session)

    await session.execute(delete(Course))
    await session.execute(delete(User))
    await session.commit()


def course_payload(code: str = "PY-101") -> CourseCreate:
    return CourseCreate(
        course_code=code,
        title="Python Foundations",
        description="Learn the foundations of Python.",
        learning_outcomes=["Write Python programs"],
        price="99.00",
    )


async def test_course_lifecycle(courses: CourseService) -> None:
    owner = await courses.users.get_by_email("course-owner@example.com")
    created = await courses.create(course_payload(), actor_id=owner.id)

    assert created.status == CourseStatus.DRAFT
    assert created.slug == "python-foundations"

    activity = (
        await courses.session.execute(
            select(ActivityLog).where(ActivityLog.entity_id == str(created.id))
        )
    ).scalars().all()
    assert activity[-1].module == ActivityModule.COURSES

    updated = await courses.update(
        created.id,
        CourseUpdate(short_description="A practical introduction."),
        actor_id=owner.id,
    )
    assert updated.short_description == "A practical introduction."

    published = await courses.publish(
        created.id,
        published_at=datetime.now(UTC),
        actor_id=owner.id,
    )
    assert published.status == CourseStatus.PUBLISHED

    draft = await courses.unpublish(created.id, actor_id=owner.id)
    assert draft.status == CourseStatus.DRAFT

    archived = await courses.archive(created.id, actor_id=owner.id)
    assert archived.status == CourseStatus.ARCHIVED

    await courses.delete(created.id)
    restored = await courses.restore(created.id)
    assert restored.deleted_at is None


async def test_course_search_and_filters(courses: CourseService) -> None:
    await courses.create(course_payload())
    await courses.create(
        course_payload("JS-101").model_copy(
            update={"title": "JavaScript Basics", "featured": True}
        )
    )

    items, total = await courses.list_courses(
        PaginationParams(page=1, page_size=10),
        search="JavaScript",
        featured_only=True,
    )

    assert total == 1
    assert len(items) == 1
    assert items[0].course_code == "JS-101"


async def test_course_code_and_slug_are_unique(courses: CourseService) -> None:
    await courses.create(course_payload())

    with pytest.raises(ConflictException):
        await courses.create(
            course_payload("PY-102").model_copy(update={"slug": "python-foundations"})
        )

    with pytest.raises(ConflictException):
        await courses.create(course_payload())
