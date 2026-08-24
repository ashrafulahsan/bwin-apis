"""Data access for notifications."""

import uuid

from sqlalchemy import select, update

from app.modules.notifications.models.notification import Notification
from app.shared.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    model = Notification
    default_sort_by = "created_at"

    async def adjust_counters(
        self,
        notification_id: uuid.UUID,
        *,
        recipients: int = 0,
        reads: int = 0,
        detail_views: int = 0,
    ) -> None:
        """Move the denormalized counters, in SQL rather than in Python.

        `total_reads = total_reads + 1` as an UPDATE, not a read followed by
        a write: a global notification is read by many people at once, and
        two requests that both read the old value would between them record
        one read instead of two.

        Addressed by id rather than through a loaded instance, because the
        caller usually holds the recipient row and not the notification.
        """
        values: dict[str, object] = {}
        if recipients:
            values["total_recipients"] = Notification.total_recipients + recipients
        if reads:
            values["total_reads"] = Notification.total_reads + reads
        if detail_views:
            values["total_detail_views"] = (
                Notification.total_detail_views + detail_views
            )

        if not values:
            return

        await self.session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(**values)
        )

    async def set_recipient_total(self, notification_id: uuid.UUID, total: int) -> None:
        """Set the recipient count outright, after resolving an audience."""
        await self.session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(total_recipients=total)
        )

    async def reset_engagement(self, notification_id: uuid.UUID) -> None:
        """Zero the read counters, for an audience that is being rebuilt."""
        await self.session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(total_reads=0, total_detail_views=0)
        )

    async def title_exists(
        self, title: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [Notification.title == title, Notification.deleted_at.is_(None)]
        if exclude_id is not None:
            conditions.append(Notification.id != exclude_id)

        result = await self.session.execute(
            select(select(Notification.id).where(*conditions).exists())
        )
        return bool(result.scalar_one())
