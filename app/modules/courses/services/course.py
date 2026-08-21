"""Business logic for courses."""

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.categories.models.category import Category
from app.modules.categories.repositories.category import CategoryRepository
from app.modules.courses.constants import COURSE_SEARCH_FIELDS, CourseStatus
from app.modules.courses.models.course import Course
from app.modules.courses.repositories.course import CourseRepository
from app.modules.courses.schemas.course import CourseCreate, CourseUpdate
from app.modules.users.repositories.user import UserRepository
from app.shared.models.seo import DEFAULT_META_ROBOTS
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.schemas.seo import SEO_FIELDS
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot
from app.shared.utils.dates import utc_now
from app.shared.utils.slug import generate_unique_slug, slugify

logger = logging.getLogger(__name__)


class CourseService:
    """Coordinates course reads, writes and publication transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CourseRepository(session)
        self.categories = CategoryRepository(session)
        self.users = UserRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.COURSES)

    async def get(self, course_id: uuid.UUID) -> Course:
        return await self.repository.get_or_raise(course_id)

    async def get_by_slug(self, slug: str) -> Course:
        course = await self.repository.get_by_slug(slug)
        if course is None:
            raise NotFoundException(f"Course '{slug}'")
        return course

    async def list_courses(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        status: CourseStatus | None = None,
        category_id: uuid.UUID | None = None,
        level: str | None = None,
        language: str | None = None,
        featured_only: bool = False,
        live_only: bool = False,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Course], int]:
        filters = []
        if status is not None:
            filters.append(Filter.eq("status", status.value))
        if category_id is not None:
            filters.append(Filter.eq("category_id", category_id))
        if level is not None:
            filters.append(Filter.eq("level", level))
        if language is not None:
            filters.append(Filter.eq("language", language))
        if featured_only:
            filters.append(Filter.eq("featured", True))
        if live_only:
            filters.extend(
                [
                    Filter.eq("status", CourseStatus.PUBLISHED.value),
                    Filter.lte("published_at", utc_now()),
                ]
            )

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(COURSE_SEARCH_FIELDS),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def create(
        self, payload: CourseCreate, *, actor_id: uuid.UUID | None = None
    ) -> Course:
        if await self.repository.course_code_exists(payload.course_code):
            raise ConflictException(
                f"A course with code '{payload.course_code}' already exists."
            )

        await self._resolve_categories(
            payload.category_id, payload.course_type, payload.delivery_mode
        )
        slug = await self._slug_for(payload.slug, payload.title)
        values = payload.model_dump(exclude={"seo"})
        values.update(
            {
                "slug": slug,
                "level": payload.level.value,
                "language": payload.language.value,
                "status": CourseStatus.DRAFT.value,
                "published_at": None,
                "created_by": actor_id,
                "updated_by": actor_id,
            }
        )
        values.update(self._seo_values(payload))
        course = await self.repository.create(**values)

        await self.activity.record(
            ActivityAction.CREATE,
            entity=course,
            description=f"Created course {course.title!r}",
            new_values=snapshot(course, exclude=["description"]),
        )
        await self.session.commit()
        logger.info("Created course %s (%s)", course.title, course.slug)
        return course

    async def update(
        self,
        course_id: uuid.UUID,
        payload: CourseUpdate,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Course:
        course = await self.repository.get_or_raise(course_id)
        changes = payload.model_dump(exclude_unset=True, exclude={"seo"})
        if not changes:
            return course

        for field in ("course_code", "title", "slug", "description"):
            if changes.get(field) is None:
                changes.pop(field, None)

        if "course_code" in changes and await self.repository.course_code_exists(
            changes["course_code"], exclude_id=course.id
        ):
            raise ConflictException(
                f"A course with code '{changes['course_code']}' already exists."
            )
        if "slug" in changes:
            changes["slug"] = await self._reslug(course, changes["slug"])
        await self._resolve_categories(
            changes.get("category_id", course.category_id),
            changes.get("course_type", course.course_type),
            changes.get("delivery_mode", course.delivery_mode),
        )
        for field in ("level", "language", "visibility"):
            if field in changes and changes[field] is not None:
                changes[field] = changes[field].value
        if payload.seo is not None:
            changes.update(self._seo_values(payload))
        changes["updated_by"] = actor_id

        before = snapshot(course, fields=changes.keys(), exclude=["description"])
        updated = await self.repository.update(course, **changes)
        old_values, new_values = diff(
            before, snapshot(updated, fields=changes.keys(), exclude=["description"])
        )
        if "description" in changes:
            new_values["description"] = f"{len(updated.description)} characters"
        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=f"Updated course {updated.title!r}",
                old_values=old_values,
                new_values=new_values,
            )
        await self.session.commit()
        return updated

    async def publish(
        self,
        course_id: uuid.UUID,
        *,
        published_at: datetime | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> Course:
        course = await self.repository.get_or_raise(course_id)
        if course.status == CourseStatus.PUBLISHED and published_at is None:
            raise ConflictException(f"'{course.title}' is already published.")
        moment = published_at or course.published_at or utc_now()
        previous_status = course.status
        updated = await self.repository.update(
            course,
            status=CourseStatus.PUBLISHED.value,
            published_at=moment,
            updated_by=actor_id,
        )
        await self.activity.record(
            ActivityAction.PUBLISH,
            entity=updated,
            description=f"Published course {updated.title!r}",
            old_values={"status": previous_status},
            new_values={"status": updated.status, "published_at": moment.isoformat()},
        )
        await self.session.commit()
        return updated

    async def unpublish(
        self, course_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Course:
        course = await self.repository.get_or_raise(course_id)
        if course.status == CourseStatus.DRAFT:
            raise ConflictException(f"'{course.title}' is already a draft.")
        previous_status = course.status
        updated = await self.repository.update(
            course, status=CourseStatus.DRAFT.value, updated_by=actor_id
        )
        await self.activity.record(
            ActivityAction.UNPUBLISH,
            entity=updated,
            description=f"Unpublished course {updated.title!r}",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()
        return updated

    async def archive(
        self, course_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
    ) -> Course:
        course = await self.repository.get_or_raise(course_id)
        if course.status == CourseStatus.ARCHIVED:
            raise ConflictException(f"'{course.title}' is already archived.")
        previous_status = course.status
        updated = await self.repository.update(
            course, status=CourseStatus.ARCHIVED.value, updated_by=actor_id
        )
        await self.activity.record(
            ActivityAction.ARCHIVE,
            entity=updated,
            description=f"Archived course {updated.title!r}",
            old_values={"status": previous_status},
            new_values={"status": updated.status},
        )
        await self.session.commit()
        return updated

    async def delete(self, course_id: uuid.UUID) -> None:
        course = await self.repository.get_or_raise(course_id)
        before = snapshot(course, exclude=["description"])
        await self.repository.soft_delete(course)
        await self.activity.record(
            ActivityAction.DELETE,
            entity=course,
            description=f"Deleted course {course.title!r}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, course_id: uuid.UUID) -> Course:
        course = await self.repository.get_or_raise(course_id, include_deleted=True)
        restored = await self.repository.restore(course)
        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored course {restored.title!r}",
            new_values=snapshot(restored, exclude=["description"]),
        )
        await self.session.commit()
        return restored

    async def _resolve_categories(
        self,
        category_id: uuid.UUID | None,
        course_type: uuid.UUID | None,
        delivery_mode: uuid.UUID | None,
    ) -> list[Category]:
        categories = []
        for category_id_value in {
            value for value in (category_id, course_type, delivery_mode) if value
        }:
            category = await self.categories.get_or_raise(category_id_value)
            if not category.is_active:
                raise BadRequestException(f"Category '{category.name}' is inactive.")
            categories.append(category)
        return categories

    async def _slug_for(self, requested: str | None, title: str) -> str:
        if requested is None:
            return await generate_unique_slug(title, self.repository.slug_exists)
        slug = slugify(requested)
        if not slug:
            raise BadRequestException(f"'{requested}' does not contain a usable slug.")
        if await self.repository.slug_exists(slug):
            raise ConflictException(f"Another course already uses the slug '{slug}'.")
        return slug

    async def _reslug(self, course: Course, requested: str) -> str:
        if course.status != CourseStatus.DRAFT:
            raise ConflictException("A published course cannot change its slug.")
        slug = slugify(requested)
        if not slug:
            raise BadRequestException(f"'{requested}' does not contain a usable slug.")
        if slug != course.slug and await self.repository.slug_exists(
            slug, exclude_id=course.id
        ):
            raise ConflictException(f"Another course already uses the slug '{slug}'.")
        return slug

    @staticmethod
    def _seo_values(payload: CourseCreate | CourseUpdate) -> dict[str, object]:
        if payload.seo is None:
            return {}
        values = payload.seo.model_dump(exclude_unset=True)
        if values.get("meta_robots") is None:
            values["meta_robots"] = DEFAULT_META_ROBOTS
        return {field: values[field] for field in SEO_FIELDS if field in values}
