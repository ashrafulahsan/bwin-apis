"""Notification recipient model: one person's copy of one notification."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.notifications.models.notification import Notification
from app.modules.users.models.user import User


class NotificationRecipient(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """What one person did with one notification.

    Materialized at send time rather than computed at read time. Working out
    "is this person in a role that was targeted" on every list request would
    mean the answer changes when their roles change - somebody promoted in
    March would retroactively receive February's announcements, and somebody
    who left would lose the record of what they were told.

    There is no `deleted_at`: a recipient row is not content, it is the
    record that a person was told something. Removing the notification soft
    deletes the parent, which is what takes it out of every view; the rows
    here go only when the notification is erased for real.
    """

    notification_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        doc="When the row was created, which is when it became visible.",
    )

    # -- Read tracking -------------------------------------------------------
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        index=True,
        doc="First read. Never revised, so 'how quickly' stays answerable.",
    )
    read_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
        doc="Every read, including the ones after the first.",
    )

    # -- Details page tracking -----------------------------------------------
    details_viewed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    details_view_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    details_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, doc="First opening of the details page."
    )
    last_viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, doc="Most recent interaction."
    )

    # -- Archiving -----------------------------------------------------------
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        doc="Cleared from the person's list without deleting the record.",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    notification: Mapped[Notification] = relationship(
        lazy="selectin",
        foreign_keys=lambda: [NotificationRecipient.notification_id],
    )
    user: Mapped[User] = relationship(
        lazy="selectin", foreign_keys=lambda: [NotificationRecipient.user_id]
    )

    __table_args__ = (
        # One copy per person. This is what makes re-resolving an audience
        # safe: a second send to an overlapping group cannot duplicate
        # anybody's row, so `ON CONFLICT DO NOTHING` is a correct no-op.
        UniqueConstraint(
            "notification_id", "user_id", name="uq_notification_recipients_pair"
        ),
        # "My notifications, unread first, newest first" - the query behind
        # both the list and the badge count.
        Index(
            "ix_notification_recipients_user_id_is_read",
            "user_id",
            "is_read",
        ),
        Index("ix_notification_recipients_created_at", "created_at"),
        Index(
            "ix_notification_recipients_details_viewed",
            "details_viewed",
        ),
    )

    def __repr__(self) -> str:
        return f"<NotificationRecipient user={self.user_id} " f"read={self.is_read}>"
