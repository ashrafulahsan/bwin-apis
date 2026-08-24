"""What a recipient can do with their own notifications.

Separate from `NotificationService`, which is about authoring announcements.
This is about receiving them, and the difference is the security boundary:
nothing here takes a notification id without also taking the caller, and
every lookup goes through the caller's own recipient row.

This layer owns the transaction and writes the audit trail;
`NotificationRecipientService` underneath does the state changes and commits
nothing.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.activity_logs.models.activity_log import ActivityAction, ActivityModule
from app.modules.notifications.models.notification_recipient import (
    NotificationRecipient,
)
from app.modules.notifications.repositories.notification_recipient import (
    NotificationRecipientRepository,
)
from app.modules.notifications.services.notification_recipient import (
    NotificationRecipientService,
)
from app.modules.users.models.user import User
from app.shared.schemas.pagination import SupportsPagination
from app.shared.services.activity_log_service import ActivityLogService


class UserNotificationService:
    """The recipient's side of the notification system."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = NotificationRecipientRepository(session)
        self.recipients = NotificationRecipientService(session)
        self.activity = ActivityLogService(session, ActivityModule.NOTIFICATIONS)

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        pagination: SupportsPagination,
        *,
        is_read: bool | None = None,
        is_archived: bool | None = False,
        include_expired: bool = False,
    ) -> tuple[list[NotificationRecipient], int]:
        return await self.repository.paginate_for_user(
            user_id,
            offset=(pagination.page - 1) * pagination.page_size,
            limit=pagination.page_size,
            is_read=is_read,
            is_archived=is_archived,
            include_expired=include_expired,
        )

    async def unread_count(self, user_id: uuid.UUID) -> int:
        return await self.repository.count_unread(user_id)

    async def open(
        self, notification_id: uuid.UUID, actor: User, *, details_view: bool = True
    ) -> NotificationRecipient:
        """Return the caller's copy, recording that they saw it."""
        recipient = await self.recipients.get_for_user(notification_id, actor.id)

        first_read = await self.recipients.mark_read(recipient)
        if details_view:
            await self.recipients.record_detail_view(recipient)

        await self.activity.record(
            ActivityAction.VIEW if details_view else ActivityAction.READ,
            entity=recipient.notification,
            description=(
                f"{'Viewed' if details_view else 'Read'} notification "
                f"{recipient.notification.title!r}"
            ),
            new_values={
                "first_read": first_read,
                "details_view": details_view,
                "read_count": recipient.read_count,
            },
        )

        await self.session.commit()
        await self.session.refresh(recipient)
        return recipient

    async def mark_read(
        self, notification_id: uuid.UUID, actor: User
    ) -> NotificationRecipient:
        """Record a read without counting a details page view."""
        recipient = await self.recipients.get_for_user(notification_id, actor.id)
        first_read = await self.recipients.mark_read(recipient)

        await self.activity.record(
            ActivityAction.READ,
            entity=recipient.notification,
            description=(f"Marked notification {recipient.notification.title!r} read"),
            new_values={"first_read": first_read},
        )

        await self.session.commit()
        await self.session.refresh(recipient)
        return recipient

    async def mark_all_read(self, actor: User) -> int:
        """Mark everything visible and unread as read.

        One audit entry for the whole call rather than one per notification:
        the action the person took was "clear my badge", and recording it
        forty times would bury forty other things in the trail.
        """
        marked = await self.recipients.mark_all_read(actor.id)

        if marked:
            await self.activity.record(
                ActivityAction.READ,
                entity_type="NotificationRecipient",
                entity_id=str(actor.id),
                description=f"Marked {marked} notification(s) read",
                new_values={"marked": marked},
            )

        await self.session.commit()
        return marked

    async def archive(
        self, notification_id: uuid.UUID, actor: User, *, archived: bool = True
    ) -> NotificationRecipient:
        recipient = await self.recipients.get_for_user(notification_id, actor.id)
        updated = await self.recipients.archive(recipient, archived=archived)

        await self.activity.record(
            ActivityAction.ARCHIVE,
            entity=updated.notification,
            description=(
                f"{'Archived' if archived else 'Unarchived'} notification "
                f"{updated.notification.title!r}"
            ),
            new_values={"is_archived": archived},
        )

        await self.session.commit()
        return updated
