"""CRUD endpoints for extended user details."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, status

from app.core.dependencies import DbSession
from app.modules.users.schemas.user_details import (
    UserDetailsCreate,
    UserDetailsRead,
    UserDetailsUpdate,
)
from app.modules.users.services.user_details import UserDetailsService
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    success_response,
)

router = APIRouter(prefix="/users", tags=["User Details"])

UserId = Annotated[uuid.UUID, Path(description="User identifier.")]


@router.get(
    "/{user_id}/details",
    response_model=APIResponse[UserDetailsRead],
    summary="Get user details",
)
async def get_user_details(
    db: DbSession, user_id: UserId
) -> APIResponse[UserDetailsRead]:
    details = await UserDetailsService(db).get(user_id)
    return success_response(
        data=UserDetailsRead.model_validate(details), message="User details fetched"
    )


@router.post(
    "/{user_id}/details",
    response_model=APIResponse[UserDetailsRead],
    status_code=status.HTTP_201_CREATED,
    summary="Create user details",
)
async def create_user_details(
    db: DbSession, user_id: UserId, payload: UserDetailsCreate
) -> APIResponse[UserDetailsRead]:
    details = await UserDetailsService(db).create(user_id, payload)
    return created_response(
        data=UserDetailsRead.model_validate(details), message="User details created"
    )


@router.patch(
    "/{user_id}/details",
    response_model=APIResponse[UserDetailsRead],
    summary="Update user details",
)
async def update_user_details(
    db: DbSession, user_id: UserId, payload: UserDetailsUpdate
) -> APIResponse[UserDetailsRead]:
    details = await UserDetailsService(db).update(user_id, payload)
    return success_response(
        data=UserDetailsRead.model_validate(details), message="User details updated"
    )


@router.delete(
    "/{user_id}/details",
    response_model=APIResponse[None],
    summary="Delete user details",
)
async def delete_user_details(db: DbSession, user_id: UserId) -> APIResponse[None]:
    await UserDetailsService(db).delete(user_id)
    return deleted_response("User details deleted")
