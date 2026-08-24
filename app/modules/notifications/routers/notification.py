"""The recipient's own notification endpoints.

Every route here is scoped to the caller by construction: the service looks
up the caller's own recipient row, so there is no path through this router
that can return somebody else's notification. That is why these carry no
permission dependency - the rule is "yours", which a permission cannot say.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query

from app.core.dependencies import DbSession, PaginationDep
from app.modules.auth.dependencies import CurrentUser
from app.modules.notifications.schemas.notification import (
    MarkAllReadResult,
    MyNotification,
    MyNotificationDetail,
    UnreadCount,
)
from app.modules.notifications.services.user_notification import (
    UserNotificationService,
)
from app.shared.schemas.pagination import Page
from app.shared.schemas.response import (
    APIResponse,
    paginated_response,
    success_response,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])

NotificationId = Annotated[uuid.UUID, Path(description="Notification identifier.")]


@router.get(
    "",
    response_model=APIResponse[Page[MyNotification]],
    summary="List my notifications",
    description=(
        "The caller's own notifications, newest first.\n\n"
        "Withdrawn, deactivated and not-yet-published notifications are "
        "never included. Expired ones are hidden unless "
        "`include_expired=true`, and archived ones unless `is_archived` "
        "says otherwise."
    ),
)
async def list_my_notifications(
    db: DbSession,
    user: CurrentUser,
    pagination: PaginationDep,
    is_read: Annotated[
        bool | None, Query(description="Filter to read or unread only.")
    ] = None,
    is_archived: Annotated[
        bool | None,
        Query(description="Defaults to unarchived. Pass null for both."),
    ] = False,
    include_expired: Annotated[bool, Query()] = False,
) -> APIResponse[Page[MyNotification]]:
    items, total = await UserNotificationService(db).list_for_user(
        user.id,
        pagination,
        is_read=is_read,
        is_archived=is_archived,
        include_expired=include_expired,
    )
    return paginated_response(
        [MyNotification.from_recipient(item) for item in items],
        total,
        pagination,
        message="Notifications fetched",
    )


@router.get(
    "/unread-count",
    response_model=APIResponse[UnreadCount],
    summary="Count my unread notifications",
    description=(
        "The badge number. Archived and expired notifications are excluded: "
        "neither should keep a badge lit for something the recipient has "
        "put away or can no longer act on."
    ),
)
async def unread_count(db: DbSession, user: CurrentUser) -> APIResponse[UnreadCount]:
    count = await UserNotificationService(db).unread_count(user.id)
    return success_response(data=UnreadCount(count=count), message="Unread count")


@router.post(
    "/mark-all-read",
    response_model=APIResponse[MarkAllReadResult],
    summary="Mark all my notifications read",
)
async def mark_all_read(
    db: DbSession, user: CurrentUser
) -> APIResponse[MarkAllReadResult]:
    marked = await UserNotificationService(db).mark_all_read(user)
    return success_response(
        data=MarkAllReadResult(marked=marked),
        message=f"Marked {marked} notification(s) read",
    )


@router.get(
    "/{notification_id}",
    response_model=APIResponse[MyNotificationDetail],
    summary="Open one of my notifications",
    description=(
        "Returns the notification with its details content, and records "
        "that the caller saw it.\n\n"
        "The first open sets `is_read`, stamps `read_at` and moves the "
        "notification's `total_reads`; every open increments `read_count`. "
        "Pass `details_view=false` to read it without counting a details "
        "page view - for a client that expands the summary inline.\n\n"
        "A notification the caller was never sent returns `404`, not `403`: "
        "a `403` would confirm it exists and that somebody else has it."
    ),
)
async def get_my_notification(
    db: DbSession,
    user: CurrentUser,
    notification_id: NotificationId,
    details_view: Annotated[
        bool, Query(description="Whether this open is a details page view.")
    ] = True,
) -> APIResponse[MyNotificationDetail]:
    recipient = await UserNotificationService(db).open(
        notification_id, user, details_view=details_view
    )
    return success_response(
        data=MyNotificationDetail.from_recipient(recipient),
        message="Notification fetched",
    )


@router.post(
    "/{notification_id}/mark-read",
    response_model=APIResponse[MyNotification],
    summary="Mark one notification read",
    description="Records a read without counting a details page view.",
)
async def mark_read(
    db: DbSession, user: CurrentUser, notification_id: NotificationId
) -> APIResponse[MyNotification]:
    recipient = await UserNotificationService(db).mark_read(notification_id, user)
    return success_response(
        data=MyNotification.from_recipient(recipient), message="Marked read"
    )


@router.post(
    "/{notification_id}/archive",
    response_model=APIResponse[MyNotification],
    summary="Archive one of my notifications",
    description=(
        "Clears it from the default list without deleting the record that "
        "the caller was sent it."
    ),
)
async def archive(
    db: DbSession, user: CurrentUser, notification_id: NotificationId
) -> APIResponse[MyNotification]:
    recipient = await UserNotificationService(db).archive(notification_id, user)
    return success_response(
        data=MyNotification.from_recipient(recipient), message="Notification archived"
    )


@router.post(
    "/{notification_id}/unarchive",
    response_model=APIResponse[MyNotification],
    summary="Take one of my notifications back out of the archive",
)
async def unarchive(
    db: DbSession, user: CurrentUser, notification_id: NotificationId
) -> APIResponse[MyNotification]:
    recipient = await UserNotificationService(db).archive(
        notification_id, user, archived=False
    )
    return success_response(
        data=MyNotification.from_recipient(recipient),
        message="Notification unarchived",
    )
