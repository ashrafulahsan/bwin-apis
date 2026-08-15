"""Category type endpoints.

Every route is restricted to Super Admin and Admin - see
[permissions.py](../permissions.py) for why the guard names roles rather than
permission codes.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.categories.constants import CategoryStatus
from app.modules.categories.permissions import category_admin
from app.modules.categories.schemas.category import (
    CategoryTypeCreate,
    CategoryTypeRead,
    CategoryTypeUpdate,
)
from app.modules.categories.services.category_type import CategoryTypeService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/category-types",
    tags=["Category Types"],
    dependencies=[category_admin()],
)

TypeId = Annotated[uuid.UUID, Path(description="Category type identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[CategoryTypeRead]],
    summary="List category types",
    description="Search matches the name, slug and description.",
)
async def list_category_types(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    type_status: Annotated[
        CategoryStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
) -> APIResponse[Page[CategoryTypeRead]]:
    items, total = await CategoryTypeService(db).list_types(
        pagination,
        search=search.search,
        status=type_status,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [CategoryTypeRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Category types fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[CategoryTypeRead],
    summary="Get a category type by slug",
)
async def get_category_type_by_slug(
    db: DbSession, slug: Annotated[str, Path(description="Category type slug.")]
) -> APIResponse[CategoryTypeRead]:
    category_type = await CategoryTypeService(db).get_by_slug(slug)

    return success_response(
        data=CategoryTypeRead.model_validate(category_type),
        message="Category type fetched",
    )


@router.get(
    "/{type_id}",
    response_model=APIResponse[CategoryTypeRead],
    summary="Get a category type",
)
async def get_category_type(
    db: DbSession, type_id: TypeId
) -> APIResponse[CategoryTypeRead]:
    category_type = await CategoryTypeService(db).get(type_id)

    return success_response(
        data=CategoryTypeRead.model_validate(category_type),
        message="Category type fetched",
    )


@router.post(
    "",
    response_model=APIResponse[CategoryTypeRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a category type",
    description="The slug is derived from the name and stays fixed afterwards.",
)
async def create_category_type(
    db: DbSession, user: CurrentUser, payload: CategoryTypeCreate
) -> APIResponse[CategoryTypeRead]:
    category_type = await CategoryTypeService(db).create(payload, actor_id=user.id)

    return created_response(
        data=CategoryTypeRead.model_validate(category_type),
        message="Category type created",
    )


@router.patch(
    "/{type_id}",
    response_model=APIResponse[CategoryTypeRead],
    summary="Update a category type",
    description="The slug is left alone when the name changes; it is in URLs.",
)
async def update_category_type(
    db: DbSession, user: CurrentUser, type_id: TypeId, payload: CategoryTypeUpdate
) -> APIResponse[CategoryTypeRead]:
    category_type = await CategoryTypeService(db).update(
        type_id, payload, actor_id=user.id
    )

    return success_response(
        data=CategoryTypeRead.model_validate(category_type),
        message="Category type updated",
    )


@router.delete(
    "/{type_id}",
    response_model=APIResponse[None],
    summary="Delete a category type",
    description=(
        "Soft delete, refused while the taxonomy still holds categories - "
        "deleting it anyway would orphan the whole tree."
    ),
)
async def delete_category_type(db: DbSession, type_id: TypeId) -> APIResponse[None]:
    await CategoryTypeService(db).delete(type_id)

    return deleted_response("Category type deleted")


@router.post(
    "/{type_id}/restore",
    response_model=APIResponse[CategoryTypeRead],
    summary="Restore a deleted category type",
)
async def restore_category_type(
    db: DbSession, type_id: TypeId
) -> APIResponse[CategoryTypeRead]:
    category_type = await CategoryTypeService(db).restore(type_id)

    return success_response(
        data=CategoryTypeRead.model_validate(category_type),
        message="Category type restored",
    )
