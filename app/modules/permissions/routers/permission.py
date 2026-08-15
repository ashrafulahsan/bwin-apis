"""Permission CRUD and role-permission mapping endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.permissions.constants import RESOURCE_LABELS
from app.modules.permissions.schemas.permission import (
    PermissionCheck,
    PermissionCodes,
    PermissionCreate,
    PermissionRead,
    PermissionSummary,
    PermissionUpdate,
    ResourcePermissions,
    RolePermissions,
)
from app.modules.permissions.services.permission import PermissionService
from app.modules.roles.services.role import RoleService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(tags=["Permissions"])

PermissionId = Annotated[uuid.UUID, Path(description="Permission identifier.")]
RoleId = Annotated[uuid.UUID, Path(description="Role identifier.")]


# -- Permission CRUD ----------------------------------------------------


@router.get(
    "/permissions",
    response_model=APIResponse[Page[PermissionRead]],
    summary="List permissions",
)
async def list_permissions(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    resource: Annotated[
        str | None, Query(description="Filter by resource, e.g. `course`.")
    ] = None,
    action: Annotated[
        str | None, Query(description="Filter by action, e.g. `view`.")
    ] = None,
) -> APIResponse[Page[PermissionRead]]:
    items, total = await PermissionService(db).list_permissions(
        pagination,
        resource=resource,
        action=action,
        search=search.search,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [PermissionRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Permissions fetched",
    )


@router.get(
    "/permissions/grouped",
    response_model=APIResponse[list[ResourcePermissions]],
    summary="Permissions grouped by resource",
    description="Shaped for a resource-by-action permission grid.",
)
async def list_grouped_permissions(
    db: DbSession,
) -> APIResponse[list[ResourcePermissions]]:
    grouped = await PermissionService(db).grouped_by_resource()

    return success_response(
        data=[
            ResourcePermissions(
                resource=resource,
                label=RESOURCE_LABELS.get(resource, resource),
                permissions=[
                    PermissionSummary.model_validate(item) for item in permissions
                ],
            )
            for resource, permissions in grouped.items()
        ],
        message="Permissions fetched",
    )


@router.get(
    "/permissions/resources",
    response_model=APIResponse[list[str]],
    summary="List permission resources",
)
async def list_resources(db: DbSession) -> APIResponse[list[str]]:
    resources = await PermissionService(db).list_resources()

    return success_response(data=resources, message="Resources fetched")


@router.get(
    "/permissions/{permission_id}",
    response_model=APIResponse[PermissionRead],
    summary="Get a permission",
)
async def get_permission(
    db: DbSession, permission_id: PermissionId
) -> APIResponse[PermissionRead]:
    permission = await PermissionService(db).get(permission_id)

    return success_response(
        data=PermissionRead.model_validate(permission), message="Permission fetched"
    )


@router.post(
    "/permissions",
    response_model=APIResponse[PermissionRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a permission",
)
async def create_permission(
    db: DbSession, payload: PermissionCreate
) -> APIResponse[PermissionRead]:
    permission = await PermissionService(db).create(payload)

    return created_response(
        data=PermissionRead.model_validate(permission), message="Permission created"
    )


@router.patch(
    "/permissions/{permission_id}",
    response_model=APIResponse[PermissionRead],
    summary="Update a permission",
    description="The code is immutable; only the label and description change.",
)
async def update_permission(
    db: DbSession, permission_id: PermissionId, payload: PermissionUpdate
) -> APIResponse[PermissionRead]:
    permission = await PermissionService(db).update(permission_id, payload)

    return success_response(
        data=PermissionRead.model_validate(permission), message="Permission updated"
    )


@router.delete(
    "/permissions/{permission_id}",
    response_model=APIResponse[None],
    summary="Delete a permission",
    description="Refused for system permissions and for any still granted to a role.",
)
async def delete_permission(
    db: DbSession, permission_id: PermissionId
) -> APIResponse[None]:
    await PermissionService(db).delete(permission_id)

    return deleted_response("Permission deleted")


# -- Role mapping -------------------------------------------------------


async def _role_permissions_payload(
    db: DbSession, role_id: uuid.UUID, permissions: list
) -> RolePermissions:
    role = await RoleService(db).get(role_id)

    return RolePermissions(
        role_id=role.id,
        role_slug=role.slug,
        count=len(permissions),
        permissions=[PermissionSummary.model_validate(item) for item in permissions],
    )


@router.get(
    "/roles/{role_id}/permissions",
    response_model=APIResponse[RolePermissions],
    summary="List a role's permissions",
)
async def list_role_permissions(
    db: DbSession, role_id: RoleId
) -> APIResponse[RolePermissions]:
    permissions = await PermissionService(db).permissions_for_role(role_id)

    return success_response(
        data=await _role_permissions_payload(db, role_id, permissions),
        message="Role permissions fetched",
    )


@router.put(
    "/roles/{role_id}/permissions",
    response_model=APIResponse[RolePermissions],
    summary="Replace a role's permissions",
    description=(
        "Sets the role's permissions to exactly the codes supplied - what an "
        "admin grid submits when saved."
    ),
)
async def replace_role_permissions(
    db: DbSession, role_id: RoleId, payload: PermissionCodes
) -> APIResponse[RolePermissions]:
    permissions = await PermissionService(db).replace(role_id, payload.codes)

    return success_response(
        data=await _role_permissions_payload(db, role_id, permissions),
        message="Role permissions updated",
    )


@router.post(
    "/roles/{role_id}/permissions",
    response_model=APIResponse[RolePermissions],
    summary="Grant permissions to a role",
    description="Adds to the existing grants. Re-granting is not an error.",
)
async def grant_role_permissions(
    db: DbSession, role_id: RoleId, payload: PermissionCodes
) -> APIResponse[RolePermissions]:
    permissions = await PermissionService(db).grant(role_id, payload.codes)

    return success_response(
        data=await _role_permissions_payload(db, role_id, permissions),
        message="Permissions granted",
    )


@router.post(
    "/roles/{role_id}/permissions/revoke",
    response_model=APIResponse[RolePermissions],
    summary="Revoke permissions from a role",
    description=(
        "POST rather than DELETE because the codes travel in the body, and "
        "some proxies strip bodies from DELETE requests."
    ),
)
async def revoke_role_permissions(
    db: DbSession, role_id: RoleId, payload: PermissionCodes
) -> APIResponse[RolePermissions]:
    permissions = await PermissionService(db).revoke(role_id, payload.codes)

    return success_response(
        data=await _role_permissions_payload(db, role_id, permissions),
        message="Permissions revoked",
    )


@router.get(
    "/roles/{role_id}/permissions/{code}",
    response_model=APIResponse[PermissionCheck],
    summary="Check a role's permission",
)
async def check_role_permission(
    db: DbSession,
    role_id: RoleId,
    code: Annotated[str, Path(description="Permission code, e.g. `user.view`.")],
) -> APIResponse[PermissionCheck]:
    service = PermissionService(db)
    granted = await service.role_has_permission(role_id, code)
    role = await RoleService(db).get(role_id)

    return success_response(
        data=PermissionCheck(role_slug=role.slug, code=code, granted=granted),
        message="Permission checked",
    )
