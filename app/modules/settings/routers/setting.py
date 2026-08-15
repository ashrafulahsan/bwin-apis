"""Settings endpoints.

Every route here is guarded. These rows hold OAuth client secrets, so an
unauthenticated settings API would be a credential leak with a URL.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.core.dependencies import DbSession
from app.modules.auth.dependencies import require_permission
from app.modules.settings.constants import SettingGroup
from app.modules.settings.permissions import SettingPermission
from app.modules.settings.schemas.setting import (
    SettingBulkUpdate,
    SettingCreate,
    SettingRead,
    SettingUpdate,
)
from app.modules.settings.services.setting import SettingService
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    success_response,
)

router = APIRouter(prefix="/settings", tags=["Settings"])

SettingKeyPath = Annotated[str, Path(description="Setting key, e.g. `frontend_url`.")]

CanView = Depends(require_permission(SettingPermission.VIEW))
CanUpdate = Depends(require_permission(SettingPermission.UPDATE))


@router.get(
    "",
    response_model=APIResponse[list[SettingRead]],
    dependencies=[CanView],
    summary="List every setting",
    description="Secret values come back masked, never in the clear.",
)
async def list_settings(db: DbSession) -> APIResponse[list[SettingRead]]:
    settings = await SettingService(db).list_all()

    return success_response(
        data=[SettingRead.from_model(item) for item in settings],
        message="Settings fetched",
    )


@router.get(
    "/groups/{group}",
    response_model=APIResponse[list[SettingRead]],
    dependencies=[CanView],
    summary="List one group of settings",
    description="Groups map onto the sections of a settings screen.",
)
async def list_group(
    db: DbSession,
    group: Annotated[SettingGroup, Path(description="Settings group.")],
) -> APIResponse[list[SettingRead]]:
    settings = await SettingService(db).list_group(group.value)

    return success_response(
        data=[SettingRead.from_model(item) for item in settings],
        message="Settings fetched",
    )


@router.get(
    "/{key}",
    response_model=APIResponse[SettingRead],
    dependencies=[CanView],
    summary="Get one setting",
)
async def get_setting(db: DbSession, key: SettingKeyPath) -> APIResponse[SettingRead]:
    setting = await SettingService(db).get(key)

    return success_response(
        data=SettingRead.from_model(setting), message="Setting fetched"
    )


@router.put(
    "/{key}",
    response_model=APIResponse[SettingRead],
    dependencies=[CanUpdate],
    summary="Change one setting",
    description="Send `null` to clear a value rather than blank it.",
)
async def update_setting(
    db: DbSession, key: SettingKeyPath, payload: SettingUpdate
) -> APIResponse[SettingRead]:
    setting = await SettingService(db).set(key, payload.value)

    return success_response(
        data=SettingRead.from_model(setting), message="Setting updated"
    )


@router.patch(
    "",
    response_model=APIResponse[list[SettingRead]],
    dependencies=[CanUpdate],
    summary="Change several settings at once",
    description=(
        "What a settings form saves. An unknown key rejects the whole request, "
        "so a typo cannot leave half the form applied."
    ),
)
async def update_settings(
    db: DbSession, payload: SettingBulkUpdate
) -> APIResponse[list[SettingRead]]:
    settings = await SettingService(db).set_many(payload.values)

    return success_response(
        data=[SettingRead.from_model(item) for item in settings],
        message="Settings updated",
    )


@router.post(
    "",
    response_model=APIResponse[SettingRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[CanUpdate],
    summary="Add a setting of your own",
)
async def create_setting(
    db: DbSession, payload: SettingCreate
) -> APIResponse[SettingRead]:
    setting = await SettingService(db).create(payload)

    return created_response(
        data=SettingRead.from_model(setting), message="Setting created"
    )


@router.delete(
    "/{key}",
    response_model=APIResponse[None],
    dependencies=[CanUpdate],
    summary="Delete a custom setting",
    description="Settings that ship with the platform cannot be deleted.",
)
async def delete_setting(db: DbSession, key: SettingKeyPath) -> APIResponse[None]:
    await SettingService(db).delete(key)

    return deleted_response("Setting deleted")
