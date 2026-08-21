"""Data access for courses."""

import uuid

from sqlalchemy import select

from app.modules.courses.models.course import Course
from app.shared.repositories.base import BaseRepository


class CourseRepository(BaseRepository[Course]):
    model = Course

    async def get_by_slug(self, slug: str) -> Course | None:
        return await self.get_by_field("slug", slug)

    async def slug_exists(
        self, slug: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [Course.slug == slug]
        if exclude_id is not None:
            conditions.append(Course.id != exclude_id)
        result = await self.session.execute(
            select(select(Course.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())

    async def course_code_exists(
        self, code: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [Course.course_code == code]
        if exclude_id is not None:
            conditions.append(Course.id != exclude_id)
        result = await self.session.execute(
            select(select(Course.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())
