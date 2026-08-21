"""Automation CRUD and publication endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.automations.constants import AutomationStatus
from app.modules.automations.permissions import (
    can_create,
    can_delete,
    can_publish,
    can_update,
    can_view,
)
from app.modules.automations.schemas.automation import (
    AutomationCreate,
    AutomationPublish,
    AutomationRead,
    AutomationSummary,
    AutomationUpdate,
)
from app.modules.automations.services.automation import AutomationService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/automations", tags=["Automations"], dependencies=[can_view()]
)
AutomationId = Annotated[uuid.UUID, Path(description="Automation identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[AutomationSummary]],
    summary="List automations",
)
async def list_automations(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    automation_status: Annotated[AutomationStatus | None, Query(alias="status")] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    live_only: bool = False,
) -> APIResponse[Page[AutomationSummary]]:
    items, total = await AutomationService(db).list_automations(
        pagination,
        search=search.search,
        status=automation_status,
        category_id=category_id,
        live_only=live_only,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order,
    )
    return paginated_response(
        [AutomationSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Automations fetched",
    )


@router.get(
    "/by-slug/{slug}",
    response_model=APIResponse[AutomationRead],
    summary="Get an automation by slug",
)
async def get_automation_by_slug(
    db: DbSession, slug: str
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).get_by_slug(slug)
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation fetched"
    )


@router.get(
    "/{automation_id}",
    response_model=APIResponse[AutomationRead],
    summary="Get an automation",
)
async def get_automation(
    db: DbSession, automation_id: AutomationId
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).get(automation_id)
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation fetched"
    )


@router.post(
    "",
    response_model=APIResponse[AutomationRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Create an automation",
)
async def create_automation(
    db: DbSession, user: CurrentUser, payload: AutomationCreate
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).create(payload, actor_id=user.id)
    return created_response(
        data=AutomationRead.from_model(automation), message="Automation created"
    )


@router.patch(
    "/{automation_id}",
    response_model=APIResponse[AutomationRead],
    dependencies=[can_update()],
    summary="Update an automation",
)
async def update_automation(
    db: DbSession,
    user: CurrentUser,
    automation_id: AutomationId,
    payload: AutomationUpdate,
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).update(
        automation_id, payload, actor_id=user.id
    )
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation updated"
    )


@router.post(
    "/{automation_id}/publish",
    response_model=APIResponse[AutomationRead],
    dependencies=[can_publish()],
    summary="Publish an automation",
)
async def publish_automation(
    db: DbSession,
    user: CurrentUser,
    automation_id: AutomationId,
    payload: AutomationPublish,
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).publish(
        automation_id, published_at=payload.published_at, actor_id=user.id
    )
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation published"
    )


@router.post(
    "/{automation_id}/unpublish",
    response_model=APIResponse[AutomationRead],
    dependencies=[can_publish()],
    summary="Unpublish an automation",
)
async def unpublish_automation(
    db: DbSession, user: CurrentUser, automation_id: AutomationId
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).unpublish(automation_id, actor_id=user.id)
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation unpublished"
    )


@router.post(
    "/{automation_id}/archive",
    response_model=APIResponse[AutomationRead],
    dependencies=[can_publish()],
    summary="Archive an automation",
)
async def archive_automation(
    db: DbSession, user: CurrentUser, automation_id: AutomationId
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).archive(automation_id, actor_id=user.id)
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation archived"
    )


@router.delete(
    "/{automation_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Delete an automation",
)
async def delete_automation(
    db: DbSession, automation_id: AutomationId
) -> APIResponse[None]:
    await AutomationService(db).delete(automation_id)
    return deleted_response("Automation deleted")


@router.post(
    "/{automation_id}/restore",
    response_model=APIResponse[AutomationRead],
    dependencies=[can_delete()],
    summary="Restore an automation",
)
async def restore_automation(
    db: DbSession, automation_id: AutomationId
) -> APIResponse[AutomationRead]:
    automation = await AutomationService(db).restore(automation_id)
    return success_response(
        data=AutomationRead.from_model(automation), message="Automation restored"
    )
