"""Category endpoints.

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
    CategoryCreate,
    CategoryMove,
    CategoryNode,
    CategoryRead,
    CategorySummary,
    CategoryUpdate,
)
from app.modules.categories.services.category import CategoryService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
    dependencies=[category_admin()],
)

CategoryId = Annotated[uuid.UUID, Path(description="Category identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[CategoryRead]],
    summary="List categories",
    description=(
        "Search matches the name, slug and description. `parent_id` returns "
        "one category's children; `roots_only` returns the top level."
    ),
)
async def list_categories(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    category_type_id: Annotated[
        uuid.UUID | None, Query(description="Filter by taxonomy.")
    ] = None,
    parent_id: Annotated[
        uuid.UUID | None, Query(description="Return this category's children.")
    ] = None,
    roots_only: Annotated[
        bool, Query(description="Return only top-level categories.")
    ] = False,
    category_status: Annotated[
        CategoryStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
) -> APIResponse[Page[CategoryRead]]:
    items, total = await CategoryService(db).list_categories(
        pagination,
        search=search.search,
        type_id=category_type_id,
        parent_id=parent_id,
        roots_only=roots_only,
        status=category_status,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [CategoryRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Categories fetched",
    )


@router.get(
    "/tree",
    response_model=APIResponse[list[CategoryNode]],
    summary="Get a taxonomy's whole tree",
    description=(
        "Every category in one taxonomy, nested, in a single query - what a "
        "navigation menu needs. A category whose parent is filtered out by "
        "`active_only` is promoted to the top rather than dropped, so nothing "
        "vanishes without being deleted."
    ),
)
async def get_category_tree(
    db: DbSession,
    category_type_id: Annotated[uuid.UUID, Query(description="Which taxonomy.")],
    active_only: Annotated[
        bool, Query(description="Leave inactive categories out.")
    ] = False,
) -> APIResponse[list[CategoryNode]]:
    tree = await CategoryService(db).tree(category_type_id, active_only=active_only)

    return success_response(data=tree, message="Category tree fetched")


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[CategoryRead],
    summary="Get a category by slug",
)
async def get_category_by_slug(
    db: DbSession, slug: Annotated[str, Path(description="Category slug.")]
) -> APIResponse[CategoryRead]:
    category = await CategoryService(db).get_by_slug(slug)

    return success_response(
        data=CategoryRead.model_validate(category), message="Category fetched"
    )


@router.get(
    "/{category_id}",
    response_model=APIResponse[CategoryRead],
    summary="Get a category",
)
async def get_category(
    db: DbSession, category_id: CategoryId
) -> APIResponse[CategoryRead]:
    category = await CategoryService(db).get(category_id)

    return success_response(
        data=CategoryRead.model_validate(category), message="Category fetched"
    )


@router.get(
    "/{category_id}/children",
    response_model=APIResponse[list[CategorySummary]],
    summary="List a category's direct children",
)
async def list_children(
    db: DbSession, category_id: CategoryId
) -> APIResponse[list[CategorySummary]]:
    children = await CategoryService(db).children_of(category_id)

    return success_response(
        data=[CategorySummary.model_validate(item) for item in children],
        message="Subcategories fetched",
    )


@router.get(
    "/{category_id}/ancestors",
    response_model=APIResponse[list[CategorySummary]],
    summary="List a category's ancestors",
    description="Nearest parent first, up to the root. What breadcrumbs need.",
)
async def list_ancestors(
    db: DbSession, category_id: CategoryId
) -> APIResponse[list[CategorySummary]]:
    ancestors = await CategoryService(db).ancestors_of(category_id)

    return success_response(
        data=[CategorySummary.model_validate(item) for item in ancestors],
        message="Ancestors fetched",
    )


@router.post(
    "",
    response_model=APIResponse[CategoryRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
    description=(
        "Omit `parent_category_id` for a top-level category. A parent must "
        "belong to the same category type."
    ),
)
async def create_category(
    db: DbSession, user: CurrentUser, payload: CategoryCreate
) -> APIResponse[CategoryRead]:
    category = await CategoryService(db).create(payload, actor_id=user.id)

    return created_response(
        data=CategoryRead.model_validate(category), message="Category created"
    )


@router.patch(
    "/{category_id}",
    response_model=APIResponse[CategoryRead],
    summary="Update a category",
    description=(
        "Sending `parent_category_id: null` moves the category to the top "
        "level; omitting the field leaves the parent alone."
    ),
)
async def update_category(
    db: DbSession, user: CurrentUser, category_id: CategoryId, payload: CategoryUpdate
) -> APIResponse[CategoryRead]:
    category = await CategoryService(db).update(category_id, payload, actor_id=user.id)

    return success_response(
        data=CategoryRead.model_validate(category), message="Category updated"
    )


@router.put(
    "/{category_id}/parent",
    response_model=APIResponse[CategoryRead],
    summary="Move a category",
    description=(
        "Re-parents a category on its own. Refused when the new parent sits "
        "under the category being moved, which would cut the branch out of "
        "the tree."
    ),
)
async def move_category(
    db: DbSession, user: CurrentUser, category_id: CategoryId, payload: CategoryMove
) -> APIResponse[CategoryRead]:
    category = await CategoryService(db).move(
        category_id, payload.parent_category_id, actor_id=user.id
    )

    return success_response(
        data=CategoryRead.model_validate(category), message="Category moved"
    )


@router.delete(
    "/{category_id}",
    response_model=APIResponse[None],
    summary="Delete a category",
    description=(
        "Soft delete, refused while the category still has subcategories - "
        "cascading would remove a whole branch on one click."
    ),
)
async def delete_category(db: DbSession, category_id: CategoryId) -> APIResponse[None]:
    await CategoryService(db).delete(category_id)

    return deleted_response("Category deleted")


@router.post(
    "/{category_id}/restore",
    response_model=APIResponse[CategoryRead],
    summary="Restore a deleted category",
)
async def restore_category(
    db: DbSession, category_id: CategoryId
) -> APIResponse[CategoryRead]:
    category = await CategoryService(db).restore(category_id)

    return success_response(
        data=CategoryRead.model_validate(category), message="Category restored"
    )
