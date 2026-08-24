"""The one way another module raises a notification.

Every part of the platform that wants to tell somebody something goes through
`NotificationManager`. That is what keeps the same event worded the same way
wherever it is raised from, and what stops a dozen modules each learning the
shape of two tables.

**It never commits.** The notification is written into the caller's session
and lands with whatever the caller was doing - a "course completed" notice
that survives a rolled back completion is a message about something that did
not happen. The caller commits; if the caller fails, the notice goes with it.

**It never raises into the caller.** `send` returns `None` when it cannot
build a notification, having logged why. A notification is a side effect of
something else succeeding, and failing an enrolment because its congratulatory
notice could not be written would be the wrong trade every time. Callers who
genuinely need to know can check the return value.
"""

import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.constants import (
    SYSTEM_EVENT_TEMPLATES,
    DeliveryType,
    NotificationPriority,
    NotificationType,
    SystemEvent,
)
from app.modules.notifications.models.notification import Notification
from app.modules.notifications.repositories.notification import NotificationRepository
from app.modules.notifications.services.notification_recipient import (
    NotificationRecipientService,
)

logger = logging.getLogger(__name__)


class NotificationManager:
    """Raises system notifications from anywhere in the platform.

        await NotificationManager(session).send(
            title="Course Completed",
            short_message="Congratulations",
            details_content="Your certificate is ready.",
            user_ids=[learner.id],
        )

    Or, preferably, by event - which supplies the standard wording:

        await NotificationManager(session).send_event(
            SystemEvent.COURSE_COMPLETED,
            user_ids=[learner.id],
            details_content=f"You have completed {course.title}.",
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = NotificationRepository(session)
        self.recipients = NotificationRecipientService(session)

    async def send(
        self,
        *,
        title: str,
        short_message: str,
        details_content: str,
        user_ids: Sequence[uuid.UUID] | None = None,
        role_ids: Sequence[uuid.UUID] | None = None,
        delivery_type: DeliveryType | None = None,
        notification_type: NotificationType = NotificationType.SYSTEM,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        icon: str | None = None,
        image_url: str | None = None,
        has_details_page: bool = True,
        expires_at: object = None,
        created_by: uuid.UUID | None = None,
    ) -> Notification | None:
        """Write a notification and resolve its audience.

        The audience is inferred: `user_ids` means those people, `role_ids`
        means those roles, and neither means everybody. Pass `delivery_type`
        explicitly to be sure rather than inferred.

        Returns the notification, or `None` if it could not be written.
        """
        resolved_delivery = delivery_type or self._infer_delivery(user_ids, role_ids)
        targets = list(user_ids or role_ids or [])

        if resolved_delivery in {DeliveryType.USER, DeliveryType.ROLE} and not targets:
            logger.warning(
                "Refusing to send the notification %r: %s delivery with no "
                "targets would reach nobody.",
                title,
                resolved_delivery.value,
            )
            return None

        try:
            notification = await self.repository.create(
                title=title,
                short_message=short_message,
                details_content=details_content,
                notification_type=notification_type.value,
                delivery_type=resolved_delivery.value,
                target_ids=[str(target) for target in targets],
                priority=priority.value,
                icon=icon,
                image_url=image_url,
                has_details_page=has_details_page,
                is_active=True,
                expires_at=expires_at,
                created_by=created_by,
            )

            total = await self.recipients.resolve(notification, target_ids=targets)
        except SQLAlchemyError:
            # Logged and swallowed: see the module docstring. The caller's
            # transaction is still theirs to commit or roll back.
            logger.exception("Could not raise the notification %r", title)
            return None

        if total == 0:
            logger.warning("Notification %r reached no recipients", title)

        return notification

    async def send_event(
        self,
        event: SystemEvent,
        *,
        user_ids: Sequence[uuid.UUID] | None = None,
        role_ids: Sequence[uuid.UUID] | None = None,
        title: str | None = None,
        short_message: str | None = None,
        details_content: str | None = None,
        priority: NotificationPriority | None = None,
        **extra: object,
    ) -> Notification | None:
        """Raise one of the platform's known events.

        The template supplies the wording; anything passed here overrides it.
        Preferred over `send` for anything the platform raises repeatedly,
        because it is what keeps "Certificate Generated" phrased identically
        every time it happens.
        """
        template = SYSTEM_EVENT_TEMPLATES.get(event, {})

        resolved_title = title or template.get("title")
        resolved_message = short_message or template.get("short_message")

        if not resolved_title or not resolved_message:
            logger.error(
                "No wording for the system event %r and none supplied", event.value
            )
            return None

        resolved_priority = priority or NotificationPriority(
            template.get("priority", NotificationPriority.NORMAL)
        )

        return await self.send(
            title=resolved_title,
            short_message=resolved_message,
            # A details page with nothing on it is worse than none, so an
            # event without a body falls back to repeating the summary.
            details_content=details_content or resolved_message,
            user_ids=user_ids,
            role_ids=role_ids,
            priority=resolved_priority,
            **extra,  # type: ignore[arg-type]
        )

    @staticmethod
    def _infer_delivery(
        user_ids: Sequence[uuid.UUID] | None, role_ids: Sequence[uuid.UUID] | None
    ) -> DeliveryType:
        if user_ids:
            return DeliveryType.USER
        if role_ids:
            return DeliveryType.ROLE
        return DeliveryType.GLOBAL
