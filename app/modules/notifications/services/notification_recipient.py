"""Resolving audiences, and tracking what each recipient did.

Two responsibilities that look separate and are not: both are about the
relationship between one notification and one person, and both are the only
things allowed to move the counters on `notifications`.

Nothing here commits. The service that owns the operation does, so a
notification and its recipient rows land in the same transaction - an
announcement that committed without its audience would exist and reach
nobody.
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.notifications.constants import DeliveryType
from app.modules.notifications.models.notification import Notification
from app.modules.notifications.models.notification_recipient import (
    NotificationRecipient,
)
from app.modules.notifications.repositories.notification import NotificationRepository
from app.modules.notifications.repositories.notification_recipient import (
    NotificationRecipientRepository,
)
from app.shared.utils.dates import utc_now

logger = logging.getLogger(__name__)


class NotificationRecipientService:
    """Builds audiences and records engagement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = NotificationRecipientRepository(session)
        self.notifications = NotificationRepository(session)

    # -- Resolution ---------------------------------------------------------

    async def resolve(
        self,
        notification: Notification,
        *,
        target_ids: Sequence[uuid.UUID] | None = None,
    ) -> int:
        """Create the recipient rows for a notification's audience.

        Returns how many people it reached, which becomes
        `total_recipients`. Safe to run again: the unique pair means a second
        pass adds only whoever was not already there.
        """
        delivery = DeliveryType(notification.delivery_type)
        targets = list(target_ids or notification.target_ids or [])

        if delivery is DeliveryType.GLOBAL:
            await self.repository.add_all_active_users(notification.id)
        elif delivery is DeliveryType.ROLE:
            await self.repository.add_users_in_roles(notification.id, targets)
        elif delivery is DeliveryType.USER:
            await self.repository.add_users(notification.id, targets)
        elif delivery is DeliveryType.COURSE:
            await self._resolve_course(notification, targets)

        # Counted rather than summed from the inserts: re-resolving an
        # audience skips the rows that already existed, so the number of rows
        # written is not the number of people reached.
        total = await self.repository.count_for_notification(notification.id)
        await self.notifications.set_recipient_total(notification.id, total)
        await self.session.flush()
        await self.session.refresh(notification)

        if total == 0:
            logger.warning("Notification %s resolved to no recipients", notification.id)

        return total

    async def _resolve_course(
        self, notification: Notification, course_ids: Sequence[uuid.UUID]
    ) -> None:
        """Reach everyone enrolled on the named courses.

        **Not yet implementable.** Course-wise delivery needs to know who is
        enrolled, and this platform has no enrolment table: there is no link
        of any kind between a user and a course in the schema. When one
        lands, this method becomes a single call to a repository query over
        it, and nothing else in the module changes.

        It refuses rather than reaching nobody quietly. An administrator
        announcing a new batch to a course, being told it worked, and having
        it arrive with no one is the worst outcome available here - far worse
        than an error that says exactly what is missing.
        """
        raise BadRequestException(
            "Course-wise delivery is not available: this platform has no "
            "enrolment records yet, so there is no way to tell who is on a "
            "course. Send to the relevant roles or to named users instead."
        )

    async def rebuild(
        self, notification: Notification, *, target_ids: Sequence[uuid.UUID] | None
    ) -> int:
        """Replace a notification's audience wholesale.

        Every existing recipient row is discarded, which also discards
        whatever those people had read. That is only acceptable before
        publication - the notification service is what enforces it.
        """
        await self.repository.clear_for_notification(notification.id)
        await self.notifications.reset_engagement(notification.id)

        return await self.resolve(notification, target_ids=target_ids)

    # -- One person's copy ---------------------------------------------------

    async def get_for_user(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationRecipient:
        """The caller's own copy, or a 404.

        A notification the caller was never sent is reported as missing
        rather than forbidden. A 403 would confirm that a notification with
        that id exists and that somebody else received it, which is more than
        a stranger should be able to learn from an id.
        """
        recipient = await self.repository.get_for_user(notification_id, user_id)

        if recipient is None or not recipient.notification.is_visible:
            raise NotFoundException("Notification")

        return recipient

    async def mark_read(self, recipient: NotificationRecipient) -> bool:
        """Record a read. Returns whether this was the first one.

        `read_count` moves every time, because it counts readings.
        `is_read`, `read_at` and the notification's `total_reads` move only
        once - `total_reads` is the numerator of the read percentage, and a
        person re-reading must not push it past the number of recipients.
        """
        moment = utc_now()
        first_read = not recipient.is_read

        recipient.read_count += 1
        recipient.last_viewed_at = moment
        if first_read:
            recipient.is_read = True
            recipient.read_at = moment

        await self.session.flush()

        if first_read:
            await self.notifications.adjust_counters(recipient.notification_id, reads=1)

        return first_read

    async def record_detail_view(self, recipient: NotificationRecipient) -> None:
        """Record an opening of the details page.

        Unlike reads this is cumulative on the notification too: coming back
        to a notice a third time is signal, and `total_detail_views` is the
        only place it is visible in aggregate.
        """
        moment = utc_now()

        recipient.details_view_count += 1
        recipient.last_viewed_at = moment
        if not recipient.details_viewed:
            recipient.details_viewed = True
            recipient.details_viewed_at = moment

        await self.session.flush()
        await self.notifications.adjust_counters(
            recipient.notification_id, detail_views=1
        )

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """Mark everything visible and unread as read. Returns how many.

        Each affected notification's `total_reads` is moved by one per
        person, from the ids the update actually touched - anything already
        read is untouched and uncounted.
        """
        notification_ids = await self.repository.mark_all_read(user_id)

        for notification_id in notification_ids:
            await self.notifications.adjust_counters(notification_id, reads=1)

        return len(notification_ids)

    async def archive(
        self, recipient: NotificationRecipient, *, archived: bool = True
    ) -> NotificationRecipient:
        """Put a notification away, or take it back out."""
        recipient.is_archived = archived
        recipient.archived_at = utc_now() if archived else None

        await self.session.flush()
        await self.session.refresh(recipient)

        return recipient
