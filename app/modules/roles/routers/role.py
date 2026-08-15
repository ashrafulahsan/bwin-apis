"""Role CRUD endpoints.

Permission enforcement arrives with the authentication module; the names in
`permissions.py` are already reserved for it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.roles.schemas.role import (
    RoleCreate,
    RoleRead,
    RoleSummary,
    RoleUpdate,
)
from app.modules.roles.services.role import RoleService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/roles", tags=["Roles"])

RoleId = Annotated[uuid.UUID, Path(description="Role identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[RoleRead]],
    summary="List roles",
    description="Paginated roles, most privileged first by default.",
)
async def list_roles(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    is_system: Annotated[
        bool | None,
        Query(description="Filter to built-in roles, or to custom ones."),
    ] = None,
) -> APIResponse[Page[RoleRead]]:
    items, total = await RoleService(db).list_roles(
        pagination,
        search=search.search,
        is_system=is_system,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [RoleRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Roles fetched",
    )


@router.get(
    "/all",
    response_model=APIResponse[list[RoleSummary]],
    summary="All roles",
    description="Every role in one call, for populating a role picker.",
)
async def list_all_roles(db: DbSession) -> APIResponse[list[RoleSummary]]:
    roles = await RoleService(db).list_all()

    return success_response(
        data=[RoleSummary.model_validate(role) for role in roles],
        message="Roles fetched",
    )


@router.get(
    "/slug/{slug}",
    response_model=APIResponse[RoleRead],
    summary="Get a role by slug",
)
async def get_role_by_slug(
    db: DbSession,
    slug: Annotated[str, Path(description="Stable role identifier, e.g. `admin`.")],
) -> APIResponse[RoleRead]:
    role = await RoleService(db).get_by_slug(slug)

    return success_response(data=RoleRead.model_validate(role), message="Role fetched")


@router.get(
    "/{role_id}",
    response_model=APIResponse[RoleRead],
    summary="Get a role",
)
async def get_role(db: DbSession, role_id: RoleId) -> APIResponse[RoleRead]:
    role = await RoleService(db).get(role_id)

    return success_response(data=RoleRead.model_validate(role), message="Role fetched")


@router.post(
    "",
    response_model=APIResponse[RoleRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a role",
    description="The slug is derived from the name and fixed thereafter.",
)
async def create_role(db: DbSession, payload: RoleCreate) -> APIResponse[RoleRead]:
    role = await RoleService(db).create(payload)

    return created_response(data=RoleRead.model_validate(role), message="Role created")


@router.patch(
    "/{role_id}",
    response_model=APIResponse[RoleRead],
    summary="Update a role",
    description=(
        "Partial update. The slug never changes, and the level of a system "
        "role is immutable."
    ),
)
async def update_role(
    db: DbSession, role_id: RoleId, payload: RoleUpdate
) -> APIResponse[RoleRead]:
    role = await RoleService(db).update(role_id, payload)

    return success_response(data=RoleRead.model_validate(role), message="Role updated")


@router.delete(
    "/{role_id}",
    response_model=APIResponse[None],
    summary="Delete a role",
    description="Soft delete. System roles cannot be deleted.",
)
async def delete_role(db: DbSession, role_id: RoleId) -> APIResponse[None]:
    await RoleService(db).delete(role_id)

    return deleted_response("Role deleted")


@router.post(
    "/{role_id}/restore",
    response_model=APIResponse[RoleRead],
    summary="Restore a deleted role",
)
async def restore_role(db: DbSession, role_id: RoleId) -> APIResponse[RoleRead]:
    role = await RoleService(db).restore(role_id)

    return success_response(data=RoleRead.model_validate(role), message="Role restored")
