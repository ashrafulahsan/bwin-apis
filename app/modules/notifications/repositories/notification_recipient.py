"""Data access for notification recipients.

The inserts here are set-based on purpose. A global notification on a
platform with fifty thousand accounts must not become fifty thousand ORM
objects held in memory and flushed one by one - it is `INSERT ... SELECT`,
which never leaves the database.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.notifications.models.notification import Notification
from app.modules.notifications.models.notification_recipient import (
    NotificationRecipient,
)
from app.modules.users.constants import UserStatus
from app.modules.users.models.user import User
from app.modules.users.models.user_role import user_roles
from app.shared.repositories.base import BaseRepository
from app.shared.utils.dates import utc_now


class NotificationRecipientRepository(BaseRepository[NotificationRecipient]):
    model = NotificationRecipient
    default_sort_by = "created_at"

    # -- Audience resolution ------------------------------------------------

    def _active_users(self) -> Select[tuple[uuid.UUID]]:
        """Accounts eligible to receive anything.

        Suspended, pending and closed accounts are excluded: a notification
        is something a person is expected to act on, and none of them can
        sign in to do so.
        """
        return select(User.id).where(
            User.status == UserStatus.ACTIVE.value,
            User.deleted_at.is_(None),
        )

    async def _insert_from_select(
        self, notification_id: uuid.UUID, user_ids: Select[tuple[uuid.UUID]]
    ) -> int:
        """Create recipient rows from a query, skipping anyone already there.

        `ON CONFLICT DO NOTHING` against the unique pair makes this safe to
        run twice, which is what lets an audience be re-resolved without
        anybody receiving two copies.
        """
        statement = pg_insert(NotificationRecipient).from_select(
            ["notification_id", "user_id", "delivered_at"],
            select(
                func.cast(notification_id, NotificationRecipient.notification_id.type),
                user_ids.subquery().c.id,
                func.now(),
            ),
        )
        statement = statement.on_conflict_do_nothing(
            constraint="uq_notification_recipients_pair"
        )

        result = await self.session.execute(statement)
        return int(result.rowcount or 0)

    async def add_all_active_users(self, notification_id: uuid.UUID) -> int:
        return await self._insert_from_select(notification_id, self._active_users())

    async def add_users_in_roles(
        self, notification_id: uuid.UUID, role_ids: Sequence[uuid.UUID]
    ) -> int:
        if not role_ids:
            return 0

        # `DISTINCT`: somebody holding two of the targeted roles is still one
        # person, and without it the insert would offer the same pair twice
        # inside one statement, which `ON CONFLICT` cannot absorb.
        query = (
            self._active_users()
            .distinct()
            .join(user_roles, user_roles.c.user_id == User.id)
            .where(user_roles.c.role_id.in_(role_ids))
        )
        return await self._insert_from_select(notification_id, query)

    async def add_users(
        self, notification_id: uuid.UUID, user_ids: Sequence[uuid.UUID]
    ) -> int:
        if not user_ids:
            return 0

        query = self._active_users().where(User.id.in_(user_ids))
        return await self._insert_from_select(notification_id, query)

    async def clear_for_notification(self, notification_id: uuid.UUID) -> int:
        """Remove every recipient row, for an audience being rebuilt."""
        result = await self.session.execute(
            NotificationRecipient.__table__.delete().where(
                NotificationRecipient.notification_id == notification_id
            )
        )
        await self.session.flush()
        return int(result.rowcount or 0)

    async def count_for_notification(self, notification_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(NotificationRecipient)
            .where(NotificationRecipient.notification_id == notification_id)
        )
        return int(result.scalar_one())

    # -- One person's copy ---------------------------------------------------

    async def get_for_user(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationRecipient | None:
        """The caller's own row, which is the only one they may ever see."""
        result = await self.session.execute(
            select(NotificationRecipient).where(
                NotificationRecipient.notification_id == notification_id,
                NotificationRecipient.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    def _visible_now(self, moment: datetime) -> list[object]:
        """Conditions restricting a listing to notifications on display."""
        return [
            Notification.deleted_at.is_(None),
            Notification.is_active.is_(True),
            or_(Notification.publish_at.is_(None), Notification.publish_at <= moment),
        ]

    def _not_expired(self, moment: datetime) -> object:
        return or_(Notification.expires_at.is_(None), Notification.expires_at > moment)

    async def paginate_for_user(
        self,
        user_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
        is_read: bool | None = None,
        is_archived: bool | None = False,
        include_expired: bool = False,
    ) -> tuple[list[NotificationRecipient], int]:
        """One page of a person's notifications, newest first.

        Joined to `notifications` rather than filtered on the recipient rows
        alone, because whether a notification is visible - active, published,
        not withdrawn - is a property of the notification, and a row here for
        a withdrawn one must not surface.
        """
        moment = utc_now()
        conditions: list[object] = [
            NotificationRecipient.user_id == user_id,
            *self._visible_now(moment),
        ]

        if not include_expired:
            conditions.append(self._not_expired(moment))
        if is_read is not None:
            conditions.append(NotificationRecipient.is_read.is_(is_read))
        if is_archived is not None:
            conditions.append(NotificationRecipient.is_archived.is_(is_archived))

        base = (
            select(NotificationRecipient)
            .join(
                Notification,
                Notification.id == NotificationRecipient.notification_id,
            )
            .where(and_(*conditions))
        )

        total = await self.session.execute(
            select(func.count())
            .select_from(NotificationRecipient)
            .join(
                Notification,
                Notification.id == NotificationRecipient.notification_id,
            )
            .where(and_(*conditions))
        )

        rows = await self.session.execute(
            base.order_by(
                NotificationRecipient.created_at.desc(),
                NotificationRecipient.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )

        return list(rows.scalars().all()), int(total.scalar_one())

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """The badge number.

        Expired and archived notifications are excluded: neither should keep
        a badge lit for something the person can no longer act on or has
        already put away.
        """
        moment = utc_now()

        result = await self.session.execute(
            select(func.count())
            .select_from(NotificationRecipient)
            .join(
                Notification,
                Notification.id == NotificationRecipient.notification_id,
            )
            .where(
                NotificationRecipient.user_id == user_id,
                NotificationRecipient.is_read.is_(False),
                NotificationRecipient.is_archived.is_(False),
                *self._visible_now(moment),
                self._not_expired(moment),
            )
        )
        return int(result.scalar_one())

    async def mark_all_read(self, user_id: uuid.UUID) -> list[uuid.UUID]:
        """Mark every visible unread notification read, in one statement.

        Returns the notification ids that actually changed, so the caller can
        move each one's `total_reads` by exactly the right amount - marking
        all read must not add a read to a notification that was already read.
        """
        moment = utc_now()

        unread = (
            select(NotificationRecipient.id, NotificationRecipient.notification_id)
            .join(
                Notification,
                Notification.id == NotificationRecipient.notification_id,
            )
            .where(
                NotificationRecipient.user_id == user_id,
                NotificationRecipient.is_read.is_(False),
                *self._visible_now(moment),
                self._not_expired(moment),
            )
        )
        rows = (await self.session.execute(unread)).all()
        if not rows:
            return []

        recipient_ids = [row[0] for row in rows]

        await self.session.execute(
            update(NotificationRecipient)
            .where(NotificationRecipient.id.in_(recipient_ids))
            .values(
                is_read=True,
                read_at=moment,
                last_viewed_at=moment,
                read_count=NotificationRecipient.read_count + 1,
            )
        )
        await self.session.flush()

        return [row[1] for row in rows]

    # -- Engagement figures ---------------------------------------------------

    async def engagement(self, notification_id: uuid.UUID) -> dict[str, int]:
        """Read, view and archive tallies for one notification."""
        result = await self.session.execute(
            select(
                func.count(),
                func.count().filter(NotificationRecipient.is_read.is_(True)),
                func.count().filter(NotificationRecipient.details_viewed.is_(True)),
                func.count().filter(NotificationRecipient.is_archived.is_(True)),
                func.coalesce(func.sum(NotificationRecipient.details_view_count), 0),
            )
            .select_from(NotificationRecipient)
            .where(NotificationRecipient.notification_id == notification_id)
        )
        total, read, viewers, archived, views = result.one()

        return {
            "total_recipients": int(total),
            "total_reads": int(read),
            "total_unread": int(total) - int(read),
            "unique_detail_viewers": int(viewers),
            "total_archived": int(archived),
            "total_detail_views": int(views),
        }

    async def paginate_recipients(
        self,
        notification_id: uuid.UUID,
        *,
        offset: int,
        limit: int,
        is_read: bool | None = None,
    ) -> tuple[list[NotificationRecipient], int]:
        """Who received one notification, for the administrative view."""
        conditions: list[object] = [
            NotificationRecipient.notification_id == notification_id
        ]
        if is_read is not None:
            conditions.append(NotificationRecipient.is_read.is_(is_read))

        total = await self.session.execute(
            select(func.count())
            .select_from(NotificationRecipient)
            .where(and_(*conditions))
        )
        rows = await self.session.execute(
            select(NotificationRecipient)
            .where(and_(*conditions))
            .order_by(NotificationRecipient.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

        return list(rows.scalars().all()), int(total.scalar_one())
