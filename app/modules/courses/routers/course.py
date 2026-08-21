"""Course CRUD and publication endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.courses.constants import CourseLanguage, CourseLevel, CourseStatus
from app.modules.courses.permissions import (
    can_create,
    can_delete,
    can_publish,
    can_update,
    can_view,
)
from app.modules.courses.schemas.course import (
    CourseCreate,
    CoursePublish,
    CourseRead,
    CourseSummary,
    CourseUpdate,
)
from app.modules.courses.services.course import CourseService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/courses", tags=["Courses"], dependencies=[can_view()])
CourseId = Annotated[uuid.UUID, Path(description="Course identifier.")]


@router.get("", response_model=APIResponse[Page[CourseSummary]], summary="List courses")
async def list_courses(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    course_status: Annotated[CourseStatus | None, Query(alias="status")] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    level: Annotated[CourseLevel | None, Query()] = None,
    language: Annotated[CourseLanguage | None, Query()] = None,
    featured_only: bool = False,
    live_only: bool = False,
) -> APIResponse[Page[CourseSummary]]:
    items, total = await CourseService(db).list_courses(
        pagination,
        search=search.search,
        status=course_status,
        category_id=category_id,
        level=level.value if level else None,
        language=language.value if language else None,
        featured_only=featured_only,
        live_only=live_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )
    return paginated_response(
        [CourseSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Courses fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[CourseRead],
    summary="Get a course by slug",
)
async def get_course_by_slug(db: DbSession, slug: str) -> APIResponse[CourseRead]:
    course = await CourseService(db).get_by_slug(slug)
    return success_response(
        data=CourseRead.from_model(course), message="Course fetched"
    )


@router.get(
    "/{course_id}", response_model=APIResponse[CourseRead], summary="Get a course"
)
async def get_course(db: DbSession, course_id: CourseId) -> APIResponse[CourseRead]:
    course = await CourseService(db).get(course_id)
    return success_response(
        data=CourseRead.from_model(course), message="Course fetched"
    )


@router.post(
    "",
    response_model=APIResponse[CourseRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Create a course",
)
async def create_course(
    db: DbSession, user: CurrentUser, payload: CourseCreate
) -> APIResponse[CourseRead]:
    course = await CourseService(db).create(payload, actor_id=user.id)
    return created_response(
        data=CourseRead.from_model(course), message="Course created"
    )


@router.patch(
    "/{course_id}",
    response_model=APIResponse[CourseRead],
    dependencies=[can_update()],
    summary="Update a course",
)
async def update_course(
    db: DbSession, user: CurrentUser, course_id: CourseId, payload: CourseUpdate
) -> APIResponse[CourseRead]:
    course = await CourseService(db).update(course_id, payload, actor_id=user.id)
    return success_response(
        data=CourseRead.from_model(course), message="Course updated"
    )


@router.post(
    "/{course_id}/publish",
    response_model=APIResponse[CourseRead],
    dependencies=[can_publish()],
    summary="Publish a course",
)
async def publish_course(
    db: DbSession, user: CurrentUser, course_id: CourseId, payload: CoursePublish
) -> APIResponse[CourseRead]:
    course = await CourseService(db).publish(
        course_id, published_at=payload.published_at, actor_id=user.id
    )
    return success_response(
        data=CourseRead.from_model(course), message="Course published"
    )


@router.post(
    "/{course_id}/unpublish",
    response_model=APIResponse[CourseRead],
    dependencies=[can_publish()],
    summary="Unpublish a course",
)
async def unpublish_course(
    db: DbSession, user: CurrentUser, course_id: CourseId
) -> APIResponse[CourseRead]:
    course = await CourseService(db).unpublish(course_id, actor_id=user.id)
    return success_response(
        data=CourseRead.from_model(course), message="Course unpublished"
    )


@router.post(
    "/{course_id}/archive",
    response_model=APIResponse[CourseRead],
    dependencies=[can_publish()],
    summary="Archive a course",
)
async def archive_course(
    db: DbSession, user: CurrentUser, course_id: CourseId
) -> APIResponse[CourseRead]:
    course = await CourseService(db).archive(course_id, actor_id=user.id)
    return success_response(
        data=CourseRead.from_model(course), message="Course archived"
    )


@router.delete(
    "/{course_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Delete a course",
)
async def delete_course(db: DbSession, course_id: CourseId) -> APIResponse[None]:
    await CourseService(db).delete(course_id)
    return deleted_response("Course deleted")


@router.post(
    "/{course_id}/restore",
    response_model=APIResponse[CourseRead],
    dependencies=[can_delete()],
    summary="Restore a course",
)
async def restore_course(db: DbSession, course_id: CourseId) -> APIResponse[CourseRead]:
    course = await CourseService(db).restore(course_id)
    return success_response(
        data=CourseRead.from_model(course), message="Course restored"
    )
