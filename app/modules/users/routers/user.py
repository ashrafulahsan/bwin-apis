"""User CRUD endpoints.

Restricted to Super Admin and Admin - see [permissions.py](../permissions.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, UploadFile, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.media.dependencies import StorageDep
from app.modules.users.constants import AuthProvider, UserStatus
from app.modules.users.permissions import user_admin
from app.modules.users.schemas.user import (
    PasswordSet,
    SocialLogin,
    UserCreate,
    UserIdentityRead,
    UserRead,
    UserRoleAssignment,
    UserUpdate,
)
from app.modules.users.services.user import UserService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/users", tags=["Users"], dependencies=[user_admin()])

UserId = Annotated[uuid.UUID, Path(description="User identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[UserRead]],
    summary="List users",
    description="Search matches email, phone, first name and last name.",
)
async def list_users(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    account_status: Annotated[
        UserStatus | None, Query(alias="status", description="Filter by status.")
    ] = None,
    role: Annotated[
        str | None, Query(description="Filter by role slug, e.g. `instructor`.")
    ] = None,
) -> APIResponse[Page[UserRead]]:
    items, total = await UserService(db).list_users(
        pagination,
        search=search.search,
        status=account_status,
        role_slug=role,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )

    return paginated_response(
        [UserRead.model_validate(item) for item in items],
        total,
        pagination,
        message="Users fetched",
    )


@router.get(
    "/by-identifier",
    response_model=APIResponse[UserRead],
    summary="Find a user by email or phone",
    description=(
        "Accepts either credential and works out which it is, so a client "
        "does not have to. Phone numbers are matched in any format."
    ),
)
async def get_user_by_identifier(
    db: DbSession,
    identifier: Annotated[
        str,
        Query(
            description="Email address or phone number.",
            examples=["ali@example.com", "01712345678"],
        ),
    ],
) -> APIResponse[UserRead]:
    user = await UserService(db).get_by_identifier(identifier)

    return success_response(data=UserRead.model_validate(user), message="User fetched")


@router.get("/{user_id}", response_model=APIResponse[UserRead], summary="Get a user")
async def get_user(db: DbSession, user_id: UserId) -> APIResponse[UserRead]:
    user = await UserService(db).get(user_id)

    return success_response(data=UserRead.model_validate(user), message="User fetched")


@router.post(
    "",
    response_model=APIResponse[UserRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
    description=(
        "Requires an email address, a phone number, or both. A password is "
        "optional - omit it for an account that will only use social login. "
        "Without `role_ids` the user becomes a student."
    ),
)
async def create_user(db: DbSession, payload: UserCreate) -> APIResponse[UserRead]:
    user = await UserService(db).create(payload)

    return created_response(data=UserRead.model_validate(user), message="User created")


@router.patch(
    "/{user_id}", response_model=APIResponse[UserRead], summary="Update a user"
)
async def update_user(
    db: DbSession, user_id: UserId, payload: UserUpdate
) -> APIResponse[UserRead]:
    user = await UserService(db).update(user_id, payload)

    return success_response(data=UserRead.model_validate(user), message="User updated")


@router.post(
    "/{user_id}/avatar",
    response_model=APIResponse[UserRead],
    summary="Upload a profile picture",
    description=(
        "Stores the image through the configured storage backend (local "
        "disk or S3 - see `STORAGE_BACKEND`) and points `avatar_url` at it. "
        "Replaces and removes any previous avatar."
    ),
)
async def upload_avatar(
    db: DbSession, user_id: UserId, storage: StorageDep, file: UploadFile
) -> APIResponse[UserRead]:
    user = await UserService(db).set_avatar(user_id, file, storage)

    return success_response(
        data=UserRead.model_validate(user), message="Avatar updated"
    )


@router.delete(
    "/{user_id}/avatar",
    response_model=APIResponse[UserRead],
    summary="Remove a profile picture",
)
async def remove_avatar(
    db: DbSession, user_id: UserId, storage: StorageDep
) -> APIResponse[UserRead]:
    user = await UserService(db).clear_avatar(user_id, storage)

    return success_response(
        data=UserRead.model_validate(user), message="Avatar removed"
    )


@router.delete(
    "/{user_id}",
    response_model=APIResponse[None],
    summary="Delete a user",
    description="Soft delete.",
)
async def delete_user(db: DbSession, user_id: UserId) -> APIResponse[None]:
    await UserService(db).delete(user_id)

    return deleted_response("User deleted")


@router.post(
    "/{user_id}/restore",
    response_model=APIResponse[UserRead],
    summary="Restore a deleted user",
)
async def restore_user(db: DbSession, user_id: UserId) -> APIResponse[UserRead]:
    user = await UserService(db).restore(user_id)

    return success_response(data=UserRead.model_validate(user), message="User restored")


@router.put(
    "/{user_id}/password",
    response_model=APIResponse[UserRead],
    summary="Set or change a password",
    description=(
        "`current_password` is required when the account already has one. "
        "An account created through social login can set its first password "
        "without it."
    ),
)
async def set_password(
    db: DbSession, user_id: UserId, payload: PasswordSet
) -> APIResponse[UserRead]:
    user = await UserService(db).set_password(user_id, payload)

    return success_response(data=UserRead.model_validate(user), message="Password set")


# -- Verification -------------------------------------------------------


@router.post(
    "/{user_id}/verify-email",
    response_model=APIResponse[UserRead],
    summary="Mark an email address verified",
)
async def verify_email(db: DbSession, user_id: UserId) -> APIResponse[UserRead]:
    user = await UserService(db).verify_email(user_id)

    return success_response(
        data=UserRead.model_validate(user), message="Email verified"
    )


@router.post(
    "/{user_id}/verify-phone",
    response_model=APIResponse[UserRead],
    summary="Mark a phone number verified",
)
async def verify_phone(db: DbSession, user_id: UserId) -> APIResponse[UserRead]:
    user = await UserService(db).verify_phone(user_id)

    return success_response(
        data=UserRead.model_validate(user), message="Phone verified"
    )


# -- Roles --------------------------------------------------------------


@router.put(
    "/{user_id}/roles",
    response_model=APIResponse[UserRead],
    summary="Replace a user's roles",
)
async def replace_roles(
    db: DbSession, user_id: UserId, payload: UserRoleAssignment
) -> APIResponse[UserRead]:
    user = await UserService(db).replace_roles(user_id, payload.role_ids)

    return success_response(data=UserRead.model_validate(user), message="Roles updated")


@router.post(
    "/{user_id}/roles",
    response_model=APIResponse[UserRead],
    summary="Assign roles to a user",
)
async def assign_roles(
    db: DbSession, user_id: UserId, payload: UserRoleAssignment
) -> APIResponse[UserRead]:
    user = await UserService(db).assign_roles(user_id, payload.role_ids)

    return success_response(
        data=UserRead.model_validate(user), message="Roles assigned"
    )


@router.post(
    "/{user_id}/roles/revoke",
    response_model=APIResponse[UserRead],
    summary="Revoke roles from a user",
)
async def revoke_roles(
    db: DbSession, user_id: UserId, payload: UserRoleAssignment
) -> APIResponse[UserRead]:
    user = await UserService(db).revoke_roles(user_id, payload.role_ids)

    return success_response(data=UserRead.model_validate(user), message="Roles revoked")


# -- Social identities --------------------------------------------------


@router.get(
    "/{user_id}/identities",
    response_model=APIResponse[list[UserIdentityRead]],
    summary="List linked social accounts",
)
async def list_identities(
    db: DbSession, user_id: UserId
) -> APIResponse[list[UserIdentityRead]]:
    user = await UserService(db).get(user_id)

    return success_response(
        data=[UserIdentityRead.model_validate(item) for item in user.identities],
        message="Identities fetched",
    )


@router.post(
    "/{user_id}/identities",
    response_model=APIResponse[UserIdentityRead],
    status_code=status.HTTP_201_CREATED,
    summary="Link a social account",
    description=(
        "Attaches a Google or Facebook account. The caller must already have "
        "verified the identity with the provider."
    ),
)
async def link_identity(
    db: DbSession, user_id: UserId, payload: SocialLogin
) -> APIResponse[UserIdentityRead]:
    identity = await UserService(db).link_social_account(user_id, payload)

    return created_response(
        data=UserIdentityRead.model_validate(identity), message="Account linked"
    )


@router.delete(
    "/{user_id}/identities/{provider}",
    response_model=APIResponse[None],
    summary="Unlink a social account",
    description="Refused when it is the only way left to sign in.",
)
async def unlink_identity(
    db: DbSession,
    user_id: UserId,
    provider: Annotated[AuthProvider, Path(description="Provider to unlink.")],
) -> APIResponse[None]:
    await UserService(db).unlink_social_account(user_id, provider.value)

    return deleted_response("Account unlinked")
