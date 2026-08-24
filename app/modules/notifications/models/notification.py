"""Notification model: one announcement, however many people receive it."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.notifications.constants import (
    NOTIFICATION_ICON_MAX_LENGTH,
    NOTIFICATION_IMAGE_URL_MAX_LENGTH,
    NOTIFICATION_TITLE_MAX_LENGTH,
    DeliveryType,
    NotificationPriority,
    NotificationType,
)
from app.modules.users.models.user import User
from app.shared.utils.dates import utc_now


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """The announcement itself, written once.

    Who receives it lives in `notification_recipients`, one row per person.
    That split is what makes a global notification one row here rather than
    one per user, and it is also what makes "who has read this" answerable
    without a second system.

    The three counters are denormalized. A notification list is read far more
    often than a notification is sent, and every row wants "how many people
    have seen this" without a correlated subquery. The recipient service is
    their only writer.
    """

    title: Mapped[str] = mapped_column(
        String(NOTIFICATION_TITLE_MAX_LENGTH), nullable=False
    )
    short_message: Mapped[str] = mapped_column(
        Text, nullable=False, doc="The line shown in the notification list."
    )
    details_content: Mapped[str] = mapped_column(
        Text, nullable=False, doc="The body of the details page. May be HTML."
    )

    notification_type: Mapped[str] = mapped_column(
        String(50),
        default=NotificationType.ADMIN.value,
        server_default=NotificationType.ADMIN.value,
        nullable=False,
        index=True,
    )
    delivery_type: Mapped[str] = mapped_column(
        String(50),
        default=DeliveryType.GLOBAL.value,
        server_default=DeliveryType.GLOBAL.value,
        nullable=False,
        index=True,
    )
    target_ids: Mapped[list | None] = mapped_column(
        JSONB,
        default=None,
        doc=(
            "The roles, courses or users this was aimed at. Kept after the "
            "recipients are resolved so the audience can still be described "
            "on the details page, and so an unpublished notification can be "
            "re-resolved when its targets are edited."
        ),
    )
    priority: Mapped[str] = mapped_column(
        String(50),
        default=NotificationPriority.NORMAL.value,
        server_default=NotificationPriority.NORMAL.value,
        nullable=False,
        index=True,
    )

    icon: Mapped[str | None] = mapped_column(
        String(NOTIFICATION_ICON_MAX_LENGTH), default=None
    )
    image_url: Mapped[str | None] = mapped_column(
        String(NOTIFICATION_IMAGE_URL_MAX_LENGTH), default=None
    )
    has_details_page: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
        doc="False for a notice that says everything in its short message.",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False, index=True
    )

    publish_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
        doc="When it becomes visible. Null means immediately.",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
        doc="When it stops being shown. Null means never.",
    )

    # -- Denormalized engagement counters ----------------------------------
    total_recipients: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    total_reads: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc=(
            "Recipients who have read it, counted once each. Unique rather "
            "than cumulative because it is the numerator of the read "
            "percentage, which a re-read must not push past 100."
        ),
    )
    total_detail_views: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc=(
            "Details pages opened, counted every time. Cumulative rather "
            "than unique on purpose - unlike reads it measures how often "
            "people came back, not how far the notice reached."
        ),
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        default=None,
        index=True,
        doc="Null for a system notification, which nobody authored.",
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    author: Mapped[User | None] = relationship(
        lazy="selectin", foreign_keys=lambda: [Notification.created_by]
    )

    __table_args__ = (
        Index("ix_notifications_created_at", "created_at"),
        # The admin listing, and the window every user-side read filters on.
        Index("ix_notifications_is_active_publish_at", "is_active", "publish_at"),
    )

    # -- Derived state --------------------------------------------------------

    @property
    def is_published(self) -> bool:
        """Whether its publication moment has arrived."""
        return self.publish_at is None or self.publish_at <= utc_now()

    @property
    def is_scheduled(self) -> bool:
        return self.publish_at is not None and self.publish_at > utc_now()

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= utc_now()

    @property
    def is_visible(self) -> bool:
        """Whether a recipient should currently be shown this."""
        return self.is_active and self.is_published and not self.is_expired

    @property
    def read_percentage(self) -> float:
        """Share of recipients who have read it, to one decimal place."""
        if not self.total_recipients:
            return 0.0
        return round(self.total_reads / self.total_recipients * 100, 1)

    def __repr__(self) -> str:
        return f"<Notification {self.title!r} {self.delivery_type}>"
