"""Business logic for notifications: writing them, sending them, reading them.

The service owns the transaction. A notification and the recipient rows that
give it an audience are committed together or not at all, because an
announcement that exists and reaches nobody is worse than one that failed
outright and said so.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SortOrder
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.notifications.constants import (
    NOTIFICATION_SEARCH_FIELDS,
    TARGETED_DELIVERY_TYPES,
    DeliveryType,
    NotificationPriority,
    NotificationType,
)
from app.modules.notifications.models.notification import Notification
from app.modules.notifications.models.notification_recipient import (
    NotificationRecipient,
)
from app.modules.notifications.repositories.notification import NotificationRepository
from app.modules.notifications.repositories.notification_recipient import (
    NotificationRecipientRepository,
)
from app.modules.notifications.schemas.notification import (
    NotificationCreate,
    NotificationStatistics,
    NotificationUpdate,
)
from app.modules.notifications.services.notification_recipient import (
    NotificationRecipientService,
)
from app.modules.roles.repositories.role import RoleRepository
from app.modules.users.models.user import User
from app.modules.users.repositories.user import UserRepository
from app.shared.repositories.filters import Filter
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import ActivityLogService, diff, snapshot


class NotificationService:
    """Creates, edits and withdraws notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = NotificationRepository(session)
        self.recipients = NotificationRecipientRepository(session)
        self.recipient_service = NotificationRecipientService(session)
        self.roles = RoleRepository(session)
        self.users = UserRepository(session)
        self.activity = ActivityLogService(session, ActivityModule.NOTIFICATIONS)

    # -- Writing -------------------------------------------------------------

    async def create(self, payload: NotificationCreate, *, actor: User) -> Notification:
        """Write an announcement and resolve its audience.

        The audience is resolved inside this transaction, so a delivery type
        that cannot reach anybody takes the whole thing down rather than
        leaving an announcement nobody will ever see.
        """
        await self._validate_targets(payload.delivery_type, payload.target_ids)

        notification = await self.repository.create(
            title=payload.title,
            short_message=payload.short_message,
            details_content=payload.details_content,
            notification_type=NotificationType.ADMIN.value,
            delivery_type=payload.delivery_type.value,
            target_ids=[str(target) for target in payload.target_ids],
            priority=payload.priority.value,
            icon=payload.icon,
            image_url=payload.image_url,
            has_details_page=payload.has_details_page,
            is_active=payload.is_active,
            publish_at=payload.publish_at,
            expires_at=payload.expires_at,
            created_by=actor.id,
            updated_by=actor.id,
        )

        total = await self.recipient_service.resolve(
            notification, target_ids=payload.target_ids
        )

        await self.activity.record(
            ActivityAction.CREATE,
            entity=notification,
            description=(
                f"Created notification {notification.title!r} for "
                f"{total} recipient(s)"
            ),
            new_values={
                "title": notification.title,
                "delivery_type": notification.delivery_type,
                "priority": notification.priority,
                "total_recipients": total,
            },
        )

        await self.session.commit()
        return notification

    async def update(
        self, notification_id: uuid.UUID, payload: NotificationUpdate, *, actor: User
    ) -> Notification:
        """Edit an announcement, before it is published.

        Published notifications are frozen. People have already read them,
        and rewriting the text afterwards would leave a reader remembering a
        different notice from the one on file - with `read_at` claiming they
        saw wording that never existed when they looked.

        Scheduling fields are the exception in the other direction: a
        notification that has not gone out yet may be rescheduled, and one
        that has may still be deactivated or given an expiry, because both
        withdraw it rather than rewrite it.
        """
        notification = await self.get(notification_id)
        changes = payload.model_dump(exclude_unset=True)

        if not changes:
            return notification

        if notification.is_published:
            self._reject_content_edits(changes)

        for field in ("delivery_type", "priority"):
            if changes.get(field) is not None:
                changes[field] = changes[field].value

        rebuild = "target_ids" in changes or "delivery_type" in changes
        if rebuild and notification.is_published:
            raise BadRequestException(
                "The audience of a published notification cannot be changed. "
                "Withdraw it and send a new one."
            )

        targets = changes.pop("target_ids", None)
        if targets is not None:
            changes["target_ids"] = [str(target) for target in targets]

        if rebuild:
            delivery = DeliveryType(
                changes.get("delivery_type", notification.delivery_type)
            )
            resolved_targets = (
                targets
                if targets is not None
                else [uuid.UUID(item) for item in notification.target_ids or []]
            )
            await self._validate_targets(delivery, resolved_targets)

        changes["updated_by"] = actor.id

        before = snapshot(notification, fields=changes.keys())
        updated = await self.repository.update(notification, **changes)

        if rebuild:
            total = await self.recipient_service.rebuild(
                updated, target_ids=resolved_targets
            )
        else:
            total = updated.total_recipients

        old_values, new_values = diff(before, snapshot(updated, fields=changes.keys()))
        if old_values or new_values:
            await self.activity.record(
                ActivityAction.UPDATE,
                entity=updated,
                description=(
                    f"Updated notification {updated.title!r}"
                    + (f", audience rebuilt to {total} recipient(s)" if rebuild else "")
                ),
                old_values=old_values,
                new_values=new_values,
            )

        await self.session.commit()
        return updated

    @staticmethod
    def _reject_content_edits(changes: dict[str, Any]) -> None:
        """Refuse the fields that rewrite what people already read."""
        frozen = {
            "title",
            "short_message",
            "details_content",
            "icon",
            "image_url",
            "has_details_page",
            "publish_at",
        } & changes.keys()

        if frozen:
            raise BadRequestException(
                "This notification has already been published, so "
                f"{', '.join(sorted(frozen))} can no longer be edited. "
                "Deactivating it or setting an expiry is still allowed."
            )

    async def delete(self, notification_id: uuid.UUID, *, actor: User) -> None:
        """Withdraw a notification.

        Soft deleted, which takes it out of every recipient's list at once:
        the user-side queries join through the notification, so one flag
        withdraws it for everybody without touching a recipient row.
        """
        notification = await self.get(notification_id)
        before = snapshot(notification, exclude={"details_content"})

        await self.repository.soft_delete(notification)
        await self.activity.record(
            ActivityAction.DELETE,
            entity=notification,
            description=f"Deleted notification {notification.title!r}",
            old_values=before,
        )
        await self.session.commit()

    async def restore(self, notification_id: uuid.UUID, *, actor: User) -> Notification:
        notification = await self.repository.get_or_raise(
            notification_id, include_deleted=True
        )
        restored = await self.repository.restore(notification)

        await self.activity.record(
            ActivityAction.RESTORE,
            entity=restored,
            description=f"Restored notification {restored.title!r}",
            new_values={"title": restored.title},
        )
        await self.session.commit()
        return restored

    # -- Reading -------------------------------------------------------------

    async def get(self, notification_id: uuid.UUID) -> Notification:
        return await self.repository.get_or_raise(notification_id)

    async def list_notifications(
        self,
        pagination: SupportsPagination,
        *,
        search: str | None = None,
        notification_type: NotificationType | None = None,
        delivery_type: DeliveryType | None = None,
        priority: NotificationPriority | None = None,
        created_by: uuid.UUID | None = None,
        is_active: bool | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        sort_by: str | None = None,
        sort_order: SortOrder = SortOrder.DESC,
    ) -> tuple[list[Notification], int]:
        filters: list[Filter] = []

        if notification_type is not None:
            filters.append(Filter.eq("notification_type", notification_type.value))
        if delivery_type is not None:
            filters.append(Filter.eq("delivery_type", delivery_type.value))
        if priority is not None:
            filters.append(Filter.eq("priority", priority.value))
        if created_by is not None:
            filters.append(Filter.eq("created_by", created_by))
        if is_active is not None:
            filters.append(Filter.eq("is_active", is_active))
        if date_from is not None:
            filters.append(Filter.gte("created_at", date_from))
        if date_to is not None:
            filters.append(Filter.lte("created_at", date_to))

        return await self.repository.paginate(
            pagination,
            filters=filters,
            search=search,
            search_fields=list(NOTIFICATION_SEARCH_FIELDS),
            sort_by=sort_by or "created_at",
            sort_order=sort_order,
        )

    async def statistics(self, notification_id: uuid.UUID) -> NotificationStatistics:
        """Engagement for one notification, counted from the recipient rows.

        Counted rather than read off the denormalized columns: this is the
        screen where the numbers are being scrutinised, and it is worth being
        the one place that goes back to the source.
        """
        await self.get(notification_id)
        figures = await self.recipients.engagement(notification_id)

        total = figures["total_recipients"]
        reads = figures["total_reads"]
        viewers = figures["unique_detail_viewers"]

        return NotificationStatistics(
            total_recipients=total,
            total_reads=reads,
            total_unread=figures["total_unread"],
            total_detail_views=figures["total_detail_views"],
            unique_detail_viewers=viewers,
            total_archived=figures["total_archived"],
            read_percentage=round(reads / total * 100, 1) if total else 0.0,
            detail_view_percentage=round(viewers / total * 100, 1) if total else 0.0,
        )

    async def list_recipients(
        self,
        notification_id: uuid.UUID,
        pagination: SupportsPagination,
        *,
        is_read: bool | None = None,
    ) -> tuple[list[NotificationRecipient], int]:
        await self.get(notification_id)
        return await self.recipients.paginate_recipients(
            notification_id,
            offset=(pagination.page - 1) * pagination.page_size,
            limit=pagination.page_size,
            is_read=is_read,
        )

    # -- Internals -----------------------------------------------------------

    async def _validate_targets(
        self, delivery_type: DeliveryType, target_ids: list[uuid.UUID]
    ) -> None:
        """Check the targets exist before anything is written.

        A role or user id that does not resolve would otherwise shrink the
        audience silently - the notification would be created, reach fewer
        people than intended, and report success.
        """
        if delivery_type not in TARGETED_DELIVERY_TYPES:
            return

        if delivery_type is DeliveryType.ROLE:
            for role_id in target_ids:
                if await self.roles.get(role_id) is None:
                    raise NotFoundException(f"Role '{role_id}'")

        elif delivery_type is DeliveryType.USER:
            for user_id in target_ids:
                if await self.users.get(user_id) is None:
                    raise NotFoundException(f"User '{user_id}'")

        # Course targets are checked by the resolver, which is also where the
        # missing enrolment table is reported.
