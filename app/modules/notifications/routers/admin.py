"""Administrative notification endpoints: authoring, sending and measuring."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.core.constants import SortOrder
from app.core.dependencies import DbSession, PaginationDep, SearchDep, SortDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.notifications.constants import (
    DeliveryType,
    NotificationPriority,
    NotificationType,
)
from app.modules.notifications.permissions import (
    can_create,
    can_delete,
    can_update,
    can_view,
)
from app.modules.notifications.schemas.notification import (
    NotificationCreate,
    NotificationDetail,
    NotificationRead,
    NotificationStatistics,
    NotificationSummary,
    NotificationUpdate,
    RecipientSummary,
)
from app.modules.notifications.services.notification import NotificationService
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    created_response,
    deleted_response,
    paginated_response,
    success_response,
)

router = APIRouter(
    prefix="/admin/notifications",
    tags=["Notifications - Admin"],
    dependencies=[can_view()],
)

NotificationId = Annotated[uuid.UUID, Path(description="Notification identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[NotificationSummary]],
    summary="List notifications",
    description="Newest first. Search matches the title and short message.",
)
async def list_notifications(
    db: DbSession,
    pagination: PaginationDep,
    search: SearchDep,
    sort: SortDep,
    notification_type: Annotated[NotificationType | None, Query()] = None,
    delivery_type: Annotated[DeliveryType | None, Query()] = None,
    priority: Annotated[NotificationPriority | None, Query()] = None,
    created_by: Annotated[uuid.UUID | None, Query()] = None,
    is_active: Annotated[bool | None, Query()] = None,
    date_from: Annotated[datetime | None, Query()] = None,
    date_to: Annotated[datetime | None, Query()] = None,
) -> APIResponse[Page[NotificationSummary]]:
    items, total = await NotificationService(db).list_notifications(
        pagination,
        search=search.search,
        notification_type=notification_type,
        delivery_type=delivery_type,
        priority=priority,
        created_by=created_by,
        is_active=is_active,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort.sort_by,
        sort_order=sort.sort_order or SortOrder.DESC,
    )
    return paginated_response(
        [NotificationSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Notifications fetched",
    )


@router.post(
    "",
    response_model=APIResponse[NotificationRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=[can_create()],
    summary="Create and send a notification",
    description=(
        "Writes the announcement and resolves its audience in one "
        "transaction, so a notification never exists without the recipients "
        "it was meant for.\n\n"
        "`target_ids` is read according to `delivery_type`: role ids for "
        "`role`, course ids for `course`, user ids for `user`, and must be "
        "empty for `global`. A targeted delivery with no targets is refused "
        "rather than reported as a send that reached nobody.\n\n"
        "Only active accounts receive anything - a suspended or closed "
        "account cannot sign in to act on it."
    ),
    responses={
        201: {"description": "Created, with its audience resolved."},
        400: {"description": "The delivery type cannot resolve an audience."},
        404: {"description": "A named role or user does not exist."},
        422: {"description": "Targets do not match the delivery type."},
    },
)
async def create_notification(
    db: DbSession, user: CurrentUser, payload: NotificationCreate
) -> APIResponse[NotificationRead]:
    notification = await NotificationService(db).create(payload, actor=user)
    return created_response(
        data=NotificationRead.from_model(notification),
        message=f"Notification sent to {notification.total_recipients} recipient(s)",
    )


@router.get(
    "/{notification_id}",
    response_model=APIResponse[NotificationDetail],
    summary="Get a notification with its engagement figures",
    description=(
        "The statistics are counted from the recipient rows rather than "
        "read off the denormalized columns - this is the screen where the "
        "numbers are scrutinised, so it goes back to the source."
    ),
)
async def get_notification(
    db: DbSession, notification_id: NotificationId
) -> APIResponse[NotificationDetail]:
    service = NotificationService(db)
    notification = await service.get(notification_id)
    statistics = await service.statistics(notification_id)

    return success_response(
        data=NotificationDetail(
            notification=NotificationRead.from_model(notification),
            statistics=statistics,
        ),
        message="Notification fetched",
    )


@router.get(
    "/{notification_id}/statistics",
    response_model=APIResponse[NotificationStatistics],
    summary="Engagement figures alone",
)
async def notification_statistics(
    db: DbSession, notification_id: NotificationId
) -> APIResponse[NotificationStatistics]:
    statistics = await NotificationService(db).statistics(notification_id)
    return success_response(data=statistics, message="Statistics fetched")


@router.get(
    "/{notification_id}/recipients",
    response_model=APIResponse[Page[RecipientSummary]],
    summary="List who received a notification",
)
async def list_recipients(
    db: DbSession,
    notification_id: NotificationId,
    pagination: PaginationDep,
    is_read: Annotated[bool | None, Query()] = None,
) -> APIResponse[Page[RecipientSummary]]:
    items, total = await NotificationService(db).list_recipients(
        notification_id, pagination, is_read=is_read
    )
    return paginated_response(
        [RecipientSummary.model_validate(item) for item in items],
        total,
        pagination,
        message="Recipients fetched",
    )


@router.put(
    "/{notification_id}",
    response_model=APIResponse[NotificationRead],
    dependencies=[can_update()],
    summary="Update a notification before it is published",
    description=(
        "Content is frozen once a notification is published: people have "
        "already read it, and rewriting the text afterwards would leave "
        "them remembering a different notice from the one on file.\n\n"
        "Deactivating a published notification or giving it an expiry is "
        "still allowed - both withdraw it rather than rewrite it. Changing "
        "`delivery_type` or `target_ids` rebuilds the audience from "
        "scratch, which discards what the previous recipients had read, so "
        "it is only permitted before publication."
    ),
    responses={400: {"description": "The notification is already published."}},
)
async def update_notification(
    db: DbSession,
    user: CurrentUser,
    notification_id: NotificationId,
    payload: NotificationUpdate,
) -> APIResponse[NotificationRead]:
    notification = await NotificationService(db).update(
        notification_id, payload, actor=user
    )
    return success_response(
        data=NotificationRead.from_model(notification),
        message="Notification updated",
    )


@router.delete(
    "/{notification_id}",
    response_model=APIResponse[None],
    dependencies=[can_delete()],
    summary="Withdraw a notification",
    description=(
        "Soft delete. Because every recipient-side query joins through the "
        "notification, this withdraws it from everybody's list at once "
        "without touching a single recipient row."
    ),
)
async def delete_notification(
    db: DbSession, user: CurrentUser, notification_id: NotificationId
) -> APIResponse[None]:
    await NotificationService(db).delete(notification_id, actor=user)
    return deleted_response("Notification deleted")


@router.post(
    "/{notification_id}/restore",
    response_model=APIResponse[NotificationRead],
    dependencies=[can_delete()],
    summary="Restore a withdrawn notification",
)
async def restore_notification(
    db: DbSession, user: CurrentUser, notification_id: NotificationId
) -> APIResponse[NotificationRead]:
    notification = await NotificationService(db).restore(notification_id, actor=user)
    return success_response(
        data=NotificationRead.from_model(notification),
        message="Notification restored",
    )
